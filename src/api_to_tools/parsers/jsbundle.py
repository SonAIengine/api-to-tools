"""JS Bundle analyzer - discovers API endpoints from website JavaScript code."""

from __future__ import annotations

import re
from urllib.parse import urljoin, urlparse

import httpx

from api_to_tools.types import AuthConfig, Tool, ToolParameter


# Patterns to extract API calls from JavaScript
API_PATH_PATTERNS = [
    # Direct string paths: "/api/..."
    r'["\'](/api/[^"\'\`\s\)}{,]+)["\'\`]',
    # fetch/axios calls
    r'(?:fetch|axios|\.get|\.post|\.put|\.delete|\.patch)\s*\(\s*["\'\`]([^"\'\`]{5,})["\'\`]',
    # Template literal API paths
    r'\`(/api/[^`]*)\`',
    # URL concatenation patterns
    r'(?:url|endpoint|path|uri)\s*[:=]\s*["\']([^"\'\s]{5,}/[^"\'\s]+)["\']',
]

# Patterns to extract base URLs from config/env
BASE_URL_PATTERNS = [
    r'(?:API_URL|API_BASE|NEXT_PUBLIC_API|baseURL|BASE_URL|apiUrl|apiBase|serverUrl)\s*[:=]\s*["\'](https?://[^"\'\s]+)["\']',
    r'["\'](https?://[^"\'\s]*api[^"\'\s]*)["\']',
]

# HTTP method detection near API calls
METHOD_PATTERNS = [
    (r'\.get\s*\(\s*["\'\`]([^"\'\`]+)', "GET"),
    (r'\.post\s*\(\s*["\'\`]([^"\'\`]+)', "POST"),
    (r'\.put\s*\(\s*["\'\`]([^"\'\`]+)', "PUT"),
    (r'\.delete\s*\(\s*["\'\`]([^"\'\`]+)', "DELETE"),
    (r'\.patch\s*\(\s*["\'\`]([^"\'\`]+)', "PATCH"),
]

# File extensions to exclude
EXCLUDED_EXTENSIONS = {".js", ".css", ".png", ".jpg", ".jpeg", ".gif", ".svg", ".ico", ".woff", ".woff2", ".ttf", ".map"}


def _is_api_path(path: str) -> bool:
    """Check if a path looks like an API endpoint."""
    if not path or len(path) < 5:
        return False
    # Exclude static assets
    if any(path.endswith(ext) for ext in EXCLUDED_EXTENSIONS):
        return False
    # Must contain api-like segments
    lower = path.lower()
    return (
        "/api/" in lower
        or "/v1/" in lower
        or "/v2/" in lower
        or "/v3/" in lower
        or lower.startswith("/api")
        or "/rest/" in lower
        or "/graphql" in lower
    )


def _clean_path(path: str) -> str:
    """Clean up extracted path."""
    # Remove trailing punctuation
    path = path.rstrip(",;)}")
    # Remove template literal expressions like ${...}
    path = re.sub(r'\$\{[^}]+\}', '{param}', path)
    # Remove query strings
    path = path.split("?")[0]
    return path


def _infer_name(path: str) -> str:
    """Infer a tool name from API path."""
    # /api/bo/v1/common/code/getStStdCd -> getStStdCd
    parts = path.rstrip("/").split("/")
    # Use last meaningful segment
    name = parts[-1] if parts else "unknown"
    # If it's a path param placeholder, use parent
    if name.startswith("{") or name.startswith(":"):
        name = f"{parts[-2]}_{name.strip('{}:')}" if len(parts) > 1 else name
    return name


def _infer_method(path: str, context: str = "") -> str:
    """Infer HTTP method from path name and context."""
    lower = path.lower()
    last_segment = path.rstrip("/").split("/")[-1].lower()

    if any(w in last_segment for w in ["get", "list", "find", "search", "fetch", "load", "select", "check", "has"]):
        return "GET"
    if any(w in last_segment for w in ["save", "create", "regist", "add", "insert", "upload"]):
        return "POST"
    if any(w in last_segment for w in ["update", "modify", "edit", "change"]):
        return "PUT"
    if any(w in last_segment for w in ["delete", "remove"]):
        return "DELETE"
    if "login" in lower or "token" in lower or "logout" in lower:
        return "POST"

    return "POST"  # Default for RPC-style APIs


def _extract_path_params(path: str) -> list[ToolParameter]:
    """Extract path parameters from URL template."""
    params = []
    for match in re.finditer(r'\{(\w+)\}|:(\w+)', path):
        name = match.group(1) or match.group(2)
        params.append(ToolParameter(
            name=name,
            type="string",
            required=True,
            location="path",
        ))
    return params


