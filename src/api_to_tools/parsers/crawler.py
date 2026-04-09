"""Dynamic browser-based API crawler using Playwright.

This parser actually runs a headless browser to:
1. Load the target website
2. Perform login (if credentials provided)
3. Navigate all discoverable pages (links, menu items, menu API responses)
4. Capture all XHR/fetch network requests
5. Extract API endpoints from actual live traffic
"""

from __future__ import annotations

import json
import re
from urllib.parse import parse_qs, urljoin, urlparse

from api_to_tools.types import AuthConfig, Tool, ToolParameter


def _is_api_request(url: str) -> bool:
    """Determine if a URL looks like an API call."""
    parsed = urlparse(url)
    path = parsed.path.lower()

    static_exts = (".js", ".css", ".png", ".jpg", ".jpeg", ".gif", ".svg",
                   ".ico", ".woff", ".woff2", ".ttf", ".map", ".html", ".mp4", ".webp")
    if any(path.endswith(ext) for ext in static_exts):
        return False
    if "/_next/" in path or "/__nextjs" in path:
        return False

    return (
        "/api/" in path
        or "/v1/" in path or "/v2/" in path or "/v3/" in path
        or "/rest/" in path
        or "/graphql" in path
        or "/rpc/" in path
    )


def _infer_json_type(value) -> str:
    if isinstance(value, bool):
        return "boolean"
    if isinstance(value, int):
        return "integer"
    if isinstance(value, float):
        return "number"
    if isinstance(value, list):
        return "array"
    if isinstance(value, dict):
        return "object"
    return "string"


def _extract_tag(path: str) -> str:
    """Extract meaningful tag from API path, skipping api/v1/v2/bo etc."""
    segments = [s for s in path.split("/") if s]
    # Skip common prefixes
    skip = {"api", "bo", "v1", "v2", "v3", "rest", "admin"}
    for seg in segments:
        if seg.lower() not in skip:
            return seg
    return segments[0] if segments else "api"


def _normalize_path_params(path: str) -> str:
    """Regex-based normalization: numeric IDs, UUIDs, alphanumeric codes."""
    # UUIDs
    path = re.sub(
        r'/[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}(/|$)',
        r'/{uuid}\1',
        path,
    )
    # Pure numeric IDs (/{id})
    path = re.sub(r'/\d+(/|$)', r'/{id}\1', path)
    # Long alphanumeric codes like LA01010000, AB12345, etc. (>= 5 chars, must have digit)
    path = re.sub(r'/[A-Z][A-Z0-9]{4,}(/|$)', r'/{code}\1', path)
    # Lowercase hash-like codes (e.g., sessionIDs)
    path = re.sub(r'/[0-9a-f]{24,}(/|$)', r'/{hash}\1', path)
    return path


def _infer_templates_from_paths(paths: list[str]) -> dict[str, str]:
    """2-pass: compare paths with same segment count to detect variable segments.

    Returns a map of raw_path -> templated_path.
    """
    # Group by segment signature (ignoring last alphanumeric segment)
    by_length: dict[int, list[list[str]]] = {}
    for p in paths:
        segs = p.strip("/").split("/")
        by_length.setdefault(len(segs), []).append(segs)

    # For each length group, find positions where values differ across paths
    # but only if the prefix matches
    templates: dict[str, str] = {}
    for length, segment_lists in by_length.items():
        if len(segment_lists) < 2:
            continue
        # Group by prefix (first N-1 segments)
        prefix_groups: dict[tuple, list[list[str]]] = {}
        for segs in segment_lists:
            key = tuple(segs[:-1])
            prefix_groups.setdefault(key, []).append(segs)

        for prefix, group in prefix_groups.items():
            if len(group) < 2:
                continue
            # Last segments differ → treat as path param
            last_values = {segs[-1] for segs in group}
            if len(last_values) >= 2:
                for segs in group:
                    raw = "/" + "/".join(segs)
                    tmpl = "/" + "/".join(list(prefix) + ["{id}"])
                    templates[raw] = tmpl

        # Also check: every position could be variable if paths share same length but differ at multiple spots
        # Only if they have matching HEAD prefix (at least 2 segs in common)

    return templates


