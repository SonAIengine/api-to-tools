"""Tests for OpenAPI 3.0 spec export (Tool → OpenAPI)."""

import json

from api_to_tools.adapters.openapi_export import to_openapi_spec, to_openapi_json
from api_to_tools.types import Tool, ToolParameter


def _make_tool(name="getUsers", method="GET", endpoint="https://api.example.com/api/v1/users",
               params=None, tags=None, metadata=None):
    return Tool(
        name=name,
        description=f"Test: {name}",
        parameters=params or [],
        endpoint=endpoint,
        method=method,
        protocol="rest",
        tags=tags or ["users"],
        metadata=metadata or {},
    )


def test_basic_spec_structure():
    tools = [_make_tool()]
    spec = to_openapi_spec(tools, title="My API", version="2.0.0")
    assert spec["openapi"] == "3.0.0"
    assert spec["info"]["title"] == "My API"
    assert spec["info"]["version"] == "2.0.0"
    assert "/api/v1/users" in spec["paths"]


def test_servers_from_endpoints():
    tools = [
        _make_tool(endpoint="https://api.example.com/users"),
        _make_tool(name="b", endpoint="https://other.example.com/items"),
    ]
    spec = to_openapi_spec(tools)
    urls = {s["url"] for s in spec["servers"]}
    assert "https://api.example.com" in urls
    assert "https://other.example.com" in urls


def test_get_with_query_params():
    params = [
        ToolParameter(name="page", type="integer", required=False, location="query", description="Page number"),
        ToolParameter(name="size", type="integer", required=False, location="query"),
    ]
    tools = [_make_tool(params=params)]
    spec = to_openapi_spec(tools)
    op = spec["paths"]["/api/v1/users"]["get"]
    assert len(op["parameters"]) == 2
    page = next(p for p in op["parameters"] if p["name"] == "page")
    assert page["in"] == "query"
    assert page["schema"]["type"] == "integer"
    assert page["description"] == "Page number"


def test_path_params():
    params = [ToolParameter(name="id", type="string", required=True, location="path")]
    tools = [_make_tool(endpoint="https://api.example.com/users/{id}", params=params)]
    spec = to_openapi_spec(tools)
    op = spec["paths"]["/users/{id}"]["get"]
    param = op["parameters"][0]
    assert param["name"] == "id"
    assert param["in"] == "path"
    assert param["required"] is True


def test_post_with_body():
    params = [
        ToolParameter(name="name", type="string", required=True, location="body"),
        ToolParameter(name="email", type="string", required=True, location="body"),
        ToolParameter(name="age", type="integer", required=False, location="body"),
    ]
    tools = [_make_tool(name="createUser", method="POST", params=params)]
    spec = to_openapi_spec(tools)
    op = spec["paths"]["/api/v1/users"]["post"]
    body = op["requestBody"]["content"]["application/json"]["schema"]
    assert body["type"] == "object"
    assert "name" in body["properties"]
    assert body["required"] == ["name", "email"]


def test_response_schema_from_metadata():
    metadata = {
        "response_schema": {
            "type": "array",
            "items": {"type": "object", "properties": {"id": {"type": "integer"}}},
        },
    }
    tools = [_make_tool(metadata=metadata)]
    spec = to_openapi_spec(tools)
    resp = spec["paths"]["/api/v1/users"]["get"]["responses"]["200"]
    assert resp["content"]["application/json"]["schema"]["type"] == "array"


def test_tags_collected():
    tools = [
        _make_tool(tags=["users"]),
        _make_tool(name="b", tags=["orders"]),
    ]
    spec = to_openapi_spec(tools)
    tag_names = {t["name"] for t in spec["tags"]}
    assert tag_names == {"users", "orders"}


def test_operation_id():
    tools = [_make_tool(name="listAllUsers")]
    spec = to_openapi_spec(tools)
    op = spec["paths"]["/api/v1/users"]["get"]
    assert op["operationId"] == "listAllUsers"


def test_to_openapi_json():
    tools = [_make_tool()]
    result = to_openapi_json(tools, title="Test")
    parsed = json.loads(result)
    assert parsed["info"]["title"] == "Test"


def test_empty_tools():
    spec = to_openapi_spec([])
    assert spec["paths"] == {}


def test_description():
    spec = to_openapi_spec([], description="My awesome API")
    assert spec["info"]["description"] == "My awesome API"
