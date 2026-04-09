"""Auto-detect API spec type from a URL."""

from __future__ import annotations

import re
from urllib.parse import urljoin, urlparse

import httpx

from api_to_tools._logging import get_logger
from api_to_tools.constants import (
    DEFAULT_HTTP_TIMEOUT,
    NEXACRO_HTML_SIGNATURES,
    WELL_KNOWN_PATHS as _WELL_KNOWN_PATHS_RAW,
)
from api_to_tools.types import AuthConfig, DetectionResult, SpecType

log = get_logger("detector")

WELL_KNOWN_PATHS: dict[SpecType, list[str]] = dict(_WELL_KNOWN_PATHS_RAW)  # type: ignore[arg-type]

GRAPHQL_PROBE_QUERY = '{"query":"{ __schema { types { name } } }"}'


def _detect_from_content(content: str, content_type: str = "") -> SpecType | None:
    """Detect spec type from response content."""
    # JSON
    if "json" in content_type or content.lstrip().startswith("{"):
        try:
            import json
            data = json.loads(content)
            if "openapi" in data or "swagger" in data:
                return "openapi"
            if "asyncapi" in data:
                return "asyncapi"
            if isinstance(data.get("data"), dict) and "__schema" in data["data"]:
                return "graphql"
        except (json.JSONDecodeError, TypeError):
            pass

    # XML
    if "xml" in content_type or content.lstrip().startswith("<"):
        if "<definitions" in content or "<wsdl:definitions" in content:
            return "wsdl"

    # YAML
    if "openapi:" in content or "swagger:" in content:
        return "openapi"
    if "asyncapi:" in content:
        return "asyncapi"

    return None


def _extract_spec_url_from_html(html: str, base_url: str, client: httpx.Client, timeout: float) -> str | None:
    """Extract spec URL from Swagger UI / Redoc HTML."""
    # Swagger UI: url: "..."
    m = re.search(r'url:\s*["\']([^"\']+)["\']', html)
    if m:
        return urljoin(base_url, m.group(1))

    # Redoc: spec-url="..."
    m = re.search(r'spec-url=["\']([^"\']+)["\']', html)
    if m:
        return urljoin(base_url, m.group(1))

    # Link tag
    m = re.search(r'<link[^>]+rel=["\']api-definition["\'][^>]+href=["\']([^"\']+)["\']', html)
    if m:
        return urljoin(base_url, m.group(1))

    # Swagger UI initializer JS
    for script_match in re.finditer(r'<script[^>]+src=["\']([^"\']*(?:initializer|config)[^"\']*)["\']', html, re.I):
        try:
            js_url = urljoin(base_url, script_match.group(1))
            js_res = client.get(js_url, timeout=timeout)
            if js_res.is_success:
                js = js_res.text
                # url: "https://..." pattern
                url_m = re.search(r'url:\s*["\'](https?://[^"\']+|/[^"\'/][^"\']*)["\']', js)
                if url_m:
                    return urljoin(base_url, url_m.group(1))
                # Variable assignment pattern
                var_m = re.search(
                    r'(?:const|let|var)\s+\w*(?:url|definition|spec|swagger|openapi)\w*\s*=\s*["\'](https?://[^"\']+\.json[^"\']*)["\']',
                    js, re.I,
                )
                if var_m:
                    return urljoin(base_url, var_m.group(1))
        except httpx.HTTPError:
            continue

    return None


def _probe(url: str, client: httpx.Client, timeout: float) -> DetectionResult | None:
    """Probe a URL for an API spec."""
    try:
        res = client.get(url, timeout=timeout, follow_redirects=True,
                         headers={"Accept": "application/json, application/xml, text/yaml, */*"})
        if not res.is_success:
            return None

        ct = res.headers.get("content-type", "")
        content = res.text
        spec_type = _detect_from_content(content, ct)

        if spec_type:
            return DetectionResult(type=spec_type, spec_url=url, raw_content=content, content_type=ct)

        # HTML -> extract spec URL
        if "html" in ct:
            spec_url = _extract_spec_url_from_html(content, url, client, timeout)
            if spec_url:
                return _probe(spec_url, client, timeout)

        return None
    except (httpx.HTTPError, httpx.InvalidURL):
        return None


