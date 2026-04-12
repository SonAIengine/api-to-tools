"""Tests for MCP adapter — tool schema generation."""

from api_to_tools.adapters.mcp_adapter import (
    _py_type,
    _safe_param_name,
    _sanitize_tool_name,
    _build_handler,
    create_mcp_server,
)
from api_to_tools.types import Tool, ToolParameter


def _make_tool(name="getUser", params=None):
    return Tool(
        name=name,
        description=f"Test: {name}",
        parameters=params or [],
        endpoint="https://api.example.com/users",
        method="GET",
        protocol="rest",
    )


# ──────────────────────────────────────────────
# Helpers
# ──────────────────────────────────────────────

def test_py_type_basic():
    assert _py_type(ToolParameter(name="x", type="string")) is str
    assert _py_type(ToolParameter(name="x", type="integer")) is int
    assert _py_type(ToolParameter(name="x", type="number")) is float
    assert _py_type(ToolParameter(name="x", type="boolean")) is bool
    assert _py_type(ToolParameter(name="x", type="array[string]")) is list


def test_safe_param_name_identifier():
    assert _safe_param_name("userId") == "userId"
    assert _safe_param_name("user-id") == "user_id"
    assert _safe_param_name("user.id") == "user_id"
    assert _safe_param_name("class") == "class_"  # Python keyword
    assert _safe_param_name("123abc") == "p_123abc"
    assert _safe_param_name("") == "arg"


def test_sanitize_tool_name():
    assert _sanitize_tool_name("getUser") == "getUser"
    # Non-ASCII → stripped → fallback "tool"
    assert _sanitize_tool_name("회원_조회") == "tool"
    assert _sanitize_tool_name("") == "tool"
    # Max 64 chars
    assert len(_sanitize_tool_name("a" * 100)) == 64
    # Hyphens and underscores preserved
    assert _sanitize_tool_name("get-user_info") == "get-user_info"


# ──────────────────────────────────────────────
# Handler signature
# ──────────────────────────────────────────────

def test_handler_signature_matches_params():
    import inspect

    tool = _make_tool(params=[
        ToolParameter(name="userId", type="integer", required=True),
        ToolParameter(name="includeDetails", type="boolean", required=False),
    ])
    handler = _build_handler(tool)
    sig = inspect.signature(handler)

    assert "userId" in sig.parameters
    assert "includeDetails" in sig.parameters
    assert sig.parameters["userId"].annotation is int
    assert sig.parameters["includeDetails"].annotation is bool
    # Required has no default
    assert sig.parameters["userId"].default is inspect.Parameter.empty
    # Optional has default None
    assert sig.parameters["includeDetails"].default is None


def test_handler_required_before_optional():
    """Python signatures require non-default params before default ones."""
    import inspect
    tool = _make_tool(params=[
        ToolParameter(name="optional_first", type="string", required=False),
        ToolParameter(name="required_second", type="string", required=True),
    ])
    handler = _build_handler(tool)
    sig = inspect.signature(handler)
    params = list(sig.parameters.values())
    # Required should come first
    assert params[0].name == "required_second"
    assert params[1].name == "optional_first"


# ──────────────────────────────────────────────
# Full MCP server
# ──────────────────────────────────────────────

def test_create_mcp_server_basic():
    tool = _make_tool(params=[
        ToolParameter(name="id", type="integer", required=True),
    ])
    mcp = create_mcp_server([tool])
    assert "getUser" in mcp._tool_manager._tools


def test_mcp_schema_has_proper_types():
    tool = _make_tool(params=[
        ToolParameter(name="id", type="integer", required=True),
        ToolParameter(name="name", type="string", required=False),
    ])
    mcp = create_mcp_server([tool])
    mcp_tool = mcp._tool_manager._tools["getUser"]
    schema = mcp_tool.parameters

    assert schema["type"] == "object"
    assert schema["properties"]["id"]["type"] == "integer"
    assert schema["properties"]["name"]["type"] == "string"
    assert "id" in schema["required"]
    assert "name" not in schema.get("required", [])


def test_mcp_schema_not_generic_kwargs():
    """Regression: ensure schema doesn't collapse to {kwargs: string}."""
    tool = _make_tool(params=[
        ToolParameter(name="foo", type="string", required=True),
    ])
    mcp = create_mcp_server([tool])
    mcp_tool = mcp._tool_manager._tools["getUser"]
    schema = mcp_tool.parameters

    assert "kwargs" not in schema.get("properties", {})
    assert "foo" in schema["properties"]


def test_mcp_description_includes_params():
    tool = _make_tool(params=[
        ToolParameter(name="id", type="integer", required=True, description="User ID"),
    ])
    mcp = create_mcp_server([tool])
    mcp_tool = mcp._tool_manager._tools["getUser"]
    assert "id" in mcp_tool.description
    assert "User ID" in mcp_tool.description
    assert "Endpoint:" in mcp_tool.description


def test_mcp_tool_name_dedup():
    tools = [_make_tool(name="getUser"), _make_tool(name="getUser")]
    mcp = create_mcp_server(tools)
    # Second should be getUser_2
    assert "getUser" in mcp._tool_manager._tools
    assert "getUser_2" in mcp._tool_manager._tools


def test_mcp_tool_name_sanitization():
    """Non-ASCII names get sanitized for MCP."""
    tool = _make_tool(name="회원_조회")
    mcp = create_mcp_server([tool])
    # Should be registered under some ASCII name
    assert len(mcp._tool_manager._tools) == 1
    name = list(mcp._tool_manager._tools.keys())[0]
    assert all(c.isalnum() or c in "_-" for c in name)


def test_mcp_handles_special_param_names():
    """Parameters with hyphens, keywords, digits still work."""
    tool = _make_tool(params=[
        ToolParameter(name="user-id", type="string", required=True),
        ToolParameter(name="class", type="string", required=True),
    ])
    mcp = create_mcp_server([tool])
    mcp_tool = mcp._tool_manager._tools["getUser"]
    schema = mcp_tool.parameters

    # Python-safe names in schema
    props = schema["properties"]
    assert "user_id" in props
    assert "class_" in props