def _build_tool_from_request(request, seen: set, path_templates: dict | None = None) -> Tool | None:
    """Convert a captured network request into a Tool."""
    url = request.url
    method = request.method

    if not _is_api_request(url):
        return None

    parsed = urlparse(url)
    path = parsed.path.rstrip("/") or "/"

    # 1st pass: regex normalization
    normalized_path = _normalize_path_params(path)

    # 2nd pass: template inference (if provided)
    if path_templates and path in path_templates:
        normalized_path = path_templates[path]

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

    # Body params
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
                        name=name, type=_infer_json_type(value),
                        required=False, location="body",
                    ))
        except (json.JSONDecodeError, TypeError):
            pass

    # Name from last path segment
    segs = [s for s in normalized_path.split("/") if s and s not in ("api", "bo", "v1", "v2", "v3")]
    name = segs[-1] if segs else "request"
    name = re.sub(r'[^a-zA-Z0-9_]', '_', name).strip("_")

    endpoint = f"{parsed.scheme}://{parsed.netloc}{normalized_path}"

    is_destructive = _is_mutation_request(method, url)
    description = f"{method} {normalized_path}"
    if is_destructive:
        description = f"[DESTRUCTIVE] {description}"

    return Tool(
        name=f"{method.lower()}_{name}",
        description=description,
        parameters=path_params + query_params + body_params,
        endpoint=endpoint,
        method=method,
        protocol="rest",
        response_format="json",
        tags=[_extract_tag(normalized_path)],
        metadata={
            "source": "crawler",
            "raw_url": url,
            "destructive": is_destructive,
        },
    )


SAFE_HTTP_METHODS = {"GET", "HEAD", "OPTIONS"}
# URL keywords that hint the request is a login/auth call (allowed even in safe mode)
AUTH_KEYWORDS = ("login", "signin", "sign-in", "auth", "token", "refresh", "logout", "signout")
# URL last-segment keywords that indicate a read-only operation (safe even if POST)
READ_KEYWORDS = (
    "get", "find", "list", "search", "query", "check", "has", "is", "fetch",
    "load", "retrieve", "view", "show", "count", "exist", "lookup", "select",
    "read", "info", "detail", "status",
)
# Keywords that strongly indicate a destructive / mutating operation
MUTATION_KEYWORDS = (
    "delete", "remove", "destroy", "drop", "erase",
    "create", "add", "insert", "regist", "new",
    "update", "modify", "edit", "change", "set", "put",
    "save", "upsert", "upload", "import",
    "send", "publish", "submit", "issue", "execute", "run",
    "approve", "reject", "cancel",
)


def _is_mutation_request(method: str, url: str) -> bool:
    """Heuristic: does this request modify server state?

    Returns True only if we're reasonably confident it's a mutation.
    False for reads (even if sent as POST - common in RPC-style APIs).
    """
    if method in SAFE_HTTP_METHODS:
        return False

    url_lower = url.lower()
    last_segment = url_lower.rstrip("/").split("/")[-1].split("?")[0]

    # Auth/session endpoints are allowed even though they're POST
    if any(kw in url_lower for kw in AUTH_KEYWORDS):
        return False

    # Read-style RPC endpoints: get*, find*, list*, search*, etc.
    if any(last_segment.startswith(kw) for kw in READ_KEYWORDS):
        return False
    if any(kw in last_segment for kw in ("list", "detail", "info", "status")):
        return False

    # DELETE/PUT/PATCH are always mutations
    if method in ("DELETE", "PUT", "PATCH"):
        return True

    # POST with mutation keywords in path
    if any(kw in url_lower for kw in MUTATION_KEYWORDS):
        return True

    # Default for POST: treat as mutation to be safe
    return True


