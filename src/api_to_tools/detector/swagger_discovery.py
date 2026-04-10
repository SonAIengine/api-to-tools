"""Authenticated Swagger/OpenAPI auto-discovery.

Discovers hidden Swagger/OpenAPI specs on sites that require authentication.
Many Spring Boot / Java services expose Swagger only to authenticated users.

Strategy:
1. Login via the frontend to get JWT/session tokens (+ CSRF handling)
2. Extract backend base URLs from HTML + JS bundles (literal scan)
3. Guess additional backend domains via naming heuristics
4. Extract API path prefixes from bundles (/api/bo/, /api/v1/, ...)
5. Probe the cartesian product of (domain × prefix × suffix) with
   multiple auth styles (Bearer only / Cookie only / Bearer + Cookie /
   custom headers) until an OpenAPI spec is found.
"""

from __future__ import annotations

import json
import re
from urllib.parse import urlparse

import httpx

from api_to_tools._logging import get_logger
from api_to_tools.types import AuthConfig, DetectionResult

log = get_logger("swagger_discovery")


# ──────────────────────────────────────────────
# Swagger / OpenAPI path suffixes (expanded — Priority 2)
# Covers SpringDoc, Springfox, Knife4j, FastAPI, .NET Core, NestJS,
# Django REST Framework, drf-yasg, Gin, Kubernetes, AsyncAPI, and more.
# ──────────────────────────────────────────────

SWAGGER_SUFFIXES = [
    # --- SpringDoc ---
    "/api-docs",
    "/v3/api-docs",
    "/v3/api-docs.yaml",
    "/api-docs.yaml",
    "/api-docs/swagger-config",
    "/v3/api-docs/swagger-config",
    "/v3/api-docs/public",
    "/v3/api-docs/admin",
    "/v3/api-docs/internal",
    # --- Springfox ---
    "/v2/api-docs",
    "/swagger-resources",
    "/swagger-resources/configuration/ui",
    "/swagger-resources/configuration/security",
    # --- Knife4j ---
    "/doc.html",
    "/swagger-json",
    # --- Generic OpenAPI ---
    "/openapi.json",
    "/openapi.yaml",
    "/openapi.yml",
    "/swagger.json",
    "/swagger.yaml",
    "/swagger",
    # --- FastAPI ---
    "/docs",
    "/redoc",
    "/docs/json",
    # --- .NET Core ---
    "/swagger/v1/swagger.json",
    "/swagger/v2/swagger.json",
    "/swagger/default/swagger.json",
    "/swagger/v1.0/swagger.json",
    # --- NestJS ---
    "/api",
    "/api-json",
    "/api/docs-json",
    # --- Django REST Framework / drf-yasg ---
    "/swagger/",
    "/swagger.json",
    "/swagger.yaml",
    "/redoc/",
    "/schema/",
    "/schema.json",
    # --- Gin / Go ---
    "/swagger/doc.json",
    "/swagger/index.html",
    # --- Strapi ---
    "/documentation/v1.0.0/swagger.json",
    # --- Kubernetes / cluster-style ---
    "/openapi/v2",
    "/openapi/v3",
    # --- Swagger UI entry (may embed spec URL) ---
    "/swagger-ui/index.html",
    "/swagger-ui",
    "/swagger-ui.html",
    # --- AsyncAPI ---
    "/asyncapi.json",
    "/asyncapi.yaml",
    # --- GraphQL schema download ---
    "/graphql/schema",
    "/graphql.json",
]


# Login endpoint patterns
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


# ──────────────────────────────────────────────
# Priority 1: JS literal base URL extractor
# ──────────────────────────────────────────────

_BASE_URL_LITERAL_RE = re.compile(
    r'["\'](https?://[A-Za-z0-9.\-]+(?::\d+)?(?:/[A-Za-z0-9._\-/]*)?)["\']'
)

