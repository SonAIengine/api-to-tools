"""Lightweight HTTP traffic capture proxy.

Records API traffic as HAR entries and converts them to Tools
using the existing HAR parser. No external dependencies required.

Usage:
    from api_to_tools.proxy import capture_traffic

    # Start proxy, open browser, record traffic, stop → Tools
    tools = capture_traffic(
        port=8080,
        duration=60,           # record for 60 seconds
        target_host="api.example.com",  # filter by host (optional)
    )

    # Or use as context manager for manual control
    from api_to_tools.proxy import TrafficRecorder

    with TrafficRecorder(port=8080) as recorder:
        # ... use browser with proxy http://localhost:8080 ...
        input("Press Enter when done recording...")

    tools = recorder.to_tools()
"""

from __future__ import annotations

import json
import threading
import time
from http.server import HTTPServer, BaseHTTPRequestHandler
from urllib.parse import urlparse

import httpx

from api_to_tools._logging import get_logger
from api_to_tools.parsers.har import parse_har

log = get_logger("proxy")


class _ProxyHandler(BaseHTTPRequestHandler):
    """Simple HTTP proxy that records requests/responses as HAR entries."""

    # Shared mutable state — set by TrafficRecorder before starting
    entries: list[dict] = []
    entries_lock: threading.Lock = threading.Lock()
    target_hosts: set[str] = set()

    def do_GET(self):
        self._proxy_request("GET")

    def do_POST(self):
        self._proxy_request("POST")

    def do_PUT(self):
        self._proxy_request("PUT")

    def do_PATCH(self):
        self._proxy_request("PATCH")

    def do_DELETE(self):
        self._proxy_request("DELETE")

    def do_HEAD(self):
        self._proxy_request("HEAD")

    def do_OPTIONS(self):
        self._proxy_request("OPTIONS")

    def _proxy_request(self, method: str):
        url = self.path
        if not url.startswith("http"):
            url = f"http://{self.headers.get('Host', 'localhost')}{self.path}"

        parsed = urlparse(url)
        host = parsed.hostname or ""

        # Filter by target host if specified
        if self.target_hosts and host not in self.target_hosts:
            self._forward_without_recording(method, url)
            return

        # Read request body
        content_length = int(self.headers.get("Content-Length", 0))
        request_body = self.rfile.read(content_length) if content_length > 0 else b""

        # Forward request headers (exclude proxy-specific ones)
        forward_headers = {}
        for key, value in self.headers.items():
            if key.lower() not in ("host", "proxy-connection", "proxy-authorization"):
                forward_headers[key] = value

        # Forward the request
        start_time = time.time()
        try:
            response = httpx.request(
                method=method,
                url=url,
                headers=forward_headers,
                content=request_body if request_body else None,
                follow_redirects=False,
                timeout=30.0,
            )

            elapsed_ms = (time.time() - start_time) * 1000

            # Build HAR entry
            entry = self._build_har_entry(
                method=method,
                url=url,
                request_headers=forward_headers,
                request_body=request_body,
                request_content_type=self.headers.get("Content-Type", ""),
                response_status=response.status_code,
                response_headers=dict(response.headers),
                response_body=response.text,
                response_content_type=response.headers.get("content-type", ""),
                elapsed_ms=elapsed_ms,
            )

            with self.entries_lock:
                self.entries.append(entry)

            # Send response back to client
            self.send_response(response.status_code)
            for key, value in response.headers.items():
                if key.lower() not in ("transfer-encoding", "content-encoding", "content-length"):
                    self.send_header(key, value)
            body_bytes = response.content
            self.send_header("Content-Length", str(len(body_bytes)))
            self.end_headers()
            self.wfile.write(body_bytes)

        except Exception as e:
            log.error("Proxy error for %s: %s", url, e)
            self.send_error(502, f"Proxy error: {e}")

    def _forward_without_recording(self, method: str, url: str):
        """Forward request without recording it."""
        content_length = int(self.headers.get("Content-Length", 0))
        body = self.rfile.read(content_length) if content_length > 0 else None
        try:
            response = httpx.request(method=method, url=url, content=body, timeout=30.0)
            self.send_response(response.status_code)
            for key, value in response.headers.items():
                if key.lower() not in ("transfer-encoding", "content-encoding", "content-length"):
                    self.send_header(key, value)
            body_bytes = response.content
            self.send_header("Content-Length", str(len(body_bytes)))
            self.end_headers()
            self.wfile.write(body_bytes)
        except Exception as e:
            self.send_error(502, str(e))

    def _build_har_entry(self, **kwargs) -> dict:
        """Build a HAR 1.2 entry from request/response data."""
        req_headers = [{"name": k, "value": v} for k, v in kwargs["request_headers"].items()]
        resp_headers = [{"name": k, "value": v} for k, v in kwargs["response_headers"].items()]

        request_body = kwargs["request_body"]
        post_data = {}
        if request_body:
            post_data = {
                "mimeType": kwargs["request_content_type"],
                "text": request_body.decode("utf-8", errors="replace"),
            }

        # Parse query string from URL
        parsed = urlparse(kwargs["url"])
        query_string = []
        if parsed.query:
            for pair in parsed.query.split("&"):
                if "=" in pair:
                    k, v = pair.split("=", 1)
                    query_string.append({"name": k, "value": v})

        return {
            "request": {
                "method": kwargs["method"],
                "url": kwargs["url"],
                "headers": req_headers,
                "queryString": query_string,
                **({"postData": post_data} if post_data else {}),
            },
            "response": {
                "status": kwargs["response_status"],
                "headers": resp_headers,
                "content": {
                    "mimeType": kwargs["response_content_type"],
                    "text": kwargs["response_body"],
                },
            },
            "time": kwargs["elapsed_ms"],
        }

    def log_message(self, format, *args):
        """Suppress default logging — use our logger instead."""
        log.debug(format, *args)


