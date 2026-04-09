"""Static SPA analyzer — discovers APIs without running a browser.

Strategy:
1. Fetch the main HTML page (with auth if needed)
2. Collect every JS chunk URL:
   - <script src> in HTML
   - Next.js `_buildManifest.js` (all route chunks)
   - <link rel="preload" as="script"> preload hints
3. Download every chunk in parallel
4. Scan each chunk with a context-aware regex pipeline:
   - Find API path string literals (and template literals)
   - Walk backwards to detect HTTP method hints ('.get(', '.post(', fetch(…,{method:})
   - Walk forward to detect body parameter objects
5. Normalize, deduplicate, build Tool definitions

No browser, no JS execution. Handles minified ES2020+ bundles that break
classic JS parsers.
"""

from __future__ import annotations

import asyncio
import re
from typing import Iterable
from urllib.parse import urljoin, urlparse

import httpx

from api_to_tools._logging import get_logger
from api_to_tools.constants import API_PATH_MARKERS
from api_to_tools.parsers._param_builder import (
    extract_tag_from_path,
    sanitize_name,
)
from api_to_tools.types import AuthConfig, Tool, ToolParameter

log = get_logger("static_spa")


# ──────────────────────────────────────────────
# 1. Chunk URL collection
# ──────────────────────────────────────────────

_SCRIPT_SRC_RE = re.compile(r'<script[^>]+src=["\']([^"\']+\.js)["\']', re.I)
_PRELOAD_RE = re.compile(
    r'<link[^>]+(?:rel=["\'](?:modulepreload|preload)["\'])[^>]*href=["\']([^"\']+\.js)["\']',
    re.I,
)
_NEXT_BUILD_ID_RE = re.compile(r'/_next/static/([^/"\']+)/')
_NEXT_CHUNK_RE = re.compile(r'/_next/static/chunks/[^"\'`\s<>]+\.js')


def _normalize_url(href: str, origin: str, base: str) -> str:
    if href.startswith("//"):
        scheme = urlparse(base).scheme
        return f"{scheme}:{href}"
    if href.startswith("http"):
        return href
    if href.startswith("/"):
        return f"{origin}{href}"
    return urljoin(base, href)


def _collect_chunks_from_html(html: str, base_url: str) -> set[str]:
    parsed = urlparse(base_url)
    origin = f"{parsed.scheme}://{parsed.netloc}"
    chunks: set[str] = set()

    for pattern in (_SCRIPT_SRC_RE, _PRELOAD_RE):
        for match in pattern.finditer(html):
            chunks.add(_normalize_url(match.group(1), origin, base_url))

    # Any stray /_next/static/chunks/... paths in the HTML body
    for m in _NEXT_CHUNK_RE.finditer(html):
        chunks.add(_normalize_url(m.group(0), origin, base_url))

    return chunks


def _find_next_build_id(html: str) -> str | None:
    for m in _NEXT_BUILD_ID_RE.finditer(html):
        bid = m.group(1)
        if bid not in ("chunks", "css", "media"):
            return bid
    return None


def _collect_chunks_from_next_manifest(
    client: httpx.Client,
    origin: str,
    build_id: str,
    timeout: float,
) -> set[str]:
    """Fetch Next.js _buildManifest.js and harvest every chunk path it mentions."""
    chunks: set[str] = set()
    for candidate in (
        f"{origin}/_next/static/{build_id}/_buildManifest.js",
        f"{origin}/_next/static/{build_id}/_ssgManifest.js",
    ):
        try:
            res = client.get(candidate, timeout=timeout, follow_redirects=True)
            if res.status_code != 200:
                continue
            content = res.text
            for m in re.finditer(r'["\']([^"\']*static/chunks/[^"\']+\.js)["\']', content):
                path = m.group(1)
                if not path.startswith("/"):
                    path = "/_next/" + path.lstrip("/")
                chunks.add(f"{origin}{path}")
        except httpx.HTTPError:
            continue
    log.debug("Next.js manifest yielded %d chunks", len(chunks))
    return chunks


def collect_all_chunks(
    html: str,
    base_url: str,
    client: httpx.Client,
    timeout: float,
) -> list[str]:
    parsed = urlparse(base_url)
    origin = f"{parsed.scheme}://{parsed.netloc}"

    chunks: set[str] = set()
    chunks.update(_collect_chunks_from_html(html, base_url))

    build_id = _find_next_build_id(html)
    if build_id:
        chunks.update(
            _collect_chunks_from_next_manifest(client, origin, build_id, timeout)
        )

    # Final sweep: grep the HTML itself for any .js under /_next/
    return sorted(chunks)


