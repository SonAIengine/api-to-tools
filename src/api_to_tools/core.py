"""Core functions: discover, to_tools, execute."""

from __future__ import annotations

import re
from dataclasses import asdict
from typing import Any

from api_to_tools.detector import detect
from api_to_tools.executors import get_executor
from api_to_tools.parsers import get_parser
from api_to_tools.types import AuthConfig, DetectionResult, ExecutionResult, Tool


# Kwargs recognized by each layer, grouped for clean filtering.
_DETECT_KEYS = frozenset({"timeout", "probe_paths", "scan_js", "crawl"})
_CRAWLER_KEYS = frozenset({"max_pages", "headless", "wait_time", "timeout", "backend", "safe_mode"})
_NEXACRO_KEYS = frozenset({"max_pages", "headless", "wait_time", "timeout", "backend"})
_FILTER_KEYS = frozenset({"base_url", "tags", "methods", "path_filter"})


def _split_kwargs(kwargs: dict[str, Any], keys: frozenset[str]) -> tuple[dict, dict]:
    """Split a kwargs dict into (matching, remaining) without mutating input."""
    matching = {k: v for k, v in kwargs.items() if k in keys}
    remaining = {k: v for k, v in kwargs.items() if k not in keys}
    return matching, remaining


def discover(url: str, *, auth: AuthConfig | None = None, **kwargs: Any) -> list[Tool]:
    """Discover and parse API spec from a URL into tools.

    Args:
        url: API spec URL or website URL
        auth: Authentication config for accessing protected APIs

    Keyword arguments (forwarded downstream):
        timeout, probe_paths, scan_js, crawl: detector options
        max_pages, headless, wait_time, backend, safe_mode: crawler options
        base_url, tags, methods, path_filter: result filters

    Examples:
        tools = discover("https://date.nager.at/openapi/v3.json")
        tools = discover("https://internal.example.com/swagger.json",
                         auth=AuthConfig(type="basic", username="admin", password="secret"))
        tools = discover("https://admin.example.com/",
                         auth=AuthConfig(type="cookie", username="admin", password="admin"))
    """
    detect_kw, remaining = _split_kwargs(kwargs, _DETECT_KEYS)
    detection = detect(url, auth=auth, **detect_kw)
    return to_tools(detection, auth=auth, **remaining)


def to_tools(
    detection: DetectionResult,
    *,
    auth: AuthConfig | None = None,
    **kwargs: Any,
) -> list[Tool]:
    """Parse a detected spec into tools."""
    parser = get_parser(detection.type)
    tools = _run_parser(parser, detection, auth, kwargs)

    # Store auth in tool metadata so execute() can use it later
    if auth:
        auth_dict = asdict(auth)
        for t in tools:
            t.metadata["auth"] = auth_dict

    return _apply_filters(tools, kwargs)


def _run_parser(
    parser: Any,
    detection: DetectionResult,
    auth: AuthConfig | None,
    kwargs: dict[str, Any],
) -> list[Tool]:
    """Dispatch parsing to the right parser with appropriate kwargs."""
    spec_type = detection.type

    if spec_type == "crawler":
        crawler_kw, _ = _split_kwargs(kwargs, _CRAWLER_KEYS)
        return parser(detection.spec_url, auth=auth, **crawler_kw)

    if spec_type == "nexacro":
        nexacro_kw, _ = _split_kwargs(kwargs, _NEXACRO_KEYS)
        return parser(detection.spec_url, auth=auth, **nexacro_kw)

    if spec_type == "jsbundle":
        return parser(detection.spec_url, auth=auth)

    if spec_type == "static_spa":
        return parser(detection.spec_url, auth=auth)

    if spec_type in ("wsdl", "graphql"):
        return parser(detection.spec_url, source_url=detection.spec_url)

    # Default (OpenAPI etc.): prefer raw content if detector already fetched it
    input_data = detection.raw_content or detection.spec_url
    return parser(input_data, source_url=detection.spec_url)


def _apply_filters(tools: list[Tool], kwargs: dict[str, Any]) -> list[Tool]:
    """Apply base_url override and result filters from kwargs."""
    base_url = kwargs.get("base_url")
    if base_url:
        for t in tools:
            t.endpoint = re.sub(r"^https?://[^/]+", base_url, t.endpoint)

    tags = kwargs.get("tags")
    if tags:
        tools = [t for t in tools if any(tag in t.tags for tag in tags)]

    methods = kwargs.get("methods")
    if methods:
        upper = {m.upper() for m in methods}
        tools = [t for t in tools if t.method.upper() in upper]

    path_filter = kwargs.get("path_filter")
    if path_filter:
        tools = [t for t in tools if re.search(path_filter, t.endpoint)]

    return tools


def execute(
    tool: Tool,
    args: dict,
    *,
    auth: AuthConfig | None = None,
) -> ExecutionResult:
    """Execute a tool with given arguments.

    Auth is resolved in this order:
        1. Explicit `auth` parameter
        2. Auth stored in tool.metadata from discover()
        3. No auth
    """
    if not auth and "auth" in tool.metadata:
        auth = AuthConfig(**tool.metadata["auth"])

    executor = get_executor(tool.protocol)
    try:
        return executor(tool, args, auth=auth)
    except Exception as e:
        return ExecutionResult(
            status=500,
            data={"error": str(e), "type": type(e).__name__},
            raw=None,
        )
