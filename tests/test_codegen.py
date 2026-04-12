"""Tests for SDK code generation."""

from api_to_tools.codegen import (
    _py_type,
    _safe_method_name,
    _extract_path,
    generate_python_sdk,
    generate_typescript_sdk,
)
from api_to_tools.types import Tool, ToolParameter


def _make_tool(name="getUsers", method="GET", endpoint="https://api.example.com/api/v1/users",
               params=None, protocol="rest"):
    return Tool(
        name=name,
        description=f"Get {name}",
        parameters=params or [],
        endpoint=endpoint,
        method=method,
        protocol=protocol,
        tags=["test"],
    )


# ──────────────────────────────────────────────
# Helpers
# ──────────────────────────────────────────────

def test_py_type_string():
    p = ToolParameter(name="x", type="string")
    assert _py_type(p) == "str"


def test_py_type_array():
    p = ToolParameter(name="x", type="array[integer]")
    assert _py_type(p) == "list[int]"


def test_py_type_object():
    p = ToolParameter(name="x", type="object")
    assert _py_type(p) == "dict"


def test_safe_method_name():
    assert _safe_method_name("getUsers") == "getusers"
    assert _safe_method_name("get-users-list") == "get_users_list"
    assert _safe_method_name("123test") == "call_123test"


def test_extract_path():
    assert _extract_path("https://api.example.com/api/v1/users") == "/api/v1/users"
    assert _extract_path("https://api.example.com") == "/"


# ──────────────────────────────────────────────
# Python SDK
# ──────────────────────────────────────────────

def test_generate_python_sdk_basic():
    params = [
        ToolParameter(name="page", type="integer", required=False, location="query"),
    ]
    tools = [_make_tool(params=params)]
    code = generate_python_sdk(tools, class_name="TestClient")
    assert "class TestClient:" in code
    assert "def getusers(self" in code
    assert "page: int | None" in code
    assert "import httpx" in code


def test_generate_python_sdk_required_params():
    params = [
        ToolParameter(name="id", type="string", required=True, location="path"),
        ToolParameter(name="q", type="string", required=False, location="query"),
    ]
    tools = [_make_tool(params=params)]
    code = generate_python_sdk(tools)
    # Required params come before optional
    assert "id: str" in code
    assert "q: str | None" in code


def test_generate_python_sdk_post_with_body():
    params = [
        ToolParameter(name="name", type="string", required=True, location="body"),
    ]
    tools = [_make_tool(name="createUser", method="POST", params=params)]
    code = generate_python_sdk(tools)
    assert 'self._client.request("POST"' in code
    assert "body" in code


def test_generate_python_sdk_context_manager():
    code = generate_python_sdk([_make_tool()])
    assert "def __enter__" in code
    assert "def __exit__" in code
    assert "def close" in code


def test_generate_python_sdk_multiple_tools():
    tools = [_make_tool(name="a"), _make_tool(name="b")]
    code = generate_python_sdk(tools)
    assert "def a(self" in code
    assert "def b(self" in code


def test_generate_python_sdk_dedup_names():
    tools = [_make_tool(name="get"), _make_tool(name="get")]
    code = generate_python_sdk(tools)
    assert "def get(self" in code
    assert "def get_2(self" in code


# ──────────────────────────────────────────────
# TypeScript SDK
# ──────────────────────────────────────────────

def test_generate_typescript_sdk_basic():
    params = [
        ToolParameter(name="page", type="integer", required=False, location="query"),
    ]
    tools = [_make_tool(params=params)]
    code = generate_typescript_sdk(tools, class_name="TestClient")
    assert "export class TestClient" in code
    assert "async getusers(" in code
    assert "page?: number" in code


def test_generate_typescript_sdk_required():
    params = [ToolParameter(name="id", type="string", required=True, location="path")]
    tools = [_make_tool(params=params)]
    code = generate_typescript_sdk(tools)
    assert "id: string" in code


def test_generate_typescript_sdk_post():
    params = [ToolParameter(name="name", type="string", required=True, location="body")]
    tools = [_make_tool(name="createUser", method="POST", params=params)]
    code = generate_typescript_sdk(tools)
    assert "body:" in code
    assert "'POST'" in code