class TrafficRecorder:
    """Context manager that runs an HTTP proxy and records traffic.

    Usage:
        with TrafficRecorder(port=8080) as recorder:
            # Configure browser to use http://localhost:8080 as proxy
            # Browse the target site...
            input("Press Enter when done.")

        tools = recorder.to_tools()
        print(f"Discovered {len(tools)} tools")
    """

    def __init__(
        self,
        port: int = 8080,
        target_host: str | None = None,
    ):
        self.port = port
        self.target_hosts = {target_host} if target_host else set()
        self._entries: list[dict] = []
        self._lock = threading.Lock()
        self._server: HTTPServer | None = None
        self._thread: threading.Thread | None = None

    def start(self):
        """Start the proxy server in a background thread."""
        _ProxyHandler.entries = self._entries
        _ProxyHandler.entries_lock = self._lock
        _ProxyHandler.target_hosts = self.target_hosts

        self._server = HTTPServer(("127.0.0.1", self.port), _ProxyHandler)
        self._thread = threading.Thread(target=self._server.serve_forever, daemon=True)
        self._thread.start()
        log.info("Proxy started on http://127.0.0.1:%d", self.port)

    def stop(self):
        """Stop the proxy server."""
        if self._server:
            self._server.shutdown()
            log.info("Proxy stopped. Recorded %d entries.", len(self._entries))

    def __enter__(self):
        self.start()
        return self

    def __exit__(self, *exc):
        self.stop()

    def get_har(self) -> dict:
        """Get recorded traffic as a HAR dict."""
        return {
            "log": {
                "version": "1.2",
                "entries": list(self._entries),
            },
        }

    def to_tools(self) -> list:
        """Convert recorded traffic to Tool definitions."""
        return parse_har(self.get_har())

    def save_har(self, path: str):
        """Save recorded traffic as a HAR file."""
        with open(path, "w") as f:
            json.dump(self.get_har(), f, indent=2, ensure_ascii=False)
        log.info("Saved %d entries to %s", len(self._entries), path)


def capture_traffic(
    *,
    port: int = 8080,
    duration: float = 60.0,
    target_host: str | None = None,
) -> list:
    """Record HTTP traffic for a duration and convert to Tools.

    Starts a proxy server, waits for the specified duration, then
    parses all recorded traffic into Tool definitions.

    Args:
        port: Proxy server port (default 8080).
        duration: Recording duration in seconds.
        target_host: Only record traffic to this host.

    Returns:
        list[Tool]: Tools discovered from recorded traffic.
    """
    with TrafficRecorder(port=port, target_host=target_host) as recorder:
        log.info("Recording traffic for %.0f seconds... (proxy: http://127.0.0.1:%d)", duration, port)
        time.sleep(duration)

    return recorder.to_tools()