def _launch_browser(playwright, backend: str, headless: bool):
    """Launch a browser with the specified backend.

    Backends:
      - "auto": try system Chrome first, fall back to Playwright Chromium
      - "system": system Chrome (requires Chrome installed, no download)
      - "playwright": Playwright-bundled Chromium
      - "lightpanda": Connect to running Lightpanda CDP server on :9222
    """
    if backend in ("auto", "system"):
        try:
            return playwright.chromium.launch(channel="chrome", headless=headless)
        except Exception:
            if backend == "system":
                raise RuntimeError(
                    "System Chrome not found. Install Chrome or use backend='playwright'."
                )
            # auto: fall through to playwright

    if backend in ("auto", "playwright"):
        try:
            return playwright.chromium.launch(headless=headless)
        except Exception as e:
            raise RuntimeError(
                "Playwright Chromium not found. Install with:\n"
                "  python -m playwright install chromium\n"
                "Or install Chrome and use backend='system'."
            ) from e

    if backend == "lightpanda":
        return playwright.chromium.connect_over_cdp("ws://127.0.0.1:9222/")

    raise ValueError(f"Unknown backend: {backend}")


def crawl_site(
    url: str,
    *,
    auth: AuthConfig | None = None,
    max_pages: int = 50,
    timeout: float = 30.0,
    headless: bool = True,
    wait_time: float = 2.0,
    backend: str = "auto",
    safe_mode: bool = True,
    endpoint_rewrite: dict[str, str] | None = None,
) -> list[Tool]:
    """Crawl a website with a real browser to discover API endpoints.

    Args:
        url: Website URL to crawl
        auth: Authentication config (AuthConfig with username/password for form login)
        max_pages: Maximum number of pages to visit
        timeout: Navigation timeout in seconds
        headless: Run browser in headless mode
        wait_time: Time to wait per page for async requests (seconds)
        backend: Browser backend - "auto" (prefer system Chrome), "system",
                 "playwright", or "lightpanda"
        safe_mode: If True, intercepts non-GET requests after login so that
                   destructive operations (POST/PUT/DELETE/PATCH) are captured
                   but NOT sent to the server. Essential for crawling live sites.
    """
    try:
        from playwright.sync_api import sync_playwright
    except ImportError as e:
        raise ImportError(
            "Playwright is not installed. Install with:\n"
            "  pip install playwright"
        ) from e

    captured_requests: list = []
    menu_routes: list[str] = []
    safe_mode_active = [False]  # mutable closure

    def _handle_request(req):
        captured_requests.append(req)

    def _handle_response(response):
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
            # Recursively find URL-like fields in menu responses
            url_keys = {"url", "path", "route", "menuurl", "pageurl", "link",
                        "menupath", "callurl", "href", "to", "pageroute"}

            def extract_urls(obj):
                if isinstance(obj, dict):
                    for k, v in obj.items():
                        if k.lower() in url_keys and isinstance(v, str) and v:
                            # Accept both /absolute and relative paths
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

    def _safe_mode_route(route, request):
        """Intercept true mutation requests after login to prevent side effects."""
        if safe_mode_active[0] and _is_mutation_request(request.method, request.url):
            # Blocked mutation - request is already recorded via page.on("request")
            route.fulfill(
                status=200,
                content_type="application/json",
                body='{"success": true, "_api_to_tools_blocked": true, '
                     '"_message": "Request blocked by api-to-tools safe_mode"}',
            )
        else:
            route.continue_()

    with sync_playwright() as p:
        browser = _launch_browser(p, backend, headless)
        if browser.contexts:
            context = browser.contexts[0]
        else:
            context = browser.new_context(ignore_https_errors=True)
        page = context.new_page()

        page.on("request", _handle_request)
        page.on("response", _handle_response)

        # Install safe-mode route handler (applies to all requests under context)
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
            _attempt_login(page, auth, wait_time)

        # 3. Wait for initial dashboard to load (menu API calls happen here)
        try:
            page.wait_for_load_state("networkidle", timeout=10000)
        except Exception:
            pass
        page.wait_for_timeout(int(wait_time * 1000))

        # Activate safe mode AFTER login so subsequent mutations are blocked
        if safe_mode:
            safe_mode_active[0] = True

        # 4. Gather routes to visit
        parsed_base = urlparse(url)
        base_origin = f"{parsed_base.scheme}://{parsed_base.netloc}"
        routes_to_visit = list(dict.fromkeys(menu_routes))  # routes from menu API
        href_links = _collect_href_links(page, base_origin)
        for link in href_links:
            if link not in routes_to_visit:
                routes_to_visit.append(link)

        # Limit and visit each route
        visited = set()
        for idx, route in enumerate(routes_to_visit):
            if len(visited) >= max_pages:
                break
            # Normalize to full URL
            if route.startswith("http"):
                full = route
            elif route.startswith("/"):
                full = f"{base_origin}{route}"
            else:
                # Relative path (e.g., "member/member-mgmt/...")
                full = f"{base_origin}/{route.lstrip('/')}"

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

        # 5. Also try clicking sidebar menu items for SPAs without href
        _click_menu_items(page, base_origin, max_pages, wait_time, visited)

        browser.close()

    # Convert captured requests
    tools: list[Tool] = []
    seen: set = set()
    for req in captured_requests:
        tool = _build_tool_from_request(req, seen)
        if tool:
            tools.append(tool)

    return tools


