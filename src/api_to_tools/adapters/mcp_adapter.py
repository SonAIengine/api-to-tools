"""MCP Server adapter."""

from __future__ import annotations

import json

from mcp.server.fastmcp import FastMCP

from api_to_tools.types import Tool
from api_to_tools.executors import get_executor


def create_mcp_server(tools: list[Tool], name: str = "api-to-tools") -> FastMCP:
    """Create an MCP server from a list of tools."""
    mcp = FastMCP(name)

    for tool in tools:
        # Capture tool in closure
        _register_tool(mcp, tool)

    return mcp


def _register_tool(mcp: FastMCP, tool: Tool):
    """Register a single tool on the MCP server."""

    # Build parameter annotations for FastMCP
    param_descriptions = {p.name: p.description or "" for p in tool.parameters}
    description = tool.description
    if param_descriptions:
        param_lines = [f"  - {k}: {v}" for k, v in param_descriptions.items() if v]
        if param_lines:
            description += "\n\nParameters:\n" + "\n".join(param_lines)

    @mcp.tool(name=tool.name, description=description)
    def _handler(**kwargs) -> str:
        try:
            executor = get_executor(tool.protocol)
            result = executor(tool, kwargs)
            if isinstance(result.data, str):
                return result.data
            return json.dumps(result.data, ensure_ascii=False, indent=2, default=str)
        except Exception as e:
            return f"Error: {e}"