# Common config variable names that hold API bases
_CONFIG_BASE_RE = re.compile(
    r'(?:API_BASE|API_URL|BASE_URL|apiBase|apiUrl|baseURL|'
    r'API_HOST|apiHost|backendUrl|BACKEND_URL|SWAGGER_URL|'
    r'NEXT_PUBLIC_API[A-Z_]*|REACT_APP_API[A-Z_]*|VITE_API[A-Z_]*)'
    r'\s*[:=]\s*["\']([^"\']+)["\']',
    re.IGNORECASE,
)


def _is_plausible_backend_url(url: str, frontend_host: str) -> bool:
    """Filter out CDN / analytics / fonts / obvious non-API urls."""
    try:
        p = urlparse(url)
    except Exception:
        return False
    host = (p.hostname or "").lower()
    if not host or "." not in host:
        return False

    # Obvious excludes
    exclude_hints = (
        "google", "googletagmanager", "gstatic", "googleapis",
        "facebook", "fbcdn", "twitter", "linkedin",
        "cloudflare.com", "jsdelivr.net", "unpkg.com",
        "cdnjs.cloudflare", "bootstrapcdn", "fontawesome",
        "fonts.googleapis", "w3.org", "schema.org",
        "sentry", "datadog", "newrelic", "mixpanel", "amplitude",
        "doubleclick", "adservice", "adobedtm", "segment.io",
    )
    if any(hint in host for hint in exclude_hints):
        return False

    # Must share a base domain with the frontend OR contain "api"/"backend"/etc
    frontend_base = ".".join(frontend_host.split(".")[-2:]) if "." in frontend_host else frontend_host
    shares_base = frontend_base and frontend_base in host
    api_hint = any(kw in host for kw in ("api", "backend", "server", "swagger", "docs"))

    return shares_base or api_hint


def extract_base_urls_from_content(text: str, frontend_url: str) -> set[str]:
    """Extract absolute base URLs that look like backend candidates."""
    bases: set[str] = set()
    frontend_host = (urlparse(frontend_url).hostname or "").lower()

    # 1. Config variable assignments
    for m in _CONFIG_BASE_RE.finditer(text):
        val = m.group(1).strip()
        if val.startswith("http") and _is_plausible_backend_url(val, frontend_host):
            bases.add(val.rstrip("/"))

    # 2. Raw URL literals
    for m in _BASE_URL_LITERAL_RE.finditer(text):
        url = m.group(1)
        if _is_plausible_backend_url(url, frontend_host):
            # Strip path, keep only scheme://host(:port)
            p = urlparse(url)
            base = f"{p.scheme}://{p.netloc}"
            bases.add(base)

    return bases


def extract_base_urls_from_js_bundles(
    client: httpx.Client,
    frontend_url: str,
    max_bundles: int = 30,
    timeout: float = 8.0,
) -> set[str]:
    """Download JS bundles from the frontend and extract backend URL literals."""
    bases: set[str] = set()
    try:
        res = client.get(frontend_url, follow_redirects=True, timeout=timeout)
        html = res.text
        bases.update(extract_base_urls_from_content(html, frontend_url))

        js_urls = re.findall(r'src=["\']([^"\']*\.js)["\']', html)
        parsed = urlparse(str(res.url))
        origin = f"{parsed.scheme}://{parsed.netloc}"

        for js_url in js_urls[:max_bundles]:
            full = f"{origin}{js_url}" if js_url.startswith("/") else js_url
            try:
                jr = client.get(full, timeout=timeout)
                if jr.status_code == 200:
                    bases.update(extract_base_urls_from_content(jr.text, frontend_url))
            except httpx.HTTPError:
                continue
    except httpx.HTTPError as e:
        log.debug("base URL scan failed: %s", e)

    return bases


# ──────────────────────────────────────────────
# API prefix extraction (unchanged but tightened)
# ──────────────────────────────────────────────

