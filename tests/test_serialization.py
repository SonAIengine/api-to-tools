"""Tests for Tool save/load serialization."""

import json

import pytest

from api_to_tools import save_tools, load_tools, tools_to_json, tools_from_json
from api_to_tools.serialization import tool_to_dict, dict_to_tool, _sanitize_auth
from api_to_tools.types import Tool, ToolParameter


def _make_tool(name="getUser", with_auth=False, with_schema=False):
    metadata = {}
    if with_auth:
        metadata["auth"] = {
            "type": "bearer",
            "token": "secret_token_abc",
            "username": "admin",
            "password": "secret_pass",
        }
    if with_schema:
        metadata["response_schema"] = {"type": "object", "properties": {"id": {"type": "integer"}}}

    return Tool(
        name=name,
        description="Test tool",
        parameters=[
            ToolParameter(name="id", type="integer", required=True, location="path"),
            ToolParameter(name="q", type="string", required=False, location="query",
                          description="Search query"),
        ],
        endpoint="https://api.example.com/users/{id}",
        method="GET",
        protocol="rest",
        tags=["users"],
        metadata=metadata,
    )


# ──────────────────────────────────────────────
# tool_to_dict / dict_to_tool
# ──────────────────────────────────────────────

def test_tool_to_dict_basic():
    tool = _make_tool()
    d = tool_to_dict(tool)
    assert d["name"] == "getUser"
    assert d["method"] == "GET"
    assert d["protocol"] == "rest"
    assert len(d["parameters"]) == 2
    assert d["parameters"][0]["name"] == "id"


def test_dict_to_tool_roundtrip():
    original = _make_tool(with_schema=True)
    d = tool_to_dict(original)
    restored = dict_to_tool(d)
    assert restored.name == original.name
    assert restored.endpoint == original.endpoint
    assert len(restored.parameters) == 2
    assert restored.parameters[0].name == "id"
    assert restored.parameters[0].required is True
    assert restored.metadata["response_schema"]["type"] == "object"


# ──────────────────────────────────────────────
# Auth sanitization
# ──────────────────────────────────────────────

def test_sanitize_auth_removes_secrets():
    auth = {
        "type": "bearer",
        "token": "secret_token",
        "password": "secret_pass",
        "refresh_token": "rt_xyz",
        "client_secret": "cs_abc",
        "cookies": {"session": "abc"},
        "username": "admin",
        "verify_ssl": True,
    }
    clean = _sanitize_auth(auth)
    assert clean["type"] == "bearer"
    assert clean["username"] == "admin"
    assert clean["verify_ssl"] is True
    assert "token" not in clean
    assert "password" not in clean
    assert "refresh_token" not in clean
    assert "client_secret" not in clean
    assert "cookies" not in clean


def test_tool_to_dict_strips_auth_by_default():
    tool = _make_tool(with_auth=True)
    d = tool_to_dict(tool)
    assert "token" not in d["metadata"]["auth"]
    assert "password" not in d["metadata"]["auth"]
    assert d["metadata"]["auth"]["type"] == "bearer"


def test_tool_to_dict_preserves_auth_when_requested():
    tool = _make_tool(with_auth=True)
    d = tool_to_dict(tool, include_auth=True)
    assert d["metadata"]["auth"]["token"] == "secret_token_abc"
    assert d["metadata"]["auth"]["password"] == "secret_pass"


# ──────────────────────────────────────────────
# save_tools / load_tools (file I/O)
# ──────────────────────────────────────────────

def test_save_and_load_tools(tmp_path):
    tools = [_make_tool(name="a"), _make_tool(name="b", with_schema=True)]
    path = tmp_path / "tools.json"
    save_tools(tools, path)

    assert path.exists()
    loaded = load_tools(path)
    assert len(loaded) == 2
    assert loaded[0].name == "a"
    assert loaded[1].name == "b"
    assert loaded[1].metadata["response_schema"]["type"] == "object"


def test_save_file_format(tmp_path):
    tools = [_make_tool()]
    path = tmp_path / "tools.json"
    save_tools(tools, path)

    raw = json.loads(path.read_text())
    assert raw["version"] == 1
    assert isinstance(raw["tools"], list)
    assert raw["tools"][0]["name"] == "getUser"


def test_save_strips_auth_by_default(tmp_path):
    tools = [_make_tool(with_auth=True)]
    path = tmp_path / "tools.json"
    save_tools(tools, path)

    raw = path.read_text()
    assert "secret_token_abc" not in raw
    assert "secret_pass" not in raw


def test_save_includes_auth_when_requested(tmp_path):
    tools = [_make_tool(with_auth=True)]
    path = tmp_path / "tools.json"
    save_tools(tools, path, include_auth=True)

    raw = path.read_text()
    assert "secret_token_abc" in raw


def test_load_nonexistent_raises(tmp_path):
    with pytest.raises(FileNotFoundError):
        load_tools(tmp_path / "nonexistent.json")


def test_load_raw_list_format(tmp_path):
    """load_tools should accept a bare JSON list too."""
    tools = [_make_tool()]
    path = tmp_path / "tools.json"
    # Write as raw list (no version wrapper)
    data = [tool_to_dict(t) for t in tools]
    path.write_text(json.dumps(data))

    loaded = load_tools(path)
    assert len(loaded) == 1


# ──────────────────────────────────────────────
# JSON string helpers
# ──────────────────────────────────────────────

def test_tools_to_json_and_back():
    tools = [_make_tool(name="a"), _make_tool(name="b")]
    json_str = tools_to_json(tools)
    loaded = tools_from_json(json_str)
    assert len(loaded) == 2
    assert loaded[0].name == "a"
    assert loaded[1].name == "b"


def test_tools_to_json_strips_auth():
    tools = [_make_tool(with_auth=True)]
    json_str = tools_to_json(tools)
    assert "secret_token_abc" not in json_str
