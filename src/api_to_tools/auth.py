"""Authentication utilities."""

from __future__ import annotations

import httpx

from api_to_tools.types import AuthConfig


def build_auth_headers(auth: AuthConfig) -> dict[str, str]:
    """Build HTTP headers from auth config."""
    headers: dict[str, str] = {}

    if auth.type == "basic":
        import base64
        creds = base64.b64encode(f"{auth.username}:{auth.password}".encode()).decode()
        headers["Authorization"] = f"Basic {creds}"

    elif auth.type == "bearer":
        headers["Authorization"] = f"Bearer {auth.token}"

    elif auth.type == "api_key" and auth.location == "header":
        if auth.key and auth.value:
            headers[auth.key] = auth.value

    elif auth.type == "custom":
        headers.update(auth.headers)

    return headers


def build_auth_params(auth: AuthConfig) -> dict[str, str]:
    """Build query parameters from auth config."""
    if auth.type == "api_key" and auth.location == "query" and auth.key and auth.value:
        return {auth.key: auth.value}
    return {}


def build_auth_cookies(auth: AuthConfig) -> dict[str, str]:
    """Get cookies from auth config, performing login if needed."""
    if auth.type != "cookie":
        return {}

    # Direct cookies provided
    if auth.cookies:
        return dict(auth.cookies)

    # Login flow
    if auth.login_url and auth.username and auth.password:
        return _perform_login(auth)

    return {}


def _perform_login(auth: AuthConfig) -> dict[str, str]:
    """Perform form-based login and return session cookies."""
    username_field = auth.login_fields.get("username_field", "username")
    password_field = auth.login_fields.get("password_field", "password")

    with httpx.Client(follow_redirects=True) as client:
        # First GET the login page (to pick up CSRF tokens, etc.)
        login_page = client.get(auth.login_url, timeout=15)
        cookies = dict(login_page.cookies)

        # Extract CSRF token if present
        csrf_token = None
        csrf_field = auth.login_fields.get("csrf_field")
        if csrf_field:
            import re
            m = re.search(rf'name=["\']?{csrf_field}["\']?\s+value=["\']([^"\']+)["\']', login_page.text)
            if m:
                csrf_token = m.group(1)

        # Build form data
        form_data = {
            username_field: auth.username,
            password_field: auth.password,
        }
        if csrf_field and csrf_token:
            form_data[csrf_field] = csrf_token

        # Add any extra login fields
        for k, v in auth.login_fields.items():
            if k not in ("username_field", "password_field", "csrf_field"):
                form_data[k] = v

        # POST login
        res = client.post(
            auth.login_url,
            data=form_data,
            cookies=cookies,
            timeout=15,
        )

        # Merge all cookies from the session
        all_cookies = dict(login_page.cookies)
        all_cookies.update(dict(res.cookies))
        return all_cookies


def _obtain_oauth2_token(auth: AuthConfig) -> str:
    """Obtain OAuth2 token via client credentials flow."""
    if not auth.token_url or not auth.client_id or not auth.client_secret:
        raise ValueError("OAuth2 requires token_url, client_id, and client_secret")

    data = {
        "grant_type": "client_credentials",
        "client_id": auth.client_id,
        "client_secret": auth.client_secret,
    }
    if auth.scope:
        data["scope"] = auth.scope

    res = httpx.post(auth.token_url, data=data, timeout=15)
    res.raise_for_status()
    return res.json()["access_token"]


def resolve_auth(auth: AuthConfig) -> AuthConfig:
    """Resolve auth config, performing any necessary token exchanges.

    For OAuth2 client credentials, fetches the token and converts to bearer.
    For cookie login, performs login and stores cookies.
    """
    if auth.type == "oauth2_client":
        token = _obtain_oauth2_token(auth)
        return AuthConfig(type="bearer", token=token)

    if auth.type == "cookie" and not auth.cookies and auth.login_url:
        cookies = _perform_login(auth)
        return AuthConfig(type="cookie", cookies=cookies)

    return auth


def apply_auth_to_client(client: httpx.Client, auth: AuthConfig) -> None:
    """Apply auth config to an httpx Client."""
    resolved = resolve_auth(auth)
    client.headers.update(build_auth_headers(resolved))
    client.params = {**dict(client.params), **build_auth_params(resolved)}
    for k, v in build_auth_cookies(resolved).items():
        client.cookies.set(k, v)


def get_authenticated_client(auth: AuthConfig | None) -> httpx.Client:
    """Create an httpx Client with auth applied."""
    client = httpx.Client(follow_redirects=True, timeout=30)
    if auth:
        apply_auth_to_client(client, auth)
    return client