def _attempt_login(page, auth: AuthConfig, wait_time: float) -> None:
    """Fill and submit a login form."""
    username_selectors = [
        'input[name="loginId"]', 'input[name="username"]', 'input[name="email"]',
        'input[name="user"]', 'input[name="id"]', 'input[type="email"]',
        'input[id*="login" i]', 'input[id*="user" i]',
    ]
    password_selectors = [
        'input[name="password"]', 'input[name="passwd"]', 'input[name="pwd"]',
        'input[type="password"]',
    ]
    submit_selectors = [
        'button[type="submit"]', 'input[type="submit"]',
        'button:has-text("로그인")', 'button:has-text("Login")',
        'button:has-text("Sign in")', 'button:has-text("Sign In")',
    ]

    for sel in username_selectors:
        try:
            if page.locator(sel).count() > 0:
                page.locator(sel).first.fill(auth.username or "")
                break
        except Exception:
            continue

    for sel in password_selectors:
        try:
            if page.locator(sel).count() > 0:
                page.locator(sel).first.fill(auth.password or "")
                break
        except Exception:
            continue

    for sel in submit_selectors:
        try:
            if page.locator(sel).count() > 0:
                page.locator(sel).first.click()
                try:
                    page.wait_for_load_state("networkidle", timeout=15000)
                except Exception:
                    pass
                page.wait_for_timeout(int(wait_time * 1000))
                return
        except Exception:
            continue


def _collect_href_links(page, base_origin: str) -> list[str]:
    """Collect internal href links from current page."""
    try:
        hrefs = page.eval_on_selector_all(
            "a[href]",
            "els => els.map(e => e.href)",
        )
    except Exception:
        return []

    base_host = urlparse(base_origin).netloc
    result = []
    for href in hrefs:
        if not href:
            continue
        parsed = urlparse(href)
        if parsed.netloc and parsed.netloc != base_host:
            continue
        if href.startswith("javascript:") or href.startswith("#"):
            continue
        if parsed.scheme not in ("", "http", "https"):
            continue
        clean = urljoin(base_origin, href).split("#")[0]
        if clean not in result:
            result.append(clean)
    return result


def _click_menu_items(page, base_origin: str, max_clicks: int, wait_time: float, visited: set) -> None:
    """Click on sidebar/menu items to navigate SPAs."""
    menu_selectors = [
        'nav a', 'nav button', 'aside a', 'aside button',
        '[role="navigation"] a', '[role="navigation"] button',
        '[class*="sidebar" i] a', '[class*="sidebar" i] button',
        '[class*="menu" i] a', '[class*="menu" i] button',
        '[class*="nav" i] a', '[class*="nav" i] button',
        'li[role="menuitem"]',
    ]

    clicked = 0
    for sel in menu_selectors:
        if clicked >= max_clicks:
            break
        try:
            count = page.locator(sel).count()
        except Exception:
            continue

        for i in range(min(count, max_clicks - clicked)):
            try:
                element = page.locator(sel).nth(i)
                # Check if visible and enabled
                if not element.is_visible(timeout=500):
                    continue
                before = page.url
                element.click(timeout=2000)
                try:
                    page.wait_for_load_state("networkidle", timeout=3000)
                except Exception:
                    pass
                page.wait_for_timeout(int(wait_time * 500))
                clicked += 1
                visited.add(page.url)
            except Exception:
                continue
