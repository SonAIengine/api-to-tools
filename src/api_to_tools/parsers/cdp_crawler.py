"""Chrome DevTools Protocol crawler — Playwright-free dynamic discovery.

Drives a real headless Chrome instance via CDP JSON-RPC over WebSocket,
without depending on the Playwright SDK or its bundled Chromium download.

Requirements:
- System Chrome / Chromium / Edge (auto-detected)
- `websockets` Python package (lightweight, ~100KB)

How it works:
1. Login via httpx → harvest cookies
2. Spawn `chrome --headless --remote-debugging-port=...`
3. WebSocket connect to the first page target
4. `Network.setCookie` to inject login state
5. `Page.navigate` through routes → capture every `Network.requestWillBeSent`
6. Convert captured requests to Tool definitions
"""

from __future__ import annotations

import asyncio
import json
import re
import shutil
import subprocess
import time
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlparse

import httpx

from api_to_tools._logging import get_logger
from api_to_tools.parsers._browser_utils import is_mutation_request
from api_to_tools.parsers._param_builder import (
    extract_tag_from_path,
    infer_json_type,
    is_api_url,
    normalize_path_params,
    sanitize_name,
)
from api_to_tools.types import AuthConfig, Tool, ToolParameter

log = get_logger("cdp_crawler")


# ──────────────────────────────────────────────
# Chrome binary detection
# ──────────────────────────────────────────────

CHROME_PATHS = [
    # macOS
    "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
    "/Applications/Chromium.app/Contents/MacOS/Chromium",
    "/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge",
    # Linux
    "/usr/bin/google-chrome",
    "/usr/bin/chromium",
    "/usr/bin/chromium-browser",
    "/usr/bin/microsoft-edge",
    # Windows (WSL)
    "/mnt/c/Program Files/Google/Chrome/Application/chrome.exe",
]


def find_chrome() -> str | None:
    """Locate a usable Chrome/Chromium/Edge binary."""
    for path in CHROME_PATHS:
        if Path(path).exists():
            return path
    for name in ("google-chrome", "chromium", "chromium-browser", "chrome", "microsoft-edge"):
        found = shutil.which(name)
        if found:
            return found
    return None


# ──────────────────────────────────────────────
# CDP client (minimal)
# ──────────────────────────────────────────────

class CDPSession:
    """A tiny CDP JSON-RPC client over a single WebSocket."""

    def __init__(self, ws):
        self._ws = ws
        self._next_id = 0
        self._pending: dict[int, asyncio.Future] = {}
        self._listeners: list = []
        self._reader_task: asyncio.Task | None = None

    @classmethod
    async def connect(cls, ws_url: str):
        import websockets  # type: ignore
        ws = await websockets.connect(ws_url, max_size=20_000_000, max_queue=2**16)
        sess = cls(ws)
        sess._reader_task = asyncio.create_task(sess._reader())
        return sess

    async def _reader(self):
        try:
            async for raw in self._ws:
                try:
                    data = json.loads(raw)
                except (json.JSONDecodeError, TypeError):
                    continue
                mid = data.get("id")
                if mid is not None and mid in self._pending:
                    fut = self._pending.pop(mid)
                    if not fut.done():
                        fut.set_result(data)
                else:
                    for cb in self._listeners:
                        try:
                            cb(data)
                        except Exception:
                            pass
        except Exception as e:
            log.debug("CDP reader stopped: %s", e)

    def on_event(self, callback) -> None:
        self._listeners.append(callback)

    async def send(self, method: str, params: dict | None = None) -> dict:
        self._next_id += 1
        mid = self._next_id
        fut = asyncio.get_event_loop().create_future()
        self._pending[mid] = fut
        await self._ws.send(json.dumps({"id": mid, "method": method, "params": params or {}}))
        try:
            return await asyncio.wait_for(fut, timeout=15)
        except asyncio.TimeoutError:
            self._pending.pop(mid, None)
            return {}

    async def close(self):
        if self._reader_task:
            self._reader_task.cancel()
        try:
            await self._ws.close()
        except Exception:
            pass


# ──────────────────────────────────────────────
# Login helper
# ──────────────────────────────────────────────