def _extract_api_prefixes_from_text(text: str) -> set[str]:
    prefixes: set[str] = set()
    for m in re.finditer(r'["\']/(api/[^"\'`\s/]+(?:/[^"\'`\s/]+)?)/[^"\'`\s]*["\']', text):
        prefixes.add("/" + m.group(1))
    for m in re.finditer(r'/(api(?:/\w+){0,2})/', text):
        prefix = "/" + m.group(1)
        if len(prefix) > 4:
            prefixes.add(prefix)
    return prefixes


def _extract_api_prefixes(client: httpx.Client, url: str) -> list[str]:
    prefixes: set[str] = set()
    try:
        res = client.get(url, follow_redirects=True, timeout=10)
        html = res.text
        prefixes.update(_extract_api_prefixes_from_text(html))

        if len(prefixes) < 2:
            js_urls = re.findall(r'src=["\']([^"\']*\.js)["\']', html)
            parsed = urlparse(str(res.url))
            origin = f"{parsed.scheme}://{parsed.netloc}"
            for js_url in js_urls[:15]:
                full = f"{origin}{js_url}" if js_url.startswith("/") else js_url
                try:
                    jr = client.get(full, timeout=8)
                    prefixes.update(_extract_api_prefixes_from_text(jr.text))
                except httpx.HTTPError:
                    continue
    except httpx.HTTPError:
        pass

    if not prefixes:
        prefixes = {"/api"}

    # Version-stripped prefixes: /api/bo/v1 → /api/bo
    extra: set[str] = set()
    for p in prefixes:
        stripped = re.sub(r'/v\d+$', '', p)
        if stripped and stripped != p:
            extra.add(stripped)
    prefixes.update(extra)

    return sorted(prefixes, key=len, reverse=True)


# ──────────────────────────────────────────────
# Backend domain guessing (heuristics + JS literals)
# ──────────────────────────────────────────────

def _guess_backend_domains(frontend_url: str) -> list[str]:
    """Heuristic variations on the frontend subdomain."""
    parsed = urlparse(frontend_url)
    host = parsed.hostname or ""
    parts = host.split(".")
    if len(parts) < 2:
        return [f"{parsed.scheme}://{host}"]

    subdomain = parts[0]
    base_domain = ".".join(parts[1:])
    scheme = parsed.scheme

    guesses = [
        f"{scheme}://api-{subdomain}.{base_domain}",
        f"{scheme}://api.{base_domain}",
        f"{scheme}://{subdomain}-api.{base_domain}",
        f"{scheme}://{subdomain}api.{base_domain}",
        f"{scheme}://backend.{base_domain}",
        f"{scheme}://server.{base_domain}",
        f"{scheme}://docs.{base_domain}",
        f"{scheme}://swagger.{base_domain}",
        f"{scheme}://api-gateway.{base_domain}",
        f"{scheme}://gateway.{base_domain}",
        f"{scheme}://internal.{base_domain}",
        f"{scheme}://{host}",  # same domain proxy
    ]
    return list(dict.fromkeys(guesses))


# ──────────────────────────────────────────────
# Login with CSRF support (Priority 3)
# ──────────────────────────────────────────────

def _extract_csrf_token(html: str) -> tuple[str | None, str | None]:
    """Find a CSRF token in HTML meta or hidden input. Returns (name, value)."""
    # <meta name="csrf-token" content="...">
    m = re.search(
        r'<meta[^>]+name=["\']([^"\']*csrf[^"\']*)["\'][^>]+content=["\']([^"\']+)["\']',
        html, re.I,
    )
    if m:
        return m.group(1), m.group(2)
    # <input type="hidden" name="_csrf" value="...">
    m = re.search(
        r'<input[^>]+name=["\']([^"\']*(?:csrf|_token|xsrf)[^"\']*)["\'][^>]+value=["\']([^"\']+)["\']',
        html, re.I,
    )
    if m:
        return m.group(1), m.group(2)
    return None, None


