"""Dynamic browser-based API crawler using Playwright.

This parser runs a headless browser to:
1. Load the target website
2. Perform login (if credentials provided)
3. Navigate all discoverable pages (links, menu items, menu API responses)
4. Capture all XHR/fetch network requests (safe_mode blocks mutations)
5. Extract API endpoints from actual live traffic
"""

from __future__ import annotations

import json
import re
from typing import Any
from urllib.parse import parse_qs, urlparse

from api_to_tools.constants import (
    DEFAULT_BROWSER_WAIT,
    DEFAULT_CRAWL_TIMEOUT,
    DEFAULT_NETWORK_IDLE_TIMEOUT,
)
from api_to_tools.parsers._browser_utils import (
    attempt_login,
    click_menu_items,
    collect_href_links,
    is_mutation_request,
    launch_browser,
    normalize_route_url,
)
from api_to_tools.parsers._param_builder import (
    extract_tag_from_path,
    infer_json_type,
    is_api_url,
    normalize_path_params,
    sanitize_name,
)
from api_to_tools.types import AuthConfig, Tool, ToolParameter


# ──────────────────────────────────────────────
# Request → Tool conversion
# ──────────────────────────────────────────────

def _build_tool_from_request(request: Any, seen: set) -> Tool | None:
    """Convert a captured network request into a Tool."""
    url = request.url
    method = request.method

    if not is_api_url(url):
        return None

    parsed = urlparse(url)
    path = parsed.path.rstrip("/") or "/"
    normalized_path = normalize_path_params(path)

    key = (method, f"{parsed.netloc}{normalized_path}")
    if key in seen:
        return None
    seen.add(key)

    # Query params
    query_params: list[ToolParameter] = []
    if parsed.query:
        for name in parse_qs(parsed.query):
            query_params.append(ToolParameter(
                name=name, type="string", required=False, location="query",
            ))

    # Path params
    path_params: list[ToolParameter] = []
    for m in re.finditer(r'\{(\w+)\}', normalized_path):
        path_params.append(ToolParameter(
            name=m.group(1), type="string", required=True, location="path",
        ))

    # Body params (from captured post_data)
    body_params: list[ToolParameter] = []
    try:
        post_data = request.post_data
    except Exception:
        post_data = None

    if post_data and method in ("POST", "PUT", "PATCH"):
        try:
            body_json = json.loads(post_data)
            if isinstance(body_json, dict):
                for name, value in body_json.items():
                    body_params.append(ToolParameter(
                        name=name,
                        type=infer_json_type(value),
                        required=False,
                        location="body",
                    ))
        except (json.JSONDecodeError, TypeError):
            pass

    # Name from last path segment
    segs = [s for s in normalized_path.split("/") if s and s not in ("api", "bo", "v1", "v2", "v3")]
    name_seed = segs[-1] if segs else "request"
    name = sanitize_name(f"{method.lower()}_{name_seed}")

    endpoint = f"{parsed.scheme}://{parsed.netloc}{normalized_path}"
    is_destructive = is_mutation_request(method, url)
    description = f"{method} {normalized_path}"
    if is_destructive:
        description = f"[DESTRUCTIVE] {description}"

    return Tool(
        name=name,
        description=description,
        parameters=path_params + query_params + body_params,
        endpoint=endpoint,
        method=method,
        protocol="rest",
        response_format="json",
        tags=[extract_tag_from_path(normalized_path)],
        metadata={
            "source": "crawler",
            "raw_url": url,
            "destructive": is_destructive,
        },
    )


# ──────────────────────────────────────────────
# Main crawl entrypoint
# ──────────────────────────────────────────────