def _login_and_get_cookies(url: str, auth: AuthConfig) -> list[dict]:
    """Reuse swagger_discovery's _try_login to obtain a session, then return cookies."""
    from api_to_tools.detector.swagger_discovery import _try_login

    parsed = urlparse(url)
    domain = parsed.netloc

    with httpx.Client(verify=False, follow_redirects=True, timeout=15) as client:
        _try_login(client, url, auth)
        cookies = []
        for k, v in client.cookies.items():
            cookies.append({
                "name": k,
                "value": v,
                "domain": domain,
                "path": "/",
                "secure": parsed.scheme == "https",
            })
        return cookies


# ──────────────────────────────────────────────
# Captured request → Tool
# ──────────────────────────────────────────────

def _request_to_tool(req: dict, seen: set) -> Tool | None:
    request = req.get("request", {})
    url = request.get("url", "")
    method = request.get("method", "GET")
    if not is_api_url(url):
        return None

    parsed = urlparse(url)
    path = parsed.path.rstrip("/") or "/"
    normalized = normalize_path_params(path)
    key = (method, f"{parsed.netloc}{normalized}")
    if key in seen:
        return None
    seen.add(key)

    parameters: list[ToolParameter] = []

    # Path params
    for m in re.finditer(r'\{(\w+)\}', normalized):
        parameters.append(ToolParameter(
            name=m.group(1), type="string", required=True, location="path",
        ))

    # Query params
    if parsed.query:
        for name in parse_qs(parsed.query):
            parameters.append(ToolParameter(
                name=name, type="string", required=False, location="query",
            ))

    # Body params from POST data
    post_data = request.get("postData") or ""
    if post_data and method in ("POST", "PUT", "PATCH"):
        try:
            body_json = json.loads(post_data)
            if isinstance(body_json, dict):
                for name, value in body_json.items():
                    parameters.append(ToolParameter(
                        name=name,
                        type=infer_json_type(value),
                        required=False,
                        location="body",
                    ))
        except (json.JSONDecodeError, TypeError):
            pass

    segs = [s for s in normalized.split("/") if s and s not in ("api", "bo", "v1", "v2", "v3")]
    name_seed = segs[-1] if segs else "request"
    name = sanitize_name(f"{method.lower()}_{name_seed}")

    endpoint = f"{parsed.scheme}://{parsed.netloc}{normalized}"
    is_destructive = is_mutation_request(method, url)
    description = f"{method} {normalized}"
    if is_destructive:
        description = f"[DESTRUCTIVE] {description}"

    return Tool(
        name=name,
        description=description,
        parameters=parameters,
        endpoint=endpoint,
        method=method,
        protocol="rest",
        response_format="json",
        tags=[extract_tag_from_path(normalized)],
        metadata={
            "source": "cdp_crawler",
            "raw_url": url,
            "destructive": is_destructive,
        },
    )


# ──────────────────────────────────────────────
# Async CDP crawl
# ──────────────────────────────────────────────