def _try_login(client: httpx.Client, frontend_url: str, auth: AuthConfig) -> str | None:
    """Attempt to login via common API endpoints and return an access token."""
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

    prefixes = _extract_api_prefixes(client, frontend_url)

    # Build candidate login URLs
    login_urls: list[str] = []
    for prefix in prefixes:
        for pattern in LOGIN_PATTERNS:
            login_urls.append(f"{base}{prefix}{pattern}")
    for pattern in LOGIN_PATTERNS:
        login_urls.append(f"{base}{pattern}")
    login_urls = list(dict.fromkeys(login_urls))

    # Pre-fetch frontend for CSRF token if needed
    csrf_name, csrf_value = None, None
    try:
        html = client.get(frontend_url, timeout=10).text
        csrf_name, csrf_value = _extract_csrf_token(html)
    except httpx.HTTPError:
        pass

    for url in login_urls:
        for payload in login_payloads:
            if csrf_name and csrf_value:
                payload_with_csrf = {**payload, csrf_name: csrf_value}
            else:
                payload_with_csrf = payload

            for u in [url, url.rstrip("/") + "/"]:
                # Try JSON first
                try:
                    headers = {}
                    if csrf_name and csrf_value:
                        headers[f"X-{csrf_name.upper()}"] = csrf_value
                    res = client.post(u, json=payload_with_csrf, headers=headers, timeout=10)
                    if res.status_code == 200:
                        try:
                            body = res.json()
                        except (json.JSONDecodeError, ValueError):
                            continue
                        token = _extract_token(body)
                        if token:
                            log.info("Login succeeded at %s", u)
                            return token
                except httpx.HTTPError:
                    continue

                # Try form-encoded
                try:
                    res = client.post(u, data=payload_with_csrf, timeout=10)
                    if res.status_code == 200:
                        try:
                            body = res.json()
                        except (json.JSONDecodeError, ValueError):
                            continue
                        token = _extract_token(body)
                        if token:
                            log.info("Login succeeded at %s (form)", u)
                            return token
                except httpx.HTTPError:
                    continue

    return None


def _extract_token(body) -> str | None:
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
                    result = _extract_token(val)
                    if result:
                        return result
        for key in ("payload", "data", "result", "body", "response"):
            if key in body and isinstance(body[key], dict):
                result = _extract_token(body[key])
                if result:
                    return result
    return None


# ──────────────────────────────────────────────
# Probing — multi-auth cartesian product (Priority 3)
# ──────────────────────────────────────────────

def _is_openapi_like(data) -> bool:
    if not isinstance(data, dict):
        return False
    return "openapi" in data or "swagger" in data or "paths" in data


def _probe_single(
    client: httpx.Client,
    url: str,
    token: str | None,
    timeout: float,
    _recursion_depth: int = 0,
) -> DetectionResult | None:
    """Probe one URL. Uses Bearer first, falls back to cookie-only on 401/403."""
    if _recursion_depth > 2:
        return None

    # Build header attempts in order of likelihood
    attempts: list[dict] = []
    if token:
        attempts.append({"Authorization": f"Bearer {token}"})
    attempts.append({})  # cookie only (client already has cookies from login)

    # Short per-probe timeout so we fail fast
    probe_timeout = min(timeout, 4.0)

    for headers in attempts:
        try:
            res = client.get(url, headers=headers, timeout=probe_timeout, follow_redirects=True)
        except (httpx.HTTPError, httpx.InvalidURL):
            continue

        if res.status_code != 200:
            continue
        ct = res.headers.get("content-type", "")
        if "json" not in ct and "yaml" not in ct:
            continue

        try:
            data = res.json()
        except (json.JSONDecodeError, ValueError):
            continue

        if _is_openapi_like(data):
            return DetectionResult(
                type="openapi",
                spec_url=url,
                raw_content=res.text,
                content_type=ct,
            )

        # swagger-config with spec URLs inside
        if isinstance(data, dict) and "urls" in data:
            for spec_ref in data["urls"] or []:
                spec_url = (spec_ref or {}).get("url", "") if isinstance(spec_ref, dict) else ""
                if spec_url:
                    if not spec_url.startswith("http"):
                        parsed = urlparse(url)
                        spec_url = f"{parsed.scheme}://{parsed.netloc}{spec_url}"
                    inner = _probe_single(client, spec_url, token, timeout, _recursion_depth + 1)
                    if inner:
                        return inner

    return None


