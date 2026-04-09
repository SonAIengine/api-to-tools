"""Tests for authentication helpers."""

import base64

from api_to_tools.auth import (
    build_auth_cookies,
    build_auth_headers,
    build_auth_params,
)
from api_to_tools.types import AuthConfig


# ── build_auth_headers ──────────────────────

def test_basic_auth_header():
    auth = AuthConfig(type="basic", username="admin", password="secret")
    headers = build_auth_headers(auth)
    expected = "Basic " + base64.b64encode(b"admin:secret").decode()
    assert headers["Authorization"] == expected


def test_bearer_auth_header():
    auth = AuthConfig(type="bearer", token="eyJxyz")
    headers = build_auth_headers(auth)
    assert headers["Authorization"] == "Bearer eyJxyz"


def test_api_key_in_header():
    auth = AuthConfig(type="api_key", key="X-API-Key", value="abc123", location="header")
    headers = build_auth_headers(auth)
    assert headers["X-API-Key"] == "abc123"


def test_api_key_in_query_not_in_headers():
    auth = AuthConfig(type="api_key", key="api_key", value="abc", location="query")
    headers = build_auth_headers(auth)
    assert "api_key" not in headers


def test_custom_headers():
    auth = AuthConfig(
        type="custom",
        headers={"X-Tenant": "acme", "X-Trace": "123"},
    )
    headers = build_auth_headers(auth)
    assert headers["X-Tenant"] == "acme"
    assert headers["X-Trace"] == "123"


def test_cookie_type_returns_no_headers():
    auth = AuthConfig(type="cookie", cookies={"s": "abc"})
    assert build_auth_headers(auth) == {}


# ── build_auth_params ───────────────────────

def test_api_key_in_query_params():
    auth = AuthConfig(type="api_key", key="token", value="xyz", location="query")
    params = build_auth_params(auth)
    assert params["token"] == "xyz"


def test_api_key_in_header_not_in_params():
    auth = AuthConfig(type="api_key", key="token", value="xyz", location="header")
    params = build_auth_params(auth)
    assert "token" not in params


def test_params_empty_for_non_api_key():
    assert build_auth_params(AuthConfig(type="bearer", token="t")) == {}
    assert build_auth_params(AuthConfig(type="basic", username="u", password="p")) == {}


# ── build_auth_cookies ──────────────────────

def test_direct_cookies():
    auth = AuthConfig(type="cookie", cookies={"session": "abc", "csrf": "xyz"})
    cookies = build_auth_cookies(auth)
    assert cookies == {"session": "abc", "csrf": "xyz"}


def test_non_cookie_type_returns_empty():
    assert build_auth_cookies(AuthConfig(type="bearer", token="t")) == {}