# ──────────────────────────────────────────────
# 2. Parallel chunk download
# ──────────────────────────────────────────────

async def _fetch_one(client: httpx.AsyncClient, url: str, timeout: float) -> tuple[str, str | None]:
    try:
        res = await client.get(url, timeout=timeout, follow_redirects=True)
        if res.status_code == 200:
            return url, res.text
    except httpx.HTTPError:
        pass
    return url, None


async def _fetch_all(urls: list[str], headers: dict[str, str], timeout: float) -> dict[str, str]:
    results: dict[str, str] = {}
    async with httpx.AsyncClient(
        headers=headers,
        verify=False,
        limits=httpx.Limits(max_connections=16, max_keepalive_connections=16),
        follow_redirects=True,
    ) as client:
        tasks = [_fetch_one(client, u, timeout) for u in urls]
        for coro in asyncio.as_completed(tasks):
            url, text = await coro
            if text:
                results[url] = text
    return results


# ──────────────────────────────────────────────
# 3. Context-aware regex scanner (the core)
# ──────────────────────────────────────────────

# Match either a quoted string literal or a template literal containing /api/
# Captures: quote, content
_API_PATH_RE = re.compile(
    r'(["\'`])'
    r'(\/(?:api|v\d+|rest|graphql|rpc)\/[^\1\s\n]{1,300}?)'
    r'\1'
)

# Method-hint lookups (walk BACKWARDS from a URL literal)
_METHOD_BEFORE_RE = re.compile(
    r'\.\s*(get|post|put|patch|delete|head|options|request)\s*\(\s*$',
    re.I,
)
_FETCH_RE = re.compile(r'\b(fetch|request)\s*\(\s*$', re.I)

# Body object after URL (walk FORWARDS to find {…})
_BODY_OBJ_RE = re.compile(r'^\s*,\s*\{([^{}]{0,500})\}')

# Object-key enumerator inside a body literal (axios method: 'POST')
_METHOD_FIELD_RE = re.compile(
    r'["\']?method["\']?\s*:\s*["\']([A-Z]+)["\']',
    re.I,
)

# Key names inside a body object — supports both `{key: val}` and shorthand `{key,}`
_OBJ_KEY_RE = re.compile(
    r'(?:^|,)\s*["\']?([A-Za-z_$][\w$]*)["\']?\s*(?::|(?=\s*[,}]))'
)


def _looks_like_api_path(path: str) -> bool:
    if not path or len(path) < 4:
        return False
    lower = path.lower()
    if any(lower.endswith(ext) for ext in (".js", ".css", ".png", ".svg", ".jpg", ".woff", ".woff2", ".ttf", ".ico")):
        return False
    if "\\n" in path or "\n" in path or " " in path:
        return False
    # must include an API marker or start with /api/
    return any(m in lower for m in API_PATH_MARKERS)


def _normalize_template_expressions(url: str) -> str:
    """Convert `/api/foo/${bar}/baz` → `/api/foo/{bar}/baz`."""
    def _sub(m):
        expr = m.group(1).strip()
        # If expression is a simple identifier, keep its name
        ident_m = re.match(r'^([A-Za-z_$][\w$]*)$', expr)
        if ident_m:
            return "{" + ident_m.group(1) + "}"
        # If it's obj.prop, use prop
        prop_m = re.match(r'^[\w$.]+\.([A-Za-z_$][\w$]*)$', expr)
        if prop_m:
            return "{" + prop_m.group(1) + "}"
        return "{param}"
    return re.sub(r'\$\{([^}]+)\}', _sub, url)


def _walk_back_for_method(js: str, start: int, limit: int = 80) -> tuple[str | None, bool]:
    """Scan leftward from `start` to spot HTTP method hints.

    Returns (method, is_fetch).
    - If `.get(`, `.post(`, ... is found → that method
    - If `fetch(`, `request(` is found → ("GET", True) (may be overridden later)
    """
    window = js[max(0, start - limit):start]
    # strip trailing whitespace/newlines
    m = _METHOD_BEFORE_RE.search(window)
    if m:
        return m.group(1).upper(), False
    m = _FETCH_RE.search(window)
    if m:
        return "GET", True
    return None, False


