"""Tests for new features: SOAP auth, CLI execute, Tool.execute()."""

from argparse import Namespace
from unittest.mock import patch

from api_to_tools.cli import cmd_execute
from api_to_tools.executors.soap import _auth_key
from api_to_tools.types import AuthConfig, ExecutionResult, Tool


def _make_tool(name="getUser", method="GET"):
    return Tool(
        name=name,
        description="test",
        parameters=[],
        endpoint="https://api.example.com/users",
        method=method,
        protocol="rest",
    )


# ──────────────────────────────────────────────
# SOAP auth key (cache stability)
# ──────────────────────────────────────────────

def test_soap_auth_key_none():
    assert _auth_key(None) == ""


def test_soap_auth_key_same_config_same_key():
    a = AuthConfig(type="basic", username="admin", password="pass")
    b = AuthConfig(type="basic", username="admin", password="pass")
    assert _auth_key(a) == _auth_key(b)


def test_soap_auth_key_different_config():
    a = AuthConfig(type="basic", username="admin", password="pass1")
    b = AuthConfig(type="basic", username="admin", password="pass2")
    assert _auth_key(a) != _auth_key(b)


def test_soap_auth_key_cookies_sorted():
    """Cookie order should not affect cache key."""
    a = AuthConfig(type="cookie", cookies={"b": "2", "a": "1"})
    b = AuthConfig(type="cookie", cookies={"a": "1", "b": "2"})
    assert _auth_key(a) == _auth_key(b)


# ──────────────────────────────────────────────
# Tool.execute() method
# ──────────────────────────────────────────────

@patch("api_to_tools.core.execute")
def test_tool_execute_delegates_to_core(mock_execute):
    mock_execute.return_value = ExecutionResult(status=200, data={"ok": True})
    tool = _make_tool()
    result = tool.execute({"id": 1})
    mock_execute.assert_called_once_with(tool, {"id": 1}, auth=None)
    assert result.status == 200


@patch("api_to_tools.core.execute")
def test_tool_execute_with_auth(mock_execute):
    mock_execute.return_value = ExecutionResult(status=200, data={})
    tool = _make_tool()
    auth = AuthConfig(type="bearer", token="abc")
    tool.execute({"id": 1}, auth=auth)
    mock_execute.assert_called_once_with(tool, {"id": 1}, auth=auth)


@patch("api_to_tools.core.execute")
def test_tool_execute_default_empty_args(mock_execute):
    mock_execute.return_value = ExecutionResult(status=200, data={})
    tool = _make_tool()
    tool.execute()
    mock_execute.assert_called_once_with(tool, {}, auth=None)


# ──────────────────────────────────────────────
# CLI execute command — arg parsing + tool matching
# ──────────────────────────────────────────────

@patch("api_to_tools.cli.discover")
@patch("api_to_tools.cli.execute")
def test_cmd_execute_exact_match(mock_execute, mock_discover):
    mock_discover.return_value = [
        _make_tool(name="getUser"),
        _make_tool(name="getOrder"),
    ]
    mock_execute.return_value = ExecutionResult(status=200, data={"id": 1})

    args = Namespace(
        url="https://api.example.com", tool="getUser", args='{"id": 1}',
        scan_js=False, crawl=False,
        bearer=None, basic=None, api_key=None, cookie=None, login=None, header=None,
    )
    try:
        cmd_execute(args)
    except SystemExit as e:
        assert e.code == 0

    mock_execute.assert_called_once()
    called_tool = mock_execute.call_args[0][0]
    assert called_tool.name == "getUser"


@patch("api_to_tools.cli.discover")
def test_cmd_execute_no_match(mock_discover, capsys):
    mock_discover.return_value = [_make_tool(name="getUser")]
    args = Namespace(
        url="https://api.example.com", tool="nonexistent", args="{}",
        scan_js=False, crawl=False,
        bearer=None, basic=None, api_key=None, cookie=None, login=None, header=None,
    )
    try:
        cmd_execute(args)
    except SystemExit as e:
        assert e.code == 1


@patch("api_to_tools.cli.discover")
@patch("api_to_tools.cli.execute")
def test_cmd_execute_partial_match(mock_execute, mock_discover):
    mock_discover.return_value = [
        _make_tool(name="getUserProfile"),
        _make_tool(name="getOrder"),
    ]
    mock_execute.return_value = ExecutionResult(status=200, data={})

    args = Namespace(
        url="https://api.example.com", tool="UserProfile", args="{}",
        scan_js=False, crawl=False,
        bearer=None, basic=None, api_key=None, cookie=None, login=None, header=None,
    )
    try:
        cmd_execute(args)
    except SystemExit:
        pass

    mock_execute.assert_called_once()
    assert mock_execute.call_args[0][0].name == "getUserProfile"


@patch("api_to_tools.cli.discover")
def test_cmd_execute_invalid_json_args(mock_discover):
    mock_discover.return_value = [_make_tool(name="getUser")]
    args = Namespace(
        url="https://api.example.com", tool="getUser", args="not valid json",
        scan_js=False, crawl=False,
        bearer=None, basic=None, api_key=None, cookie=None, login=None, header=None,
    )
    try:
        cmd_execute(args)
    except SystemExit as e:
        assert e.code == 1
