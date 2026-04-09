"""Auto-detect API spec type from a URL."""

from __future__ import annotations

import re
from urllib.parse import urljoin, urlparse

import httpx

from api_to_tools.types import AuthConfig, DetectionResult, SpecType

WELL_KNOWN_PATHS: dict[SpecType, list[str]] = {
    "openapi": [
        "/openapi.json", "/openapi.yaml", "/openapi/v3.json",
        "/swagger.json", "/swagger.yaml",
        "/api-docs", "/v2/api-docs", "/v3/api-docs",
        "/.well-known/openapi",
        "/docs/openapi.json", "/docs/swagger.json",
        "/swagger/v1/swagger.json", "/swagger/v2/swagger.json",
        "/api/swagger.json", "/api/openapi.json",
        "/spec.json", "/api/spec.json",
        "/api-docs.json", "/api/api-docs",
    ],
    "wsdl": ["?wsdl", "?WSDL", "/ws?wsdl", "/services?wsdl"],
    "graphql": ["/graphql", "/.well-known/graphql"],
    "grpc": [],
    "asyncapi": ["/asyncapi.json", "/asyncapi.yaml"],
    "jsonrpc": ["/rpc", "/jsonrpc"],
}

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


def detect(url: str, *, timeout: float = 10.0, probe_paths: bool = True, auth: AuthConfig | None = None, scan_js: bool = False, crawl: bool = False) -> DetectionResult:
    """Discover API spec from a URL.

    Tries direct detection, then probes well-known paths.
    Supports authenticated discovery via AuthConfig.
    """
    # Crawler mode: skip spec detection entirely, use browser
    if crawl:
        return DetectionResult(type="crawler", spec_url=url)

    from api_to_tools.auth import get_authenticated_client

    with get_authenticated_client(auth) as client:
        # GraphQL endpoint heuristic
        if "graphql" in url or url.endswith("/gql"):
            result = _probe_graphql(url.rstrip("/"), client, timeout)
            if result:
                return result

        # Direct probe
        result = _probe(url, client, timeout)
        if result:
            return result

        # Well-known paths
        if probe_paths:
            base = url.rstrip("/")
            for paths in WELL_KNOWN_PATHS.values():
                for path in paths:
                    probe_url = f"{base}{path}" if path.startswith("?") else urljoin(base + "/", path.lstrip("/"))
                    result = _probe(probe_url, client, timeout)
                    if result:
                        return result

            # GraphQL (POST-based)
            result = _probe_graphql(base, client, timeout)
            if result:
                return result

    # Fallback: JS bundle scanning
    if scan_js:
        return DetectionResult(type="jsbundle", spec_url=url)

    raise ValueError(
        f"Could not detect API spec at {url}. "
        "Try providing the direct spec URL, or use scan_js=True to analyze JS bundles."
    )