def _walk_forward_for_body(js: str, end: int, limit: int = 500) -> tuple[str | None, list[str]]:
    """After a URL literal, try to find the config/body object.

    Returns (method_override, body_param_names).
    """
    window = js[end:end + limit]
    m = _BODY_OBJ_RE.match(window)
    if not m:
        return None, []
    body = m.group(1)
    method_override = None
    mm = _METHOD_FIELD_RE.search(body)
    if mm:
        method_override = mm.group(1).upper()
    keys = _OBJ_KEY_RE.findall(body)
    # filter reserved config keys
    reserved = {"method", "headers", "params", "data", "body", "timeout", "withCredentials", "responseType"}
    body_keys = [k for k in keys if k not in reserved]
    return method_override, body_keys


def extract_api_calls_from_js(js_source: str) -> list[dict]:
    """Scan a JS source blob for API call sites without parsing.

    Returns a list of {method, url, body_params} dicts.
    """
    found: list[dict] = []

    for match in _API_PATH_RE.finditer(js_source):
        raw_path = match.group(2)
        path = _normalize_template_expressions(raw_path)

        if not _looks_like_api_path(path):
            continue

        # Find method: walk back to look for .get( / .post( / fetch(
        method, is_fetch = _walk_back_for_method(js_source, match.start(), limit=80)

        # Walk forward for body object + potential method override
        method_override, body_params = _walk_forward_for_body(
            js_source, match.end(), limit=600
        )
        if method_override:
            method = method_override

        if not method:
            # Keep fetch with GET default; otherwise infer from path name
            method = _infer_method_from_path(path)

        found.append({
            "method": method,
            "url": path,
            "body_params": body_params,
        })

    return found


def _infer_method_from_path(path: str) -> str:
    last = path.rstrip("/").split("/")[-1].lower()
    last = re.sub(r'\{[^}]+\}', '', last)
    if not last:
        return "GET"
    if any(last.startswith(w) for w in ("get", "find", "list", "search", "query", "check", "fetch", "load", "view", "show", "count")):
        return "GET"
    if any(w in last for w in ("delete", "remove", "destroy")):
        return "DELETE"
    if any(w in last for w in ("update", "modify", "edit", "change")):
        return "PUT"
    if any(w in last for w in ("create", "add", "regist", "save", "upload", "send", "submit")):
        return "POST"
    return "GET"


# ──────────────────────────────────────────────
# 4. Main entry point
# ──────────────────────────────────────────────

def _try_json_login(client: httpx.Client, base_url: str, auth: AuthConfig, timeout: float) -> str | None:
    """Reuse swagger_discovery's login flow to obtain a bearer token."""
    try:
        from api_to_tools.detector.swagger_discovery import _try_login
        return _try_login(client, base_url, auth)
    except Exception as e:
        log.debug("Login failed: %s", e)
        return None


def _collect_route_paths_from_chunks(chunk_sources: dict[str, str]) -> set[str]:
    """Scan chunks for route path strings (e.g. "/admin/users")."""
    routes: set[str] = set()
    # Route paths look like "/admin/..." or "/member/..." — NOT /api/ and NOT static
    route_re = re.compile(r'["\'`](/[a-z][a-z0-9/_-]{3,80})["\'`]')
    skip = {"api", "v1", "v2", "v3", "_next", "static", "chunks"}
    for js in chunk_sources.values():
        for m in route_re.finditer(js):
            path = m.group(1)
            first_seg = path.strip("/").split("/")[0].lower()
            if first_seg in skip:
                continue
            if any(path.endswith(ext) for ext in (".js", ".css", ".png", ".svg", ".json", ".ico")):
                continue
            if "/api/" in path or "/_next/" in path:
                continue
            routes.add(path)
    return routes


