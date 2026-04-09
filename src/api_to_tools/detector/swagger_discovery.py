"""Authenticated Swagger/OpenAPI auto-discovery.

Discovers hidden Swagger/OpenAPI specs on sites that require authentication.
Many Spring Boot / Java services expose Swagger only to authenticated users.

Strategy:
1. Login via the frontend to get JWT/session tokens
2. Guess backend domain (api.example.com from admin.example.com)
3. Extract API path prefixes from JS bundles (/api/bo/, /api/v1/, etc.)
4. Try all swagger path + prefix combinations with Bearer/Cookie auth
5. Return the spec URL if found
"""

from __future__ import annotations

import json
import re
from urllib.parse import urlparse

import httpx

from api_to_tools.types import AuthConfig, DetectionResult

# Swagger/OpenAPI well-known paths to append AFTER the API prefix
SWAGGER_SUFFIXES = [
    "/api-docs",
    "/api-docs/swagger-config",
    "/v3/api-docs",
    "/v2/api-docs",
    "/swagger.json",
    "/openapi.json",
    "/swagger-resources",
    "/swagger-ui/index.html",
    "/doc.html",
]

# Common login API patterns
LOGIN_PATTERNS = [
    "/login", "/auth/login", "/v1/login", "/v2/login",
    "/api/login", "/api/auth/login", "/api/v1/auth/login",
]


def _guess_backend_domains(frontend_url: str) -> list[str]:
    """Guess possible backend API domains from frontend URL.

    admin.example.com → [api.example.com, api.example.com, bo-api.example.com]
    app.example.com → [api.example.com, api-app.example.com, backend.example.com]
    admin.example.com → [api-admin.example.com, api.example.com]
    """
    parsed = urlparse(frontend_url)
    host = parsed.hostname or ""
    parts = host.split(".")

    if len(parts) < 2:
        return []

    subdomain = parts[0]
    base_domain = ".".join(parts[1:])
    scheme = parsed.scheme

    guesses = [
        f"{scheme}://api-{subdomain}.{base_domain}",  # api.example.com
        f"{scheme}://api.{base_domain}",               # api.example.com
        f"{scheme}://{subdomain}-api.{base_domain}",   # bo-api.example.com
        f"{scheme}://backend.{base_domain}",           # backend.example.com
        f"{scheme}://server.{base_domain}",            # server.example.com
        f"{scheme}://{host}",                          # same domain (proxy)
    ]

    return list(dict.fromkeys(guesses))  # dedupe preserving order


def _extract_api_prefixes_from_text(text: str) -> set[str]:
    """Extract API path prefixes from text content."""
    prefixes = set()
    for m in re.finditer(r'["\']/(api/[^"\'`\s/]+(?:/[^"\'`\s/]+)?)/[^"\'`\s]*["\']', text):
        prefix = "/" + m.group(1)
        prefixes.add(prefix)
    for m in re.finditer(r'/(api(?:/\w+){0,2})/', text):
        prefix = "/" + m.group(1)
        if len(prefix) > 4:
            prefixes.add(prefix)
    return prefixes


def _extract_api_prefixes(client: httpx.Client, url: str) -> list[str]:
    """Extract API path prefixes from HTML page + its JS bundles.

    Scans the HTML page and downloads a sample of JS bundles
    to find patterns like /api/bo/v1/..., /api/v2/..., etc.
    """
    prefixes = set()
    try:
        res = client.get(url, follow_redirects=True, timeout=10)
        html = res.text
        prefixes.update(_extract_api_prefixes_from_text(html))

        # If HTML didn't have enough, scan JS bundles
        if len(prefixes) < 2:
            js_urls = re.findall(r'src="([^"]*\.js)"', html)
            parsed = urlparse(url)
            base = f"{parsed.scheme}://{parsed.netloc}"
            for js_url in js_urls[:15]:  # scan up to 15 bundles
                full = f"{base}{js_url}" if js_url.startswith("/") else js_url
                try:
                    jr = client.get(full, timeout=8)
                    prefixes.update(_extract_api_prefixes_from_text(jr.text))
                except Exception:
                    continue
    except Exception:
        pass

    if not prefixes:
        prefixes = {"/api"}

    # Also add version-stripped prefixes: /api/bo/v1 → /api/bo
    extra = set()
    for p in prefixes:
        stripped = re.sub(r'/v\d+$', '', p)
        if stripped and stripped != p:
            extra.add(stripped)
    prefixes.update(extra)

    return sorted(prefixes, key=len, reverse=True)


