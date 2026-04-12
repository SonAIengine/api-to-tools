"""Tests for core.py — _apply_filters (pure function)."""

import re

from api_to_tools.core import _apply_filters
from api_to_tools.types import Tool, ToolParameter


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
