"""Nexacro (넥사크로) platform crawler and parser.

Nexacro is a proprietary enterprise UI platform widely used by Korean
large enterprises (롯데, 현대, 삼성 계열사, 금융권 등).

Characteristics:
- Backend: Spring 3.x with XML config (NOT annotation-based)
- Protocol: HTTP POST with SSV (Semi-colon Separated Values) payloads
- Frontend: Nexacro XADL (proprietary XML-based UI definition)
- URLs: RPC-style, e.g. /nexa/common/getCodeList.lotte

Strategy:
1. Use Playwright to load the Nexacro application
2. Navigate pages and trigger user interactions
3. Intercept all POST requests
4. Detect SSV responses and parse them
5. Build Tool definitions from captured traffic
"""

from __future__ import annotations

import re
from typing import Any
from urllib.parse import urlparse

from api_to_tools.constants import (
    DEFAULT_BROWSER_WAIT,
    DEFAULT_CRAWL_TIMEOUT,
    DEFAULT_NETWORK_IDLE_TIMEOUT,
    NEXACRO_URL_PATTERNS,
)
from api_to_tools.parsers._browser_utils import (
    attempt_login,
    collect_href_links,
    launch_browser,
)
from api_to_tools.parsers._param_builder import sanitize_name
from api_to_tools.parsers.ssv import (
    extract_ssv_schema,
    is_ssv_content,
    parse_ssv,
)
from api_to_tools.types import AuthConfig, Tool, ToolParameter


def _is_nexacro_endpoint(url: str) -> bool:
    """Heuristic: is this URL likely a Nexacro service endpoint?"""
    parsed = urlparse(url)
    path = parsed.path.lower()
    return any(p in path for p in NEXACRO_URL_PATTERNS) and parsed.scheme in ("http", "https")


def _parse_request_body(body: str) -> dict:
    """Parse a Nexacro request body (SSV or form-encoded)."""
    if not body:
        return {}

    if is_ssv_content(body):
        return parse_ssv(body)

    # Form-encoded fallback
    try:
        from urllib.parse import parse_qs
        parsed = parse_qs(body)
        return {k: v[0] if len(v) == 1 else v for k, v in parsed.items()}
    except Exception:
        return {}


def _build_tool_from_nexacro_request(
    request,
    seen: set,
    response_text: str | None = None,
) -> Tool | None:
    """Convert a Nexacro HTTP request into a Tool definition."""
    url = request.url
    method = request.method

    if not _is_nexacro_endpoint(url):
        return None
    if method not in ("POST", "GET"):
        return None

    parsed = urlparse(url)
    path = parsed.path

    # Dedupe by (method, path without query)
    key = (method, f"{parsed.netloc}{path}")
    if key in seen:
        return None
    seen.add(key)

    # Extract name from last path segment (before extension)
    segments = [s for s in path.split("/") if s]
    last = segments[-1] if segments else "request"
    name = re.sub(r'\.[a-z]+$', '', last)  # strip .lotte, .do, etc.
    name = sanitize_name(name) or "request"

    # Parse request body for parameters
    parameters: list[ToolParameter] = []
    post_data = None
    try:
        post_data = request.post_data
    except Exception:
        pass

    if post_data:
        body_dict = _parse_request_body(post_data)
        for pname, value in body_dict.items():
            # Skip Nexacro-internal fields
            if pname.startswith("_") or pname in (
                "SessionId", "ErrorCode", "ErrorMsg", "ErrorType", "ErrorKey",
            ):
                continue
            # Skip dataset fields (lists), they're response-only typically
            if isinstance(value, list):
                continue

            if isinstance(value, bool):
                ptype = "boolean"
            elif isinstance(value, int):
                ptype = "integer"
            elif isinstance(value, float):
                ptype = "number"
            elif isinstance(value, dict):
                ptype = "object"
            else:
                ptype = "string"

            parameters.append(ToolParameter(
                name=pname,
                type=ptype,
                required=False,
                location="body",
                description=f"example: {value}" if value else None,
            ))

    # Also include query parameters
    if parsed.query:
        from urllib.parse import parse_qs
        for pname in parse_qs(parsed.query):
            parameters.append(ToolParameter(
                name=pname,
                type="string",
                required=False,
                location="query",
            ))

    # Extract response schema from SSV
    response_schema = None
    if response_text and is_ssv_content(response_text):
        schema = extract_ssv_schema(response_text)
        if schema.get("scalars") or schema.get("datasets"):
            # Flatten for LLM consumption
            flat = {}
            for k, v in schema.get("scalars", {}).items():
                flat[k] = v
            for ds_name, ds_cols in schema.get("datasets", {}).items():
                flat[f"{ds_name}[]"] = ds_cols
            response_schema = flat

    # Tag from URL segment after the nexa prefix
    tag = "nexacro"
    for i, seg in enumerate(segments):
        if seg.lower() in ("nexa", "nexacro", "nex"):
            if i + 1 < len(segments):
                tag = segments[i + 1]
                break
    else:
        if len(segments) >= 2:
            tag = segments[-2]

    metadata: dict = {
        "source": "nexacro_crawler",
        "protocol_variant": "nexacro-ssv",
    }
    if response_schema:
        metadata["response_schema"] = response_schema

    endpoint = f"{parsed.scheme}://{parsed.netloc}{path}"

    return Tool(
        name=name,
        description=f"[Nexacro] {method} {path}",
        parameters=parameters,
        endpoint=endpoint,
        method=method,
        protocol="rest",  # HTTP-based, but SSV payload
        response_format="json",  # We parse SSV to JSON
        tags=[tag],
        metadata=metadata,
    )


