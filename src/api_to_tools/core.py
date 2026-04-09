"""Core functions."""

from __future__ import annotations

from api_to_tools.types import Tool, DetectionResult, ExecutionResult
from api_to_tools.detector import detect
from api_to_tools.parsers import get_parser
from api_to_tools.executors import get_executor


def discover(url: str, **kwargs) -> list[Tool]:
    """Discover and parse API spec from a URL into tools.

    >>> tools = discover("https://date.nager.at/openapi/v3.json")
    >>> tools = discover("https://petstore.swagger.io")  # auto-detects
    """
    # Separate detect options from filter options
    detect_kwargs = {k: kwargs[k] for k in ("timeout", "probe_paths") if k in kwargs}
    detection = detect(url, **detect_kwargs)
    return to_tools(detection, **kwargs)


def to_tools(detection: DetectionResult, **kwargs) -> list[Tool]:
    """Parse a detected spec into tools."""
    parser = get_parser(detection.type)
    # WSDL/GraphQL need the URL, not raw content (libraries fetch themselves)
    if detection.type in ("wsdl", "graphql"):
        input_data = detection.spec_url
    else:
        input_data = detection.raw_content or detection.spec_url
    tools = parser(input_data, source_url=detection.spec_url)

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


def execute(tool: Tool, args: dict) -> ExecutionResult:
    """Execute a tool with given arguments.

    >>> tools = discover("https://date.nager.at/openapi/v3.json")
    >>> result = execute(tools[0], {"countryCode": "KR"})
    """
    executor = get_executor(tool.protocol)
    return executor(tool, args)