def discover_static_spa(
    url: str,
    *,
    auth: AuthConfig | None = None,
    timeout: float = 15.0,
    max_chunks: int = 1000,
    follow_routes: bool = True,
) -> list[Tool]:
    """Discover APIs from a SPA without running a browser.

    Strategy:
    1. Fetch main page → initial chunks
    2. If auth provided: login → get token → re-fetch main page → more chunks
    3. Scan chunks for route paths → fetch each route HTML → even more chunks
    4. Parse every chunk for API call sites
    """
    from api_to_tools.auth import get_authenticated_client

    with get_authenticated_client(auth) as client:
        try:
            res = client.get(url, timeout=timeout, follow_redirects=True)
        except httpx.HTTPError as e:
            log.warning("Failed to fetch %s: %s", url, e)
            return []

        html = res.text
        final_url = str(res.url)
        all_chunks: set[str] = set(collect_all_chunks(html, final_url, client, timeout))

        # If credentials given, try to login and re-fetch the main page
        if auth and auth.username and auth.password:
            token = _try_json_login(client, url, auth, timeout)
            if token:
                log.info("Obtained access token — re-fetching pages with auth")
                client.headers["Authorization"] = f"Bearer {token}"
                try:
                    auth_res = client.get(url, timeout=timeout, follow_redirects=True)
                    all_chunks.update(collect_all_chunks(auth_res.text, str(auth_res.url), client, timeout))
                except httpx.HTTPError:
                    pass

        headers = dict(client.headers)

    log.info("Initial chunk pool: %d", len(all_chunks))

    # Download first batch
    chunks_list = sorted(all_chunks)[:max_chunks]
    chunk_sources = asyncio.run(_fetch_all(chunks_list, headers, timeout))
    log.info("Downloaded %d/%d chunks", len(chunk_sources), len(chunks_list))

    # Route discovery: scan chunks for internal page routes, visit them, collect more chunks
    if follow_routes and auth and auth.username and auth.password:
        routes = _collect_route_paths_from_chunks(chunk_sources)
        log.info("Discovered %d internal routes to visit", len(routes))

        if routes:
            parsed = urlparse(final_url)
            origin = f"{parsed.scheme}://{parsed.netloc}"
            # Visit each route with auth cookies to harvest new chunks
            route_urls = [f"{origin}{r.rstrip('/')}" for r in list(routes)[:50]]

            with get_authenticated_client(auth) as client:
                for rurl in route_urls:
                    try:
                        r = client.get(rurl, timeout=timeout, follow_redirects=True)
                        if r.status_code == 200:
                            new_chunks = collect_all_chunks(r.text, str(r.url), client, timeout)
                            all_chunks.update(new_chunks)
                    except httpx.HTTPError:
                        continue

            new_to_fetch = sorted(all_chunks - set(chunk_sources.keys()))[: max_chunks - len(chunk_sources)]
            if new_to_fetch:
                log.info("Fetching %d additional chunks from routes", len(new_to_fetch))
                extra = asyncio.run(_fetch_all(new_to_fetch, headers, timeout))
                chunk_sources.update(extra)

    log.info("Final chunk pool size: %d (downloaded)", len(chunk_sources))

    all_calls: list[dict] = []
    for chunk_url, source in chunk_sources.items():
        try:
            calls = extract_api_calls_from_js(source)
        except Exception as e:
            log.debug("Scan error on %s: %s", chunk_url, e)
            continue
        for c in calls:
            c["_chunk"] = chunk_url
            all_calls.append(c)

    log.info("Extracted %d raw API call sites", len(all_calls))
    return _calls_to_tools(all_calls, final_url)


# ──────────────────────────────────────────────
# 5. Call records → Tool definitions
# ──────────────────────────────────────────────

def _calls_to_tools(calls: Iterable[dict], source_url: str) -> list[Tool]:
    parsed = urlparse(source_url)
    origin = f"{parsed.scheme}://{parsed.netloc}"

    seen: dict[tuple[str, str], Tool] = {}

    for call in calls:
        method = call["method"]
        url = call["url"]
        body_params = call.get("body_params", [])

        if url.startswith("http"):
            endpoint = url
        elif url.startswith("/"):
            endpoint = f"{origin}{url}"
        else:
            continue

        endpoint = endpoint.rstrip("/")
        key = (method, endpoint)

        if key in seen:
            existing = seen[key]
            existing_names = {p.name for p in existing.parameters if p.location == "body"}
            for name in body_params:
                if name not in existing_names:
                    existing.parameters.append(ToolParameter(
                        name=name, type="string", required=False, location="body",
                    ))
            continue

        path_for_name = urlparse(endpoint).path
        path_params = [
            ToolParameter(name=m.group(1), type="string", required=True, location="path")
            for m in re.finditer(r'\{(\w+)\}', endpoint)
        ]
        body_parameters = [
            ToolParameter(name=n, type="string", required=False, location="body")
            for n in body_params
        ]

        segs = [s for s in path_for_name.split("/") if s and s not in ("api", "v1", "v2", "v3", "bo")]
        name_seed = segs[-1] if segs else "request"
        name_seed = re.sub(r'\{[^}]+\}', '', name_seed) or "request"
        name = sanitize_name(f"{method.lower()}_{name_seed}")

        seen[key] = Tool(
            name=name,
            description=f"{method} {path_for_name}",
            parameters=path_params + body_parameters,
            endpoint=endpoint,
            method=method,
            protocol="rest",
            response_format="json",
            tags=[extract_tag_from_path(path_for_name)],
            metadata={"source": "static_spa", "raw_url": url},
        )

    return list(seen.values())
