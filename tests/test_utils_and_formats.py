"""Tests for utilities and LLM format converters."""

from api_to_tools.adapters.formats import to_anthropic_tools, to_function_calling
from api_to_tools.types import Tool, ToolParameter
from api_to_tools.utils import (
    group_by_method,
    group_by_tag,
    search_tools,
    summarize,
)


def _make_tool(name, method="GET", tags=None, params=None) -> Tool:
    return Tool(
        name=name,
        description=f"desc for {name}",
        parameters=params or [],
        endpoint=f"https://api.example.com/{name}",
        method=method,
        protocol="rest",
        tags=tags or [],
    )


def _sample_tools() -> list[Tool]:
    return [
        _make_tool("listUsers", "GET", ["users"]),
        _make_tool("createUser", "POST", ["users"]),
        _make_tool("deleteUser", "DELETE", ["users"]),
        _make_tool("listOrders", "GET", ["orders"]),
        _make_tool("searchItems", "GET", ["search"]),
    ]


# ── group / summarize ───────────────────────

def test_group_by_tag():
    groups = group_by_tag(_sample_tools())
    assert len(groups["users"]) == 3
    assert len(groups["orders"]) == 1
    assert len(groups["search"]) == 1


def test_group_by_method():
    groups = group_by_method(_sample_tools())
    assert len(groups["GET"]) == 3
    assert len(groups["POST"]) == 1
    assert len(groups["DELETE"]) == 1


def test_summarize_totals():
    s = summarize(_sample_tools())
    assert s["total"] == 5
    assert s["by_method"]["GET"] == 3
    assert s["by_tag"]["users"] == 3


def test_search_tools_by_name():
    tools = _sample_tools()
    results = search_tools(tools, "user")
    assert len(results) == 3


def test_search_tools_case_insensitive():
    tools = _sample_tools()
    assert len(search_tools(tools, "USER")) == 3


def test_search_tools_by_description():
    tools = _sample_tools()
    assert any(t.name == "listOrders" for t in search_tools(tools, "listOrders"))


# ── format converters ──────────────────────

def test_to_anthropic_tools_shape():
    params = [
        ToolParameter(name="id", type="integer", required=True, location="path"),
        ToolParameter(name="q", type="string", required=False, location="query",
                      description="search query"),
    ]
    tools = [_make_tool("getUser", params=params)]
    result = to_anthropic_tools(tools)

    assert len(result) == 1
    item = result[0]
    assert item["name"] == "getUser"
    assert item["description"] == "desc for getUser"

    schema = item["input_schema"]
    assert schema["type"] == "object"
    assert "id" in schema["properties"]
    assert schema["properties"]["id"]["type"] == "integer"
    assert schema["properties"]["q"]["description"] == "search query"
    assert schema["required"] == ["id"]


def test_to_function_calling_shape():
    params = [ToolParameter(name="id", type="integer", required=True, location="path")]
    tools = [_make_tool("getUser", params=params)]
    result = to_function_calling(tools)

    assert len(result) == 1
    fn = result[0]
    assert fn["type"] == "function"
    assert fn["function"]["name"] == "getUser"
    assert fn["function"]["parameters"]["required"] == ["id"]


def test_formats_preserve_enum():
    params = [
        ToolParameter(
            name="status",
            type="string",
            required=True,
            enum=["A", "B"],
        )
    ]
    tools = [_make_tool("x", params=params)]
    anthropic = to_anthropic_tools(tools)
    assert anthropic[0]["input_schema"]["properties"]["status"]["enum"] == ["A", "B"]


def test_formats_array_type():
    """array[object] should become {"type": "array", "items": {"type": "object"}}."""
    params = [
        ToolParameter(name="items", type="array[object]", required=True),
        ToolParameter(name="tags", type="array[string]", required=False),
    ]
    tools = [_make_tool("x", params=params)]
    openai = to_function_calling(tools)
    props = openai[0]["function"]["parameters"]["properties"]
    assert props["items"]["type"] == "array"
    assert props["items"]["items"]["type"] == "object"
    assert props["tags"]["type"] == "array"
    assert props["tags"]["items"]["type"] == "string"


def test_formats_unknown_type_falls_back_to_string():
    params = [ToolParameter(name="x", type="unknown_custom", required=False)]
    tools = [_make_tool("x", params=params)]
    result = to_anthropic_tools(tools)
    assert result[0]["input_schema"]["properties"]["x"]["type"] == "string"
