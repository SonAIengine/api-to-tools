"""MCP Server adapter.

Generates FastMCP servers from discovered Tool definitions.
Each Tool becomes an MCP tool with proper parameter schema so clients
(Claude Desktop, MCP Inspector) see typed arguments — not generic kwargs.
"""

from __future__ import annotations

import inspect
import json
import re

from mcp.server.fastmcp import FastMCP

from api_to_tools.types import Tool, ToolParameter

# Python type mapping from JSON Schema primitive types.
# FastMCP derives the tool inputSchema by introspecting these annotations.
_TYPE_TO_PY = {
    "string": str,
    "integer": int,
    "number": float,
    "boolean": bool,
    "array": list,
    "object": dict,
    "null": type(None),
}


def _py_type(param: ToolParameter):
    """Map a ToolParameter type string to a Python type for introspection."""
    t = param.type
    if t.startswith("array["):
        return list
    return _TYPE_TO_PY.get(t, str)


def _safe_param_name(name: str) -> str:
    """Convert a parameter name to a valid Python identifier.

    MCP tools can have arbitrary parameter names (e.g. containing `-`),
    but Python signatures must be valid identifiers. We sanitize and
    remember the mapping so execute() gets the original names back.
    """
    clean = re.sub(r"[^a-zA-Z0-9_]", "_", name)
    if clean and clean[0].isdigit():
        clean = "p_" + clean
    if not clean:
        clean = "arg"
    # Avoid Python keywords
    import keyword
    if keyword.iskeyword(clean):
        clean = clean + "_"
    return clean


def _build_handler(tool: Tool):
    """Build an async handler with a proper signature for FastMCP introspection.

    Returns a function whose __signature__ and __annotations__ match the
    Tool's parameters, so FastMCP generates the correct inputSchema.
    """
    # Build parameter list for the signature
    sig_params: list[inspect.Parameter] = []
    annotations: dict = {}
    name_map: dict[str, str] = {}  # python_name -> original_name

    # Required params first, then optional (Python requires this ordering)
    ordered = sorted(tool.parameters, key=lambda p: 0 if p.required else 1)
    used_names: set[str] = set()

    for p in ordered:
        py_name = _safe_param_name(p.name)
        # Ensure uniqueness after sanitization
        if py_name in used_names:
            counter = 2
            while f"{py_name}_{counter}" in used_names:
                counter += 1
            py_name = f"{py_name}_{counter}"
        used_names.add(py_name)
        name_map[py_name] = p.name

        py_type = _py_type(p)
        annotations[py_name] = py_type

        sig_params.append(
            inspect.Parameter(
                name=py_name,
                kind=inspect.Parameter.KEYWORD_ONLY,
                default=inspect.Parameter.empty if p.required else None,
                annotation=py_type,
            )
        )

    annotations["return"] = str

    async def _handler(**kwargs) -> str:
        from api_to_tools.core import execute
        # Map Python-safe names back to original parameter names
        args = {}
        for py_name, value in kwargs.items():
            if value is None:
                continue
            orig_name = name_map.get(py_name, py_name)
            args[orig_name] = value

        result = execute(tool, args)
        if isinstance(result.data, str):
            return result.data
        return json.dumps(result.data, ensure_ascii=False, indent=2, default=str)

    _handler.__signature__ = inspect.Signature(
        parameters=sig_params,
        return_annotation=str,
    )
    _handler.__annotations__ = annotations
    _handler.__name__ = tool.name

    return _handler


def _build_description(tool: Tool) -> str:
    """Build a rich description including parameter docs for clients that
    only show the description (e.g. older MCP clients)."""
    desc = tool.description or f"{tool.method} {tool.endpoint}"

    param_lines = []
    for p in tool.parameters:
        req = "required" if p.required else "optional"
        line = f"  - {p.name} ({p.type}, {req})"
        if p.description:
            line += f": {p.description}"
        param_lines.append(line)

    if param_lines:
        desc = desc + "\n\nParameters:\n" + "\n".join(param_lines)

    # Append endpoint info for debugging
    desc += f"\n\nEndpoint: {tool.method} {tool.endpoint}"
    return desc


def _sanitize_tool_name(name: str) -> str:
    """MCP tool names must match [a-zA-Z0-9_-]+, max 64 chars."""
    clean = re.sub(r"[^a-zA-Z0-9_-]", "_", name)
    clean = re.sub(r"_+", "_", clean).strip("_-")
    if not clean:
        clean = "tool"
    return clean[:64]


def create_mcp_server(tools: list[Tool], name: str = "api-to-tools") -> FastMCP:
    """Create an MCP server that exposes the given tools with proper schemas.

    Each Tool is registered as an MCP tool with:
    - Typed parameter signature (so clients see proper input schema)
    - Rich description including parameter docs and endpoint info
    - Auto-resolved auth from tool.metadata (set by discover())

    Args:
        tools: Tools to expose as MCP tools.
        name: MCP server name (shown to clients).

    Returns:
        Configured FastMCP instance. Call `.run(transport="stdio")` to serve.
    """
    mcp = FastMCP(name)

    registered_names: set[str] = set()
    for tool in tools:
        _register_tool(mcp, tool, registered_names)

    return mcp


def _register_tool(mcp: FastMCP, tool: Tool, registered_names: set[str]) -> None:
    """Register a single Tool on the MCP server with full parameter schema."""
    # Sanitize and deduplicate MCP tool name
    mcp_name = _sanitize_tool_name(tool.name)
    if mcp_name in registered_names:
        counter = 2
        while f"{mcp_name}_{counter}" in registered_names:
            counter += 1
        mcp_name = f"{mcp_name}_{counter}"
    registered_names.add(mcp_name)

    handler = _build_handler(tool)
    description = _build_description(tool)

    # Register via FastMCP's tool manager — it introspects the handler's
    # signature to build the JSON schema automatically.
    mcp._tool_manager.add_tool(
        handler,
        name=mcp_name,
        description=description,
    )
