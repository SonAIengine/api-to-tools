"""Async protocol executor for WebSocket and SSE connections.

Handles Tools with protocol="async" (from AsyncAPI specs).
Supports:
- WebSocket: connect, send JSON message, receive response
- SSE (Server-Sent Events): connect, stream events
"""

from __future__ import annotations

import asyncio
import json

from api_to_tools._logging import get_logger
from api_to_tools.constants import DEFAULT_EXECUTOR_TIMEOUT
from api_to_tools.types import AuthConfig, ExecutionResult, Tool

log = get_logger("async_exec")


def _normalize_ws_url(url: str) -> str:
    """Convert http(s) URLs to ws(s) for WebSocket connections."""
    if url.startswith("http://"):
        return "ws://" + url[7:]
    if url.startswith("https://"):
        return "wss://" + url[8:]
    return url


async def _execute_websocket(
    tool: Tool,
    args: dict,
    *,
    auth: AuthConfig | None = None,
    timeout: float = DEFAULT_EXECUTOR_TIMEOUT,
    wait_response: bool = True,
) -> ExecutionResult:
    """Execute a WebSocket send/receive cycle."""
    try:
        import websockets
    except ImportError:
        return ExecutionResult(
            status=500,
            data={"error": "websockets package required: pip install websockets"},
        )

    url = _normalize_ws_url(tool.endpoint)
    headers = {}
    if auth:
        from api_to_tools.auth import build_auth_headers
        headers = build_auth_headers(auth)

    method = tool.method.upper()
    message = json.dumps(args) if args else None

    try:
        async with websockets.connect(url, additional_headers=headers or None) as ws:
            if method == "PUBLISH" and message:
                await ws.send(message)
                log.info("Sent to %s: %s", url, message[:100])

                if wait_response:
                    try:
                        response = await asyncio.wait_for(ws.recv(), timeout=timeout)
                        try:
                            data = json.loads(response)
                        except (json.JSONDecodeError, ValueError):
                            data = response
                        return ExecutionResult(status=200, data=data, raw=str(response))
                    except asyncio.TimeoutError:
                        return ExecutionResult(
                            status=200,
                            data={"status": "sent", "note": "No response within timeout"},
                        )
                else:
                    return ExecutionResult(status=200, data={"status": "sent"})

            elif method == "SUBSCRIBE":
                messages = []
                try:
                    async for msg in ws:
                        try:
                            messages.append(json.loads(msg))
                        except (json.JSONDecodeError, ValueError):
                            messages.append(msg)
                        if len(messages) >= 10:
                            break
                except asyncio.TimeoutError:
                    pass

                return ExecutionResult(
                    status=200,
                    data=messages,
                    raw=json.dumps(messages, default=str),
                )

            else:
                return ExecutionResult(
                    status=400,
                    data={"error": f"Unsupported async method: {method}"},
                )

    except Exception as e:
        log.error("WebSocket error for %s: %s", url, e)
        return ExecutionResult(
            status=500,
            data={"error": str(e), "type": type(e).__name__},
        )


async def _execute_sse(
    tool: Tool,
    args: dict,
    *,
    auth: AuthConfig | None = None,
    timeout: float = DEFAULT_EXECUTOR_TIMEOUT,
    max_events: int = 10,
) -> ExecutionResult:
    """Execute an SSE (Server-Sent Events) subscription."""
    import httpx

    url = tool.endpoint
    headers = {"Accept": "text/event-stream"}
    if auth:
        from api_to_tools.auth import build_auth_headers
        headers.update(build_auth_headers(auth))

    verify = auth.verify_ssl if auth else True
    events: list[dict] = []

    try:
        async with httpx.AsyncClient(verify=verify) as client:
            async with client.stream("GET", url, headers=headers, params=args or None,
                                     timeout=timeout) as response:
                async for line in response.aiter_lines():
                    if line.startswith("data:"):
                        data_str = line[5:].strip()
                        try:
                            events.append(json.loads(data_str))
                        except (json.JSONDecodeError, ValueError):
                            events.append({"raw": data_str})
                        if len(events) >= max_events:
                            break

        return ExecutionResult(
            status=200,
            data=events,
            raw=json.dumps(events, default=str),
        )

    except Exception as e:
        log.error("SSE error for %s: %s", url, e)
        return ExecutionResult(
            status=500,
            data={"error": str(e), "type": type(e).__name__},
        )


def execute_async(tool: Tool, args: dict, *, auth: AuthConfig | None = None) -> ExecutionResult:
    """Execute an async protocol tool (WebSocket or SSE).

    Determines the transport from the endpoint URL scheme:
    - ws://, wss://, mqtt:// → WebSocket
    - http://, https:// with SSE content type → SSE
    - Default → WebSocket
    """
    url = tool.endpoint.lower()

    if any(url.startswith(s) for s in ("http://", "https://")) and "sse" in tool.metadata.get("source", ""):
        coro = _execute_sse(tool, args, auth=auth)
    else:
        coro = _execute_websocket(tool, args, auth=auth)

    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        loop = None

    if loop and loop.is_running():
        import concurrent.futures
        with concurrent.futures.ThreadPoolExecutor() as pool:
            return pool.submit(asyncio.run, coro).result()
    else:
        return asyncio.run(coro)
