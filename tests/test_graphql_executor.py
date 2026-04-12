"""Tests for GraphQL executor — _build_query (pure function)."""

from api_to_tools.executors.graphql import _build_query
from api_to_tools.types import Tool, ToolParameter


def _make_gql_tool(name="getUser", method="query", params=None, selection_set="{ id name }"):
    return Tool(
        name=name,
        description="test",
        parameters=params or [],
        endpoint="https://example.com/graphql",
        method=method,
        protocol="graphql",
        metadata={"selection_set": selection_set},
    )


def test_build_query_no_params():
    tool = _make_gql_tool()
    q = _build_query(tool, {})
    assert q == "query { getUser { id name } }"


def test_build_query_with_params():
    tool = _make_gql_tool(params=[
        ToolParameter(name="id", type="ID", required=True, location="body"),
    ])
    q = _build_query(tool, {"id": "123"})
    assert "$id: ID!" in q
    assert "id: $id" in q
    assert q.startswith("query(")


def test_build_query_optional_param():
    tool = _make_gql_tool(params=[
        ToolParameter(name="limit", type="Int", required=False, location="body"),
    ])
    q = _build_query(tool, {"limit": 10})
    assert "$limit: Int" in q
    assert "Int!" not in q


def test_build_query_mutation():
    tool = _make_gql_tool(name="createUser", method="mutation", params=[
        ToolParameter(name="name", type="String", required=True, location="body"),
    ])
    q = _build_query(tool, {"name": "Alice"})
    assert q.startswith("mutation(")


def test_build_query_skips_unused_params():
    tool = _make_gql_tool(params=[
        ToolParameter(name="id", type="ID", required=True, location="body"),
        ToolParameter(name="extra", type="String", required=False, location="body"),
    ])
    q = _build_query(tool, {"id": "1"})
    assert "$id" in q
    assert "extra" not in q


def test_build_query_multiple_params():
    tool = _make_gql_tool(params=[
        ToolParameter(name="id", type="ID", required=True, location="body"),
        ToolParameter(name="name", type="String", required=False, location="body"),
    ])
    q = _build_query(tool, {"id": "1", "name": "Alice"})
    assert "$id: ID!" in q
    assert "$name: String" in q
    assert "id: $id" in q
    assert "name: $name" in q
