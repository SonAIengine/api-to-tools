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
from concurrent.futures import Future, ThreadPoolExecutor, as_completed
from urllib.parse import urlparse

import httpx

from api_to_tools._logging import get_logger
from api_to_tools.auth import try_api_login
from api_to_tools.constants import (
    DEFAULT_AUTH_TIMEOUT,
    DEFAULT_HTTP_TIMEOUT,
    DEFAULT_JS_FETCH_TIMEOUT,
    DEFAULT_PROBE_RPS,
    DEFAULT_PROBE_TIMEOUT,
)
from api_to_tools.rate_limiter import get_domain_limiter
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
    timeout: float = DEFAULT_JS_FETCH_TIMEOUT,
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
        res = client.get(url, follow_redirects=True, timeout=DEFAULT_HTTP_TIMEOUT)
        html = res.text
        prefixes.update(_extract_api_prefixes_from_text(html))

        if len(prefixes) < 2:
            js_urls = re.findall(r'src=["\']([^"\']*\.js)["\']', html)
            parsed = urlparse(str(res.url))
            origin = f"{parsed.scheme}://{parsed.netloc}"
            for js_url in js_urls[:15]:
                full = f"{origin}{js_url}" if js_url.startswith("/") else js_url
                try:
                    jr = client.get(full, timeout=DEFAULT_JS_FETCH_TIMEOUT)
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
# Login helper — delegates to auth.try_api_login
# ──────────────────────────────────────────────

def _try_login(client: httpx.Client, frontend_url: str, auth: AuthConfig) -> str | None:
    """Attempt login with auto-discovered API prefixes."""
    prefixes = _extract_api_prefixes(client, frontend_url)
    return try_api_login(client, frontend_url, auth, prefixes=prefixes)


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

    # Rate limit per target domain
    domain = urlparse(url).netloc
    limiter = get_domain_limiter(domain, DEFAULT_PROBE_RPS)
    limiter.acquire()

    # Build header attempts in order of likelihood
    attempts: list[dict] = []
    if token:
        attempts.append({"Authorization": f"Bearer {token}"})
    attempts.append({})  # cookie only (client already has cookies from login)

    # Short per-probe timeout so we fail fast
    probe_timeout = min(timeout, DEFAULT_PROBE_TIMEOUT)

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


def _cancel_remaining(futures: dict[Future, str]) -> None:
    """Best-effort cancel all pending futures."""
    for fut in futures:
        fut.cancel()


# Max concurrent probes per domain — keeps request fan-out bounded
_PROBE_WORKERS = 12


def _probe_swagger(
    client: httpx.Client,
    domain: str,
    prefixes: list[str],
    token: str | None,
    timeout: float,
) -> DetectionResult | None:
    """Try all swagger path combinations on a domain (parallel, early exit)."""
    urls_to_try = _build_probe_urls(domain, prefixes)
    log.debug("Probing %d URLs on %s (parallel, %d workers)", len(urls_to_try), domain, _PROBE_WORKERS)

    with ThreadPoolExecutor(max_workers=_PROBE_WORKERS) as executor:
        futures: dict[Future, str] = {
            executor.submit(_probe_single, client, url, token, timeout): url
            for url in urls_to_try
        }
        for fut in as_completed(futures):
            try:
                result = fut.result()
                if result:
                    _cancel_remaining(futures)
                    return result
            except Exception:
                continue
    return None


# ──────────────────────────────────────────────
# Main entrypoint — orchestrates all priorities
# ──────────────────────────────────────────────

def discover_swagger_with_auth(
    url: str,
    auth: AuthConfig,
    *,
    timeout: float = DEFAULT_AUTH_TIMEOUT,
) -> DetectionResult | None:
    """Find a Swagger/OpenAPI spec by combining login, domain guessing,
    JS base URL extraction, and multi-auth probing."""

    with httpx.Client(follow_redirects=True, verify=auth.verify_ssl, timeout=timeout) as client:
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

        # Step 4: Multi-backend probing — parallel across domains (Priority 4)
        # Each domain internally runs parallel URL probing via _probe_swagger.
        # We probe up to 4 domains concurrently and early-exit on first hit.
        _DOMAIN_WORKERS = min(4, len(all_domains))
        with ThreadPoolExecutor(max_workers=_DOMAIN_WORKERS) as executor:
            futures: dict[Future, str] = {
                executor.submit(_probe_swagger, client, domain, prefixes, token, timeout): domain
                for domain in all_domains
            }
            for fut in as_completed(futures):
                try:
                    result = fut.result()
                    if result:
                        _cancel_remaining(futures)
                        return result
                except Exception:
                    continue

    return None