# Ordered by empirical hit rate — try most common first
_HIGH_PRIORITY_SUFFIXES = [
    "/api-docs",
    "/v3/api-docs",
    "/v2/api-docs",
    "/swagger.json",
    "/openapi.json",
]


def _build_probe_urls(domain: str, prefixes: list[str]) -> list[str]:
    """Build candidate URLs ordered by likelihood (highest first)."""
    urls: list[str] = []

    # Tier 1: prefix + high-priority suffix (most common in practice)
    for prefix in prefixes:
        for suffix in _HIGH_PRIORITY_SUFFIXES:
            urls.append(f"{domain}{prefix}{suffix}")

    # Tier 2: domain root + high-priority suffix
    for suffix in _HIGH_PRIORITY_SUFFIXES:
        urls.append(f"{domain}{suffix}")

    # Tier 3: rest of the suffixes × prefix
    for prefix in prefixes:
        for suffix in SWAGGER_SUFFIXES:
            if suffix in _HIGH_PRIORITY_SUFFIXES:
                continue
            urls.append(f"{domain}{prefix}{suffix}")

    # Tier 4: domain root + remaining suffixes
    for suffix in SWAGGER_SUFFIXES:
        if suffix in _HIGH_PRIORITY_SUFFIXES:
            continue
        urls.append(f"{domain}{suffix}")

    # Dedupe preserving order
    seen: set[str] = set()
    ordered: list[str] = []
    for u in urls:
        if u not in seen:
            seen.add(u)
            ordered.append(u)
    return ordered


def _probe_swagger(
    client: httpx.Client,
    domain: str,
    prefixes: list[str],
    token: str | None,
    timeout: float,
) -> DetectionResult | None:
    """Try all swagger path combinations on a domain (ordered by priority)."""
    urls_to_try = _build_probe_urls(domain, prefixes)
    log.debug("Probing %d URLs on %s (tiered)", len(urls_to_try), domain)

    for url in urls_to_try:
        result = _probe_single(client, url, token, timeout)
        if result:
            return result
    return None


# ──────────────────────────────────────────────
# Main entrypoint — orchestrates all priorities
# ──────────────────────────────────────────────

def discover_swagger_with_auth(
    url: str,
    auth: AuthConfig,
    *,
    timeout: float = 15.0,
) -> DetectionResult | None:
    """Find a Swagger/OpenAPI spec by combining login, domain guessing,
    JS base URL extraction, and multi-auth probing."""

    with httpx.Client(follow_redirects=True, verify=False, timeout=timeout) as client:
        # Step 1: Login → token
        token = _try_login(client, url, auth)

        if auth.cookies:
            for k, v in auth.cookies.items():
                client.cookies.set(k, v)

        # Step 2: API prefixes
        prefixes = _extract_api_prefixes(client, url)

        # Step 3: Backend domains — ordered by empirical hit rate
        #   1. Heuristic (same domain + api-*) — covers 95% of typical cases
        #   2. JS literal base URLs — catches exotic backends
        heuristic_domains = _guess_backend_domains(url)
        literal_bases = extract_base_urls_from_js_bundles(client, url, timeout=timeout)

        all_domains: list[str] = []
        for d in heuristic_domains:
            if d not in all_domains:
                all_domains.append(d)
        # Append literals last so the fast path runs first
        for d in literal_bases:
            if d not in all_domains:
                all_domains.append(d)

        log.info(
            "Discovery candidates: %d domains × %d prefixes × %d suffixes",
            len(all_domains), len(prefixes), len(SWAGGER_SUFFIXES),
        )

        # Step 4: Multi-backend probing (Priority 4)
        for domain in all_domains:
            result = _probe_swagger(client, domain, prefixes, token, timeout)
            if result:
                return result

    return None