async def _crawl_with_cdp(
    url: str,
    auth: AuthConfig | None,
    max_pages: int,
    wait_time: float,
    timeout: float,
    chrome_binary: str,
    debug_port: int = 9223,
) -> list[dict]:
    """Run a single CDP crawl and return the captured request payloads."""
    parsed = urlparse(url)
    profile_dir = Path("/tmp") / f"a2t-cdp-{int(time.time())}"
    profile_dir.mkdir(parents=True, exist_ok=True)

    proc = subprocess.Popen(
        [
            chrome_binary,
            "--headless=new",
            "--disable-gpu",
            "--no-sandbox",
            "--disable-dev-shm-usage",
            f"--remote-debugging-port={debug_port}",
            f"--user-data-dir={profile_dir}",
            "--no-first-run",
            "--no-default-browser-check",
            "about:blank",
        ],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )

    captured_requests: list = []
    captured_responses: dict = {}
    menu_routes: set = set()

    try:
        # Wait for Chrome to expose CDP
        ws_url = None
        for _ in range(20):
            await asyncio.sleep(0.5)
            try:
                targets = httpx.get(f"http://localhost:{debug_port}/json", timeout=2).json()
                page = next((t for t in targets if t["type"] == "page"), None)
                if page:
                    ws_url = page["webSocketDebuggerUrl"]
                    break
            except Exception:
                continue

        if not ws_url:
            log.warning("CDP did not become ready")
            return []

        sess = await CDPSession.connect(ws_url)

        def _on_event(data: dict):
            method = data.get("method", "")
            params = data.get("params", {})
            if method == "Network.requestWillBeSent":
                captured_requests.append(params)
            elif method == "Network.responseReceived":
                # Track response so we can fetch body for menu APIs
                resp = params.get("response", {})
                req_id = params.get("requestId")
                if req_id and "/menu" in resp.get("url", "").lower():
                    captured_responses[req_id] = resp

        sess.on_event(_on_event)

        await sess.send("Network.enable")
        await sess.send("Page.enable")

        # Inject login cookies
        if auth and auth.username and auth.password:
            cookies = _login_and_get_cookies(url, auth)
            for c in cookies:
                await sess.send("Network.setCookie", c)
            log.info("Injected %d cookies", len(cookies))

        # Initial navigation
        await sess.send("Page.navigate", {"url": url})
        await asyncio.sleep(wait_time + 2)

        # Try to extract menu routes from response bodies
        for req_id in list(captured_responses.keys()):
            try:
                body_resp = await sess.send(
                    "Network.getResponseBody", {"requestId": req_id}
                )
                body_text = body_resp.get("result", {}).get("body", "")
                if body_text:
                    try:
                        data = json.loads(body_text)
                        _extract_menu_routes(data, menu_routes)
                    except (json.JSONDecodeError, TypeError):
                        pass
            except Exception:
                continue

        log.info("Discovered %d menu routes", len(menu_routes))

        # Navigate to each route
        origin = f"{parsed.scheme}://{parsed.netloc}"
        visited = 0
        for route in list(menu_routes):
            if visited >= max_pages:
                break
            target = route if route.startswith("http") else f"{origin}/{route.lstrip('/')}"
            try:
                await sess.send("Page.navigate", {"url": target})
                await asyncio.sleep(wait_time)
                visited += 1
            except Exception:
                continue

        await sess.close()
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()
        # Cleanup profile
        try:
            import shutil as sh
            sh.rmtree(profile_dir, ignore_errors=True)
        except Exception:
            pass

    return captured_requests


def _extract_menu_routes(obj: Any, routes: set) -> None:
    """Recursively scan JSON for menu URL fields."""
    url_keys = {"url", "path", "route", "menuurl", "callurl",
                "href", "to", "pageroute", "menupath"}
    if isinstance(obj, dict):
        for k, v in obj.items():
            if k.lower() in url_keys and isinstance(v, str) and v:
                if v.startswith("javascript:") or v == "#":
                    continue
                routes.add(v)
            elif isinstance(v, (dict, list)):
                _extract_menu_routes(v, routes)
    elif isinstance(obj, list):
        for item in obj:
            _extract_menu_routes(item, routes)


# ──────────────────────────────────────────────
# Public entrypoint
# ──────────────────────────────────────────────

def crawl_with_cdp(
    url: str,
    *,
    auth: AuthConfig | None = None,
    max_pages: int = 30,
    wait_time: float = 2.5,
    timeout: float = 30.0,
    chrome_binary: str | None = None,
) -> list[Tool]:
    """Discover APIs by driving headless Chrome via CDP — no Playwright SDK."""
    binary = chrome_binary or find_chrome()
    if not binary:
        raise RuntimeError(
            "No Chrome/Chromium/Edge binary found. Install one or pass chrome_binary."
        )
    log.info("Using Chrome binary: %s", binary)

    try:
        import websockets  # noqa: F401
    except ImportError as e:
        raise ImportError(
            "websockets is required for CDP crawler. Install with: pip install websockets"
        ) from e

    captured = asyncio.run(
        _crawl_with_cdp(url, auth, max_pages, wait_time, timeout, binary)
    )
    log.info("Captured %d total requests", len(captured))

    seen: set = set()
    tools: list[Tool] = []
    for req in captured:
        tool = _request_to_tool(req, seen)
        if tool:
            tools.append(tool)
    return tools