def _try_login(client: httpx.Client, frontend_url: str, auth: AuthConfig) -> str | None:
    """Try to login via common API endpoints and return access token."""
    parsed = urlparse(frontend_url)
    base = f"{parsed.scheme}://{parsed.netloc}"

    # Try common login endpoints
    login_payloads = [
        {"loginId": auth.username, "password": auth.password},
        {"username": auth.username, "password": auth.password},
        {"id": auth.username, "password": auth.password},
        {"email": auth.username, "password": auth.password},
    ]

    prefixes = _extract_api_prefixes(client, frontend_url)

    # Build candidate login URLs
    login_urls = []
    for prefix in prefixes:
        for pattern in LOGIN_PATTERNS:
            login_urls.append(f"{base}{prefix}{pattern}")
    # Also add generic patterns
    for pattern in LOGIN_PATTERNS:
        login_urls.append(f"{base}{pattern}")

    login_urls = list(dict.fromkeys(login_urls))  # dedupe

    for url in login_urls:
        for payload in login_payloads:
            try:
                # Try with and without trailing slash
                for u in [url, url.rstrip("/") + "/"]:
                    res = client.post(u, json=payload, timeout=10)
                    if res.status_code == 200:
                        body = res.json()
                        # Look for token in response (various structures)
                        token = _extract_token(body)
                        if token:
                            return token
            except Exception:
                continue

    return None


def _extract_token(body) -> str | None:
    """Recursively find an access token in a JSON response."""
    if isinstance(body, str):
        return body if body.startswith("eyJ") else None
    if isinstance(body, dict):
        # Direct keys
        for key in ("accessToken", "access_token", "token", "jwt", "id_token", "data"):
            if key in body:
                val = body[key]
                if isinstance(val, str) and val.startswith("eyJ"):
                    return val
                if isinstance(val, dict):
                    result = _extract_token(val)
                    if result:
                        return result
        # Nested payload/data/result
        for key in ("payload", "data", "result", "body", "response"):
            if key in body and isinstance(body[key], dict):
                result = _extract_token(body[key])
                if result:
                    return result
    return None


def _probe_swagger(
    client: httpx.Client,
    domain: str,
    prefixes: list[str],
    token: str | None,
    timeout: float,
) -> DetectionResult | None:
    """Try all swagger path combinations on a domain."""
    headers = {}
    if token:
        headers["Authorization"] = f"Bearer {token}"

    # Try each prefix + swagger suffix combination
    urls_to_try = []
    for prefix in prefixes:
        for suffix in SWAGGER_SUFFIXES:
            urls_to_try.append(f"{domain}{prefix}{suffix}")

    # Also try root-level swagger paths
    for suffix in SWAGGER_SUFFIXES:
        urls_to_try.append(f"{domain}{suffix}")

    urls_to_try = list(dict.fromkeys(urls_to_try))

    for url in urls_to_try:
        # Try with and without trailing slash
        for u in [url, url.rstrip("/") + "/"]:
            try:
                res = client.get(u, headers=headers, timeout=timeout, follow_redirects=True)
                if res.status_code != 200:
                    continue
                ct = res.headers.get("content-type", "")
                if "json" not in ct and "yaml" not in ct:
                    continue
                try:
                    data = res.json()
                except Exception:
                    continue
                # Check if it's an OpenAPI/Swagger spec
                if isinstance(data, dict) and ("openapi" in data or "swagger" in data or "paths" in data):
                    return DetectionResult(
                        type="openapi",
                        spec_url=u,
                        raw_content=res.text,
                        content_type=ct,
                    )
                # Check if it's swagger-config (has urls list pointing to specs)
                if isinstance(data, dict) and "urls" in data:
                    for spec_ref in data["urls"]:
                        spec_url = spec_ref.get("url", "")
                        if spec_url:
                            if not spec_url.startswith("http"):
                                spec_url = f"{domain}{spec_url}"
                            return _probe_swagger_url(client, spec_url, headers, timeout)
            except (httpx.HTTPError, httpx.InvalidURL):
                continue

    return None


def _probe_swagger_url(client, url, headers, timeout) -> DetectionResult | None:
    """Probe a single known swagger URL."""
    try:
        res = client.get(url, headers=headers, timeout=timeout, follow_redirects=True)
        if res.status_code == 200:
            data = res.json()
            if isinstance(data, dict) and ("openapi" in data or "swagger" in data or "paths" in data):
                return DetectionResult(type="openapi", spec_url=url, raw_content=res.text)
    except Exception:
        pass
    return None


def discover_swagger_with_auth(
    url: str,
    auth: AuthConfig,
    *,
    timeout: float = 15.0,
) -> DetectionResult | None:
    """Attempt to discover Swagger/OpenAPI spec using authenticated access.

    1. Login via frontend API to get JWT token
    2. Guess backend domains
    3. Try all swagger paths with Bearer auth
    """
    with httpx.Client(follow_redirects=True, verify=False, timeout=timeout) as client:
        # 1. Login to get token
        token = _try_login(client, url, auth)

        # Also try with cookies from the login response
        if auth.cookies:
            for k, v in auth.cookies.items():
                client.cookies.set(k, v)

        # 2. Extract API prefixes from frontend
        prefixes = _extract_api_prefixes(client, url)

        # 3. Guess backend domains
        domains = _guess_backend_domains(url)

        # 4. Try swagger on each domain
        for domain in domains:
            result = _probe_swagger(client, domain, prefixes, token, timeout)
            if result:
                return result

    return None
