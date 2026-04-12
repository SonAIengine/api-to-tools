"""Authentication utilities."""

from __future__ import annotations

import json
import re
import time
from urllib.parse import urlparse

import httpx

from api_to_tools._logging import get_logger
from api_to_tools.constants import DEFAULT_AUTH_TIMEOUT, DEFAULT_EXECUTOR_TIMEOUT, DEFAULT_HTTP_TIMEOUT
from api_to_tools.types import AuthConfig

log = get_logger("auth")


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

    with httpx.Client(follow_redirects=True, verify=auth.verify_ssl) as client:
        # First GET the login page (to pick up CSRF tokens, etc.)
        login_page = client.get(auth.login_url, timeout=DEFAULT_AUTH_TIMEOUT)
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
            timeout=DEFAULT_AUTH_TIMEOUT,
        )

        # Merge all cookies from the session
        all_cookies = dict(login_page.cookies)
        all_cookies.update(dict(res.cookies))
        return all_cookies


def _obtain_oauth2_token(auth: AuthConfig) -> dict:
    """Obtain OAuth2 token via client credentials or refresh_token flow.

    Returns dict with keys: access_token, expires_in (optional), refresh_token (optional).
    """
    if not auth.token_url:
        raise ValueError("OAuth2 requires token_url")

    if auth.refresh_token:
        data = {
            "grant_type": "refresh_token",
            "refresh_token": auth.refresh_token,
        }
        if auth.client_id:
            data["client_id"] = auth.client_id
        if auth.client_secret:
            data["client_secret"] = auth.client_secret
    else:
        if not auth.client_id or not auth.client_secret:
            raise ValueError("OAuth2 requires client_id and client_secret (or refresh_token)")
        data = {
            "grant_type": "client_credentials",
            "client_id": auth.client_id,
            "client_secret": auth.client_secret,
        }

    if auth.scope:
        data["scope"] = auth.scope

    res = httpx.post(auth.token_url, data=data, timeout=DEFAULT_AUTH_TIMEOUT, verify=auth.verify_ssl)
    res.raise_for_status()
    body = res.json()
    return {
        "access_token": body["access_token"],
        "expires_in": body.get("expires_in"),
        "refresh_token": body.get("refresh_token", auth.refresh_token),
    }


# ──────────────────────────────────────────────
# Token Manager — automatic renewal
# ──────────────────────────────────────────────

# Renew token this many seconds before actual expiry
_EXPIRY_BUFFER_SECONDS = 30


class TokenManager:
    """Manages OAuth2 token lifecycle with automatic renewal.

    Usage:
        mgr = TokenManager(auth_config)
        token = mgr.get_token()      # fetches or returns cached
        token = mgr.get_token()      # returns cached if still valid
        token = mgr.refresh()        # force refresh
    """

    def __init__(self, auth: AuthConfig):
        self._auth = auth
        self._access_token: str | None = None
        self._refresh_token: str | None = auth.refresh_token
        self._expires_at: float | None = None

    @property
    def is_expired(self) -> bool:
        if self._expires_at is None:
            return self._access_token is None
        return time.monotonic() >= (self._expires_at - _EXPIRY_BUFFER_SECONDS)

    def get_token(self) -> str:
        """Get a valid access token, refreshing if expired."""
        if self._access_token and not self.is_expired:
            return self._access_token
        return self.refresh()

    def refresh(self) -> str:
        """Force token refresh."""
        auth = self._auth
        if self._refresh_token:
            auth = AuthConfig(
                type=auth.type,
                token_url=auth.token_url,
                client_id=auth.client_id,
                client_secret=auth.client_secret,
                scope=auth.scope,
                refresh_token=self._refresh_token,
                verify_ssl=auth.verify_ssl,
            )

        result = _obtain_oauth2_token(auth)
        self._access_token = result["access_token"]
        if result.get("refresh_token"):
            self._refresh_token = result["refresh_token"]
        if result.get("expires_in"):
            self._expires_at = time.monotonic() + result["expires_in"]
        else:
            self._expires_at = None

        log.info("Token refreshed (expires_in=%s)", result.get("expires_in"))
        return self._access_token

    def get_auth_header(self) -> dict[str, str]:
        """Get Authorization header with a valid token."""
        return {"Authorization": f"Bearer {self.get_token()}"}


# Module-level cache: auth config content hash → TokenManager
_token_managers: dict[str, TokenManager] = {}


def _auth_cache_key(auth: AuthConfig) -> str:
    """Value-based cache key so identical credentials share one TokenManager."""
    parts = (auth.type, auth.token_url, auth.client_id, auth.client_secret,
             auth.scope, auth.refresh_token, auth.username, auth.password)
    return "|".join(str(p) for p in parts)


def get_token_manager(auth: AuthConfig) -> TokenManager:
    """Get or create a TokenManager for the given auth config."""
    key = _auth_cache_key(auth)
    if key not in _token_managers:
        _token_managers[key] = TokenManager(auth)
    return _token_managers[key]