def scan_js_bundles(
    url: str,
    *,
    auth: AuthConfig | None = None,
    timeout: float = 10.0,
    max_bundles: int = 100,
) -> list[Tool]:
    """Scan a website's JavaScript bundles to discover API endpoints.

    Fetches the HTML page, finds all JS bundles, downloads them,
    and extracts API endpoint patterns from the code.

    Args:
        url: Website URL to scan
        auth: Authentication config (for accessing protected pages)
        timeout: Request timeout per request
        max_bundles: Maximum number of JS bundles to download

    Returns:
        List of discovered Tool definitions
    """
    from api_to_tools.auth import get_authenticated_client

    parsed = urlparse(url)
    base_origin = f"{parsed.scheme}://{parsed.netloc}"

    with get_authenticated_client(auth) as client:
        # 1. Fetch the main page
        response = client.get(url, follow_redirects=True, timeout=timeout)
        html = response.text
        final_url = str(response.url)

        # 2. Collect all JS bundle URLs from the page
        js_urls: list[str] = []
        for match in re.finditer(r'src=["\']((?:[^"\']*/)?[^"\']*\.js)["\']', html):
            js_url = match.group(1)
            if js_url.startswith("//"):
                js_url = f"{parsed.scheme}:{js_url}"
            elif js_url.startswith("/"):
                js_url = f"{base_origin}{js_url}"
            elif not js_url.startswith("http"):
                js_url = urljoin(final_url, js_url)
            js_urls.append(js_url)

        # If redirected (e.g., to login page), also scan the login page
        if final_url != url:
            for match in re.finditer(r'src=["\']((?:[^"\']*/)?[^"\']*\.js)["\']', html):
                js_url = match.group(1)
                if js_url.startswith("/"):
                    js_url = f"{base_origin}{js_url}"
                elif not js_url.startswith("http"):
                    js_url = urljoin(final_url, js_url)
                if js_url not in js_urls:
                    js_urls.append(js_url)

        js_urls = list(dict.fromkeys(js_urls))[:max_bundles]  # dedupe, limit

        # 3. Download and analyze each JS bundle
        api_endpoints: dict[str, str] = {}  # path -> inferred method
        base_urls_found: set[str] = set()

        for js_url in js_urls:
            try:
                js_response = client.get(js_url, timeout=timeout)
                js_code = js_response.text

                # Extract base URLs
                for pattern in BASE_URL_PATTERNS:
                    for m in re.finditer(pattern, js_code, re.I):
                        base_urls_found.add(m.group(1))

                # Extract API paths with method hints
                for pattern, method in METHOD_PATTERNS:
                    for m in re.finditer(pattern, js_code):
                        path = _clean_path(m.group(1))
                        if _is_api_path(path):
                            api_endpoints[path] = method

                # Extract general API paths
                for pattern in API_PATH_PATTERNS:
                    for m in re.finditer(pattern, js_code):
                        path = _clean_path(m.group(1))
                        if _is_api_path(path) and path not in api_endpoints:
                            api_endpoints[path] = _infer_method(path)

            except (httpx.HTTPError, httpx.InvalidURL):
                continue

    # 4. Determine base URL
    api_base = base_origin
    if base_urls_found:
        # Prefer the most specific API base URL
        for bu in sorted(base_urls_found, key=len, reverse=True):
            if "api" in bu.lower():
                api_base = bu.rstrip("/")
                break

    # 5. Convert to Tool definitions
    tools: list[Tool] = []
    for path, method in sorted(api_endpoints.items()):
        # Build full endpoint URL
        if path.startswith("http"):
            endpoint = path
        elif path.startswith("/"):
            endpoint = f"{base_origin}{path}"
        else:
            endpoint = f"{api_base}/{path}"

        # Infer tags from path segments
        # /api/bo/v1/common/code/getStStdCd -> ["common", "code"]
        segments = [s for s in path.split("/") if s and s not in ("api", "bo", "v1", "v2", "v3", "rest")]
        tag = segments[0] if segments else "unknown"

        tools.append(Tool(
            name=_infer_name(path),
            description=f"{method} {path}",
            parameters=_extract_path_params(path),
            endpoint=endpoint,
            method=method,
            protocol="rest",
            response_format="json",
            tags=[tag],
            metadata={"source": "jsbundle", "raw_path": path},
        ))

    return tools