def _probe_graphql(base_url: str, client: httpx.Client, timeout: float) -> DetectionResult | None:
    """Try GraphQL introspection."""
    urls = [base_url] + [urljoin(base_url + "/", p.lstrip("/")) for p in WELL_KNOWN_PATHS["graphql"]]
    seen = set()
    for url in urls:
        if url in seen:
            continue
        seen.add(url)
        try:
            res = client.post(url, content=GRAPHQL_PROBE_QUERY,
                              headers={"Content-Type": "application/json"}, timeout=timeout)
            if res.is_success and "__schema" in res.text:
                return DetectionResult(type="graphql", spec_url=url)
        except (httpx.HTTPError, httpx.InvalidURL):
            continue
    return None


def _detect_nexacro(client: httpx.Client, url: str, timeout: float) -> bool:
    """Detect if a site is a Nexacro-based application."""
    try:
        res = client.get(url, follow_redirects=True, timeout=timeout)
        html = res.text.lower()
        return any(sig in html for sig in NEXACRO_HTML_SIGNATURES)
    except httpx.HTTPError as e:
        log.debug("Nexacro detection failed for %s: %s", url, e)
        return False


def detect(url: str, *, timeout: float = 10.0, probe_paths: bool = True, auth: AuthConfig | None = None, scan_js: bool = False, crawl: bool = False, cdp: bool = False) -> DetectionResult:
    """Discover API spec from a URL.

    Tries direct detection, then probes well-known paths.
    Supports authenticated discovery via AuthConfig.
    """
    log.debug("detect() start url=%s crawl=%s scan_js=%s auth=%s",
              url, crawl, scan_js, bool(auth))

    # Crawler mode: skip spec detection entirely, use browser
    if crawl:
        return DetectionResult(type="crawler", spec_url=url)

    # CDP mode: drive headless Chrome via DevTools Protocol (no Playwright)
    if cdp:
        return DetectionResult(type="cdp", spec_url=url)

    from api_to_tools.auth import get_authenticated_client

    with get_authenticated_client(auth) as client:
        # Nexacro platform detection (before generic crawling)
        if _detect_nexacro(client, url, timeout):
            log.info("Detected Nexacro platform at %s", url)
            return DetectionResult(type="nexacro", spec_url=url)

        # GraphQL endpoint heuristic
        if "graphql" in url or url.endswith("/gql"):
            result = _probe_graphql(url.rstrip("/"), client, timeout)
            if result:
                return result

        # Direct probe
        result = _probe(url, client, timeout)
        if result:
            return result

        # Well-known paths (parallel probing, OpenAPI first)
        if probe_paths:
            base = url.rstrip("/")
            # Priority order: OpenAPI is most common, probe first
            ordered = list(WELL_KNOWN_PATHS.get("openapi", []))
            for st, paths in WELL_KNOWN_PATHS.items():
                if st != "openapi":
                    ordered.extend(paths)

            probe_urls = [
                f"{base}{path}" if path.startswith("?") else urljoin(base + "/", path.lstrip("/"))
                for path in ordered
            ]

            # Parallel batch probing (6 at a time)
            from concurrent.futures import ThreadPoolExecutor, as_completed
            batch_size = 6
            for i in range(0, len(probe_urls), batch_size):
                batch = probe_urls[i:i + batch_size]
                with ThreadPoolExecutor(max_workers=batch_size) as ex:
                    futures = {ex.submit(_probe, u, client, timeout): u for u in batch}
                    for fut in as_completed(futures):
                        try:
                            res = fut.result()
                            if res:
                                return res
                        except Exception:
                            continue

            # GraphQL (POST-based)
            gql_result = _probe_graphql(base, client, timeout)
            if gql_result:
                return gql_result

    # Authenticated Swagger discovery (login → guess backend → probe with Bearer)
    if auth and auth.username and auth.password:
        from api_to_tools.detector.swagger_discovery import discover_swagger_with_auth
        result = discover_swagger_with_auth(url, auth, timeout=timeout)
        if result:
            return result

    # Static SPA analysis (browser-free): parse all JS chunks via AST
    # This runs BEFORE Playwright crawler as an opt-in default fallback.
    # Always try this if scan_js is explicitly True.
    if scan_js:
        return DetectionResult(type="static_spa", spec_url=url)

    raise ValueError(
        f"Could not detect API spec at {url}. "
        "Try providing the direct spec URL, or use scan_js=True to analyze JS bundles."
    )
