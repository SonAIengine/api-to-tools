"""MCP Server adapter."""

from __future__ import annotations

import json

from mcp.server.fastmcp import FastMCP

from api_to_tools.adapters.formats import _to_json_schema_type
from api_to_tools.types import Tool


def _build_input_schema(tool: Tool) -> dict:
    """Build a JSON Schema for the tool's input parameters."""
    properties = {}
    required = []
    for p in tool.parameters:
        prop = _to_json_schema_type(p.type)
        if p.description:
            prop["description"] = p.description
        if p.enum:
            prop["enum"] = p.enum
        properties[p.name] = prop
        if p.required:
            required.append(p.name)

    schema: dict = {"type": "object", "properties": properties}
    if required:
        schema["required"] = required
    return schema


def create_mcp_server(tools: list[Tool], name: str = "api-to-tools") -> FastMCP:
    """Create an MCP server from a list of tools."""
    mcp = FastMCP(name)

    for tool in tools:
        _register_tool(mcp, tool)

    return mcp


def _register_tool(mcp: FastMCP, tool: Tool):
    """Register a single tool on the MCP server with full parameter schema."""
    input_schema = _build_input_schema(tool)

    # Use low-level _tool_manager to pass inputSchema directly if available,
    # otherwise fall back to @mcp.tool() decorator with schema in description.
    try:
        from mcp.types import Tool as McpTool

        async def _handler_async(**kwargs) -> str:
            from api_to_tools.core import execute
            result = execute(tool, kwargs)
            if isinstance(result.data, str):
                return result.data
            return json.dumps(result.data, ensure_ascii=False, indent=2, default=str)

        mcp_tool = McpTool(
            name=tool.name,
            description=tool.description,
            inputSchema=input_schema,
        )
        # Register via internal tool manager
        if hasattr(mcp, '_tool_manager'):
            mcp._tool_manager.add_tool(mcp_tool, _handler_async)
            return
    except (ImportError, AttributeError, TypeError):
        pass

    # Fallback: use @mcp.tool() decorator (schema in description)
    description = tool.description
    param_lines = [f"  - {p.name}: {p.description or p.type}" for p in tool.parameters if p.description or p.type]
    if param_lines:
        description += "\n\nParameters:\n" + "\n".join(param_lines)

    @mcp.tool(name=tool.name, description=description)
    def _handler(**kwargs) -> str:
        from api_to_tools.core import execute
        result = execute(tool, kwargs)
        if isinstance(result.data, str):
            return result.data
        return json.dumps(result.data, ensure_ascii=False, indent=2, default=str)