def crawl_nexacro_site(
    url: str,
    *,
    auth: AuthConfig | None = None,
    max_pages: int = 50,
    timeout: float = DEFAULT_CRAWL_TIMEOUT,
    headless: bool = True,
    wait_time: float = DEFAULT_BROWSER_WAIT,
    backend: str = "auto",
) -> list[Tool]:
    """Crawl a Nexacro-based website to discover API endpoints.

    Uses Playwright to navigate the app and captures all POST requests
    with SSV responses. Supports both explicit Nexacro URL patterns
    (/nexa/, .lotte, .do) and generic POST endpoints.
    """
    try:
        from playwright.sync_api import sync_playwright
    except ImportError as e:
        raise ImportError(
            "Playwright is not installed. Install with: pip install playwright"
        ) from e

    captured_requests: list = []
    response_bodies: dict = {}  # request_id → response text

    def _on_request(req: Any) -> None:
        captured_requests.append(req)

    def _on_response(response: Any) -> None:
        """Capture SSV responses and menu data."""
        try:
            if not _is_nexacro_endpoint(response.url):
                return
            if response.status != 200:
                return
            body = response.text()
            if body and is_ssv_content(body):
                response_bodies[id(response.request)] = body
        except Exception:
            pass

    with sync_playwright() as p:
        browser = launch_browser(p, backend, headless)
        context = browser.contexts[0] if browser.contexts else browser.new_context(
            ignore_https_errors=True
        )
        page = context.new_page()

        page.on("request", _on_request)
        page.on("response", _on_response)

        # 1. Initial load
        try:
            page.goto(url, timeout=int(timeout * 1000), wait_until="domcontentloaded")
        except Exception:
            page.goto(url, timeout=int(timeout * 1000))
        page.wait_for_timeout(int(wait_time * 1000))

        # 2. Login if credentials provided
        if auth and auth.username and auth.password:
            attempt_login(page, auth, wait_time)

        try:
            page.wait_for_load_state("networkidle", timeout=int(DEFAULT_NETWORK_IDLE_TIMEOUT * 1000))
        except Exception:
            pass
        page.wait_for_timeout(int(wait_time * 1000))

        # 3. Collect links and navigate
        parsed = urlparse(url)
        base_origin = f"{parsed.scheme}://{parsed.netloc}"
        links = collect_href_links(page, base_origin)[:max_pages]

        visited = set()
        for link in links:
            if len(visited) >= max_pages:
                break
            if link in visited:
                continue
            visited.add(link)
            try:
                page.goto(link, timeout=int(timeout * 1000), wait_until="domcontentloaded")
                page.wait_for_timeout(int(wait_time * 1000))
                try:
                    page.wait_for_load_state("networkidle", timeout=4000)
                except Exception:
                    pass
            except Exception:
                continue

        browser.close()

    # 4. Build tools from captured requests
    tools: list[Tool] = []
    seen: set = set()
    for req in captured_requests:
        resp_text = response_bodies.get(id(req))
        tool = _build_tool_from_nexacro_request(req, seen, resp_text)
        if tool:
            tools.append(tool)

    return tools
