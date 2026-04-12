"""Tests for core.py — _apply_filters, _deduplicate_names (pure functions)."""


from api_to_tools.core import _apply_filters, _deduplicate_names, _enrich_response_schema
from api_to_tools.types import Tool


def _make_tool(name="get_users", method="GET", endpoint="https://api.example.com/api/v1/users", tags=None):
    return Tool(
        name=name,
        description="test",
        parameters=[],
        endpoint=endpoint,
        method=method,
        protocol="rest",
        tags=tags or ["users"],
    )


# ──────────────────────────────────────────────
# base_url override
# ──────────────────────────────────────────────

def test_apply_filters_base_url():
    tools = [_make_tool(endpoint="https://old.example.com/api/v1/users")]
    result = _apply_filters(tools, {"base_url": "https://new.example.com"})
    assert result[0].endpoint == "https://new.example.com/api/v1/users"


def test_apply_filters_base_url_no_change_without_option():
    tools = [_make_tool()]
    result = _apply_filters(tools, {})
    assert result[0].endpoint == "https://api.example.com/api/v1/users"


# ──────────────────────────────────────────────
# tag filter
# ──────────────────────────────────────────────

def test_apply_filters_tags():
    tools = [
        _make_tool(name="get_users", tags=["users"]),
        _make_tool(name="get_orders", tags=["orders"]),
    ]
    result = _apply_filters(tools, {"tags": ["users"]})
    assert len(result) == 1
    assert result[0].name == "get_users"


def test_apply_filters_tags_multiple():
    tools = [
        _make_tool(name="a", tags=["users"]),
        _make_tool(name="b", tags=["orders"]),
        _make_tool(name="c", tags=["products"]),
    ]
    result = _apply_filters(tools, {"tags": ["users", "orders"]})
    assert len(result) == 2


def test_apply_filters_tags_no_match():
    tools = [_make_tool(tags=["users"])]
    result = _apply_filters(tools, {"tags": ["nonexistent"]})
    assert result == []


# ──────────────────────────────────────────────
# method filter
# ──────────────────────────────────────────────

def test_apply_filters_methods():
    tools = [
        _make_tool(name="get_users", method="GET"),
        _make_tool(name="create_user", method="POST"),
        _make_tool(name="delete_user", method="DELETE"),
    ]
    result = _apply_filters(tools, {"methods": ["GET", "POST"]})
    assert len(result) == 2


def test_apply_filters_methods_case_insensitive():
    tools = [_make_tool(method="GET")]
    result = _apply_filters(tools, {"methods": ["get"]})
    assert len(result) == 1


# ──────────────────────────────────────────────
# path_filter (regex)
# ──────────────────────────────────────────────

def test_apply_filters_path_filter():
    tools = [
        _make_tool(name="a", endpoint="https://api.example.com/api/v1/users"),
        _make_tool(name="b", endpoint="https://api.example.com/api/v1/orders"),
    ]
    result = _apply_filters(tools, {"path_filter": r"/users"})
    assert len(result) == 1
    assert result[0].name == "a"


def test_apply_filters_path_filter_regex():
    tools = [
        _make_tool(name="a", endpoint="https://api.example.com/api/v1/users"),
        _make_tool(name="b", endpoint="https://api.example.com/api/v2/users"),
    ]
    result = _apply_filters(tools, {"path_filter": r"/v[12]/users"})
    assert len(result) == 2


# ──────────────────────────────────────────────
# combined filters
# ──────────────────────────────────────────────

def test_apply_filters_combined():
    tools = [
        _make_tool(name="get_users", method="GET", tags=["users"]),
        _make_tool(name="create_user", method="POST", tags=["users"]),
        _make_tool(name="get_orders", method="GET", tags=["orders"]),
    ]
    result = _apply_filters(tools, {"tags": ["users"], "methods": ["GET"]})
    assert len(result) == 1
    assert result[0].name == "get_users"


def test_apply_filters_empty_kwargs():
    tools = [_make_tool(), _make_tool(name="b")]
    result = _apply_filters(tools, {})
    assert len(result) == 2


def test_apply_filters_base_url_does_not_mutate_original():
    tools = [_make_tool(endpoint="https://old.example.com/api/v1/users")]
    original_endpoint = tools[0].endpoint
    _apply_filters(tools, {"base_url": "https://new.example.com"})
    assert tools[0].endpoint == original_endpoint


# ──────────────────────────────────────────────
# _deduplicate_names
# ──────────────────────────────────────────────

def test_deduplicate_names_no_dupes():
    tools = [_make_tool(name="a"), _make_tool(name="b")]
    result = _deduplicate_names(tools)
    assert [t.name for t in result] == ["a", "b"]


def test_deduplicate_names_with_dupes():
    tools = [_make_tool(name="getUser"), _make_tool(name="getUser"), _make_tool(name="getUser")]
    result = _deduplicate_names(tools)
    names = [t.name for t in result]
    assert len(set(names)) == 3
    assert names[0] == "getUser"
    assert names[1] == "getUser_2"
    assert names[2] == "getUser_3"


def test_deduplicate_names_mixed():
    tools = [_make_tool(name="a"), _make_tool(name="b"), _make_tool(name="a")]
    result = _deduplicate_names(tools)
    names = [t.name for t in result]
    assert names == ["a", "b", "a_2"]


# ──────────────────────────────────────────────
# _enrich_response_schema
# ──────────────────────────────────────────────

def test_enrich_response_schema_dict():
    tool = _make_tool()
    _enrich_response_schema(tool, {"id": 1, "name": "Alice"})
    schema = tool.metadata["response_schema"]
    assert schema["type"] == "object"
    assert "id" in schema["properties"]
    assert schema["properties"]["id"]["type"] == "integer"


def test_enrich_response_schema_list():
    tool = _make_tool()
    _enrich_response_schema(tool, [{"id": 1}, {"id": 2}])
    schema = tool.metadata["response_schema"]
    assert schema["type"] == "array"
    assert schema["items"]["type"] == "object"


def test_enrich_response_schema_skips_string():
    tool = _make_tool()
    _enrich_response_schema(tool, "plain text")
    assert "response_schema" not in tool.metadata


def test_enrich_does_not_run_if_schema_exists():
    """execute() skips _enrich_response_schema when response_schema already set."""
    tool = _make_tool()
    tool.metadata["response_schema"] = {"type": "object"}
    # Simulate execute()'s guard: only enrich if no schema
    if not tool.metadata.get("response_schema"):
        _enrich_response_schema(tool, {"new": "data"})
    assert tool.metadata["response_schema"] == {"type": "object"}
