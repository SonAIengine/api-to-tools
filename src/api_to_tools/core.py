"""Core functions."""

from __future__ import annotations

from api_to_tools.types import Tool, AuthConfig, DetectionResult, ExecutionResult
from api_to_tools.detector import detect
from api_to_tools.parsers import get_parser
from api_to_tools.executors import get_executor


def discover(url: str, *, auth: AuthConfig | None = None, **kwargs) -> list[Tool]:
    """Discover and parse API spec from a URL into tools.

    Args:
        url: API spec URL or website URL
        auth: Authentication config for accessing protected APIs

    Examples:
        # Public API
        tools = discover("https://date.nager.at/openapi/v3.json")

        # Basic Auth protected Swagger
        tools = discover("https://internal.example.com/swagger.json",
                         auth=AuthConfig(type="basic", username="admin", password="secret"))

        # Bearer token
        tools = discover("https://api.example.com",
                         auth=AuthConfig(type="bearer", token="eyJ..."))

        # Login form → discover all APIs
        tools = discover("https://app.example.com",
                         auth=AuthConfig(type="cookie", login_url="https://app.example.com/login",
                                         username="user@email.com", password="pass"))
    """
    detect_kwargs = {k: kwargs.pop(k) for k in list(kwargs) if k in ("timeout", "probe_paths", "scan_js", "crawl")}
    # Pass crawler-specific options through to to_tools via kwargs
    crawl_kwargs = {k: kwargs.pop(k) for k in list(kwargs) if k in ("max_pages", "headless", "wait_time", "backend", "safe_mode")}
    detection = detect(url, auth=auth, **detect_kwargs)
    return to_tools(detection, auth=auth, **{**kwargs, **crawl_kwargs})


def to_tools(detection: DetectionResult, *, auth: AuthConfig | None = None, **kwargs) -> list[Tool]:
    """Parse a detected spec into tools."""
    parser = get_parser(detection.type)

    # Crawler: actual browser-based discovery
    if detection.type == "crawler":
        crawler_kwargs = {k: kwargs.pop(k) for k in list(kwargs)
                          if k in ("max_pages", "headless", "wait_time", "timeout", "backend", "safe_mode")}
        tools = parser(detection.spec_url, auth=auth, **crawler_kwargs)
    # jsbundle parser has its own fetch logic and needs auth
    elif detection.type == "jsbundle":
        tools = parser(detection.spec_url, auth=auth)
    # WSDL/GraphQL need the URL, not raw content (libraries fetch themselves)
    elif detection.type in ("wsdl", "graphql"):
        input_data = detection.spec_url
        tools = parser(input_data, source_url=detection.spec_url)
    else:
        input_data = detection.raw_content or detection.spec_url
        tools = parser(input_data, source_url=detection.spec_url)

    # Store auth in tool metadata for execution
    if auth:
        from dataclasses import asdict
        auth_dict = asdict(auth)
        for t in tools:
            t.metadata["auth"] = auth_dict

    # Apply base URL override
    base_url = kwargs.get("base_url")
    if base_url:
        import re
        for t in tools:
            t.endpoint = re.sub(r"^https?://[^/]+", base_url, t.endpoint)

    # Filters
    tags = kwargs.get("tags")
    if tags:
        tools = [t for t in tools if any(tag in t.tags for tag in tags)]

    methods = kwargs.get("methods")
    if methods:
        upper = [m.upper() for m in methods]
        tools = [t for t in tools if t.method.upper() in upper]

    path_filter = kwargs.get("path_filter")
    if path_filter:
        import re
        tools = [t for t in tools if re.search(path_filter, t.endpoint)]

    return tools


def execute(tool: Tool, args: dict, *, auth: AuthConfig | None = None) -> ExecutionResult:
    """Execute a tool with given arguments.

    Auth is resolved in this order:
    1. Explicit `auth` parameter
    2. Auth stored in tool.metadata from discover()
    3. No auth
    """
    # Resolve auth from tool metadata if not explicitly provided
    if not auth and "auth" in tool.metadata:
        auth = AuthConfig(**tool.metadata["auth"])

    executor = get_executor(tool.protocol)
    return executor(tool, args, auth=auth)