def crawl_site(
    url: str,
    *,
    auth: AuthConfig | None = None,
    max_pages: int = 50,
    timeout: float = DEFAULT_CRAWL_TIMEOUT,
    headless: bool = True,
    wait_time: float = DEFAULT_BROWSER_WAIT,
    backend: str = "auto",
    safe_mode: bool = True,
) -> list[Tool]:
    """Crawl a website with a real browser to discover API endpoints.

    Args:
        url: Website URL to crawl
        auth: Authentication config (AuthConfig with username/password for form login)
        max_pages: Maximum number of pages to visit
        timeout: Navigation timeout in seconds
        headless: Run browser in headless mode
        wait_time: Time to wait per page for async requests (seconds)
        backend: "auto" | "system" | "playwright" | "lightpanda"
        safe_mode: Block mutation requests after login (default True)
    """
    try:
        from playwright.sync_api import sync_playwright
    except ImportError as e:
        raise ImportError(
            "Playwright is not installed. Install with: pip install playwright"
        ) from e

    captured_requests: list = []
    menu_routes: list[str] = []
    safe_mode_active = [False]

    def _on_request(req: Any) -> None:
        captured_requests.append(req)

    def _on_response(response: Any) -> None:
        """Parse menu-list-like API responses to find routes to visit."""
        try:
            url_lower = response.url.lower()
            if not any(kw in url_lower for kw in ("menu", "route", "navigation", "sitemap")):
                return
            if response.status != 200:
                return
            ct = response.headers.get("content-type", "")
            if "json" not in ct:
                return
            body = response.json()

            url_keys = {"url", "path", "route", "menuurl", "pageurl", "link",
                        "menupath", "callurl", "href", "to", "pageroute"}

            def extract_urls(obj: Any) -> None:
                if isinstance(obj, dict):
                    for k, v in obj.items():
                        if k.lower() in url_keys and isinstance(v, str) and v:
                            if v.startswith("//") or v.startswith("http"):
                                continue
                            if v.startswith("javascript:") or v == "#":
                                continue
                            menu_routes.append(v)
                        elif isinstance(v, (dict, list)):
                            extract_urls(v)
                elif isinstance(obj, list):
                    for item in obj:
                        extract_urls(item)

            extract_urls(body)
        except Exception:
            pass

    def _safe_mode_route(route: Any, request: Any) -> None:
        """Intercept true mutation requests after login to prevent side effects."""
        if safe_mode_active[0] and is_mutation_request(request.method, request.url):
            route.fulfill(
                status=200,
                content_type="application/json",
                body='{"success": true, "_api_to_tools_blocked": true, '
                     '"_message": "Request blocked by api-to-tools safe_mode"}',
            )
        else:
            route.continue_()

    with sync_playwright() as p:
        browser = launch_browser(p, backend, headless)
        context = browser.contexts[0] if browser.contexts else browser.new_context(
            ignore_https_errors=True
        )
        page = context.new_page()

        page.on("request", _on_request)
        page.on("response", _on_response)

        if safe_mode:
            context.route("**/*", _safe_mode_route)

        # 1. Initial load
        try:
            page.goto(url, timeout=int(timeout * 1000), wait_until="networkidle")
        except Exception:
            try:
                page.goto(url, timeout=int(timeout * 1000))
            except Exception:
                browser.close()
                raise

        page.wait_for_timeout(int(wait_time * 1000))

        # 2. Login
        if auth and auth.username and auth.password:
            attempt_login(page, auth, wait_time)

        try:
            page.wait_for_load_state("networkidle", timeout=int(DEFAULT_NETWORK_IDLE_TIMEOUT * 1000))
        except Exception:
            pass
        page.wait_for_timeout(int(wait_time * 1000))

        if safe_mode:
            safe_mode_active[0] = True

        # 3. Gather routes to visit
        parsed_base = urlparse(url)
        base_origin = f"{parsed_base.scheme}://{parsed_base.netloc}"
        routes_to_visit = list(dict.fromkeys(menu_routes))
        for link in collect_href_links(page, base_origin):
            if link not in routes_to_visit:
                routes_to_visit.append(link)

        # 4. Visit each route
        visited: set[str] = set()
        for route in routes_to_visit:
            if len(visited) >= max_pages:
                break
            full = normalize_route_url(route, base_origin)
            if full in visited:
                continue
            visited.add(full)
            try:
                page.goto(full, timeout=int(timeout * 1000), wait_until="domcontentloaded")
                page.wait_for_timeout(int(wait_time * 1000))
                try:
                    page.wait_for_load_state("networkidle", timeout=5000)
                except Exception:
                    pass
            except Exception:
                continue

        # 5. Click sidebar menu items for SPAs without href
        click_menu_items(page, base_origin, max_pages, wait_time, visited)

        browser.close()

    # 6. Convert captured requests into Tools
    tools: list[Tool] = []
    seen: set = set()
    for req in captured_requests:
        tool = _build_tool_from_request(req, seen)
        if tool:
            tools.append(tool)

    return tools