def resolve_auth(auth: AuthConfig) -> AuthConfig:
    """Resolve auth config, performing any necessary token exchanges.

    For OAuth2 client credentials, fetches the token and converts to bearer.
    For cookie login, performs login and stores cookies.
    """
    if auth.type == "oauth2_client":
        mgr = get_token_manager(auth)
        token = mgr.get_token()
        return AuthConfig(type="bearer", token=token, verify_ssl=auth.verify_ssl)

    if auth.type == "cookie" and not auth.cookies and auth.login_url:
        cookies = _perform_login(auth)
        return AuthConfig(type="cookie", cookies=cookies, verify_ssl=auth.verify_ssl)

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
    verify = auth.verify_ssl if auth else True
    client = httpx.Client(follow_redirects=True, timeout=DEFAULT_EXECUTOR_TIMEOUT, verify=verify)
    if auth:
        apply_auth_to_client(client, auth)
    return client


# ──────────────────────────────────────────────
# Generic API login (shared by detector & parsers)
# ──────────────────────────────────────────────

LOGIN_PATTERNS = [
    "/login",
    "/auth/login",
    "/signin",
    "/auth/signin",
    "/v1/login",
    "/v2/login",
    "/api/login",
    "/api/auth/login",
    "/api/v1/auth/login",
    "/api/v2/auth/login",
    "/api/v1/login",
    "/api/v2/login",
    "/user/login",
    "/users/login",
]


def extract_csrf_token(html: str) -> tuple[str | None, str | None]:
    """Find a CSRF token in HTML meta or hidden input. Returns (name, value)."""
    m = re.search(
        r'<meta[^>]+name=["\']([^"\']*csrf[^"\']*)["\'][^>]+content=["\']([^"\']+)["\']',
        html, re.I,
    )
    if m:
        return m.group(1), m.group(2)
    m = re.search(
        r'<input[^>]+name=["\']([^"\']*(?:csrf|_token|xsrf)[^"\']*)["\'][^>]+value=["\']([^"\']+)["\']',
        html, re.I,
    )
    if m:
        return m.group(1), m.group(2)
    return None, None


def extract_token(body) -> str | None:
    """Recursively locate an access token inside a JSON response."""
    if isinstance(body, str):
        return body if body.startswith("eyJ") else None
    if isinstance(body, dict):
        for key in (
            "accessToken", "access_token", "token", "jwt", "id_token",
            "idToken", "authToken", "bearerToken",
        ):
            if key in body:
                val = body[key]
                if isinstance(val, str) and val.startswith("eyJ"):
                    return val
                if isinstance(val, dict):
                    result = extract_token(val)
                    if result:
                        return result
        for key in ("payload", "data", "result", "body", "response"):
            if key in body and isinstance(body[key], dict):
                result = extract_token(body[key])
                if result:
                    return result
    return None


def try_api_login(
    client: httpx.Client,
    frontend_url: str,
    auth: AuthConfig,
    *,
    prefixes: list[str] | None = None,
) -> str | None:
    """Attempt login via common API endpoints and return an access token.

    Args:
        client: httpx Client (cookies will be populated on success).
        frontend_url: The frontend URL to derive login endpoints from.
        auth: AuthConfig with username/password.
        prefixes: Optional API path prefixes (e.g. ["/api/bo", "/api"]).
            If None, only root-level login patterns are tried.
    """
    parsed = urlparse(frontend_url)
    base = f"{parsed.scheme}://{parsed.netloc}"

    login_payloads = [
        {"loginId": auth.username, "password": auth.password},
        {"username": auth.username, "password": auth.password},
        {"id": auth.username, "password": auth.password},
        {"email": auth.username, "password": auth.password},
        {"userId": auth.username, "password": auth.password},
        {"user": auth.username, "pass": auth.password},
    ]

    login_urls: list[str] = []
    for prefix in (prefixes or []):
        for pattern in LOGIN_PATTERNS:
            login_urls.append(f"{base}{prefix}{pattern}")
    for pattern in LOGIN_PATTERNS:
        login_urls.append(f"{base}{pattern}")
    login_urls = list(dict.fromkeys(login_urls))

    csrf_name, csrf_value = None, None
    try:
        html = client.get(frontend_url, timeout=DEFAULT_HTTP_TIMEOUT).text
        csrf_name, csrf_value = extract_csrf_token(html)
    except httpx.HTTPError:
        pass

    for url in login_urls:
        for payload in login_payloads:
            if csrf_name and csrf_value:
                payload_with_csrf = {**payload, csrf_name: csrf_value}
            else:
                payload_with_csrf = payload

            for u in [url, url.rstrip("/") + "/"]:
                # JSON
                try:
                    headers = {}
                    if csrf_name and csrf_value:
                        headers[f"X-{csrf_name.upper()}"] = csrf_value
                    res = client.post(u, json=payload_with_csrf, headers=headers, timeout=DEFAULT_AUTH_TIMEOUT)
                    if res.status_code == 200:
                        try:
                            body = res.json()
                        except (json.JSONDecodeError, ValueError):
                            continue
                        token = extract_token(body)
                        if token:
                            log.info("Login succeeded at %s", u)
                            return token
                except httpx.HTTPError:
                    continue

                # Form-encoded
                try:
                    res = client.post(u, data=payload_with_csrf, timeout=DEFAULT_AUTH_TIMEOUT)
                    if res.status_code == 200:
                        try:
                            body = res.json()
                        except (json.JSONDecodeError, ValueError):
                            continue
                        token = extract_token(body)
                        if token:
                            log.info("Login succeeded at %s (form)", u)
                            return token
                except httpx.HTTPError:
                    continue

    return None
