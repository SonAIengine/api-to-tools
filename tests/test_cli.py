"""Tests for CLI — _build_auth and _discover_kwargs (pure functions)."""

from argparse import Namespace

from api_to_tools.cli import _build_auth, _discover_kwargs


# ──────────────────────────────────────────────
# _build_auth
# ──────────────────────────────────────────────

def test_build_auth_bearer():
    args = Namespace(bearer="eyJtoken", basic=None, api_key=None, cookie=None, login=None, header=None)
    auth = _build_auth(args)
    assert auth is not None
    assert auth.type == "bearer"
    assert auth.token == "eyJtoken"


def test_build_auth_basic():
    args = Namespace(bearer=None, basic="admin:secret", api_key=None, cookie=None, login=None, header=None)
    auth = _build_auth(args)
    assert auth.type == "basic"
    assert auth.username == "admin"
    assert auth.password == "secret"


def test_build_auth_basic_no_password():
    args = Namespace(bearer=None, basic="admin", api_key=None, cookie=None, login=None, header=None)
    auth = _build_auth(args)
    assert auth.type == "basic"
    assert auth.username == "admin"
    assert auth.password == ""


def test_build_auth_api_key():
    args = Namespace(bearer=None, basic=None, api_key="X-API-Key=abc123", cookie=None, login=None, header=None)
    auth = _build_auth(args)
    assert auth.type == "api_key"
    assert auth.key == "X-API-Key"
    assert auth.value == "abc123"


def test_build_auth_cookie():
    args = Namespace(bearer=None, basic=None, api_key=None, cookie=["session=abc", "csrf=xyz"], login=None, header=None)
    auth = _build_auth(args)
    assert auth.type == "cookie"
    assert auth.cookies == {"session": "abc", "csrf": "xyz"}


def test_build_auth_login():
    args = Namespace(
        bearer=None, basic=None, api_key=None, cookie=None,
        login="https://example.com/login", login_user="admin", login_pass="secret",
        header=None,
    )
    auth = _build_auth(args)
    assert auth.type == "cookie"
    assert auth.login_url == "https://example.com/login"
    assert auth.username == "admin"
    assert auth.password == "secret"


def test_build_auth_custom_headers():
    args = Namespace(
        bearer=None, basic=None, api_key=None, cookie=None, login=None,
        header=["X-Tenant: acme", "Authorization: Custom xyz"],
    )
    auth = _build_auth(args)
    assert auth.type == "custom"
    assert auth.headers == {"X-Tenant": "acme", "Authorization": "Custom xyz"}


def test_build_auth_none():
    args = Namespace(bearer=None, basic=None, api_key=None, cookie=None, login=None, header=None)
    assert _build_auth(args) is None


def test_build_auth_priority_bearer_over_basic():
    """Bearer should win when both are provided."""
    args = Namespace(bearer="token", basic="user:pass", api_key=None, cookie=None, login=None, header=None)
    auth = _build_auth(args)
    assert auth.type == "bearer"


# ──────────────────────────────────────────────
# _discover_kwargs
# ──────────────────────────────────────────────

def test_discover_kwargs_scan_js():
    args = Namespace(scan_js=True, crawl=False)
    kw = _discover_kwargs(args)
    assert kw == {"scan_js": True}


def test_discover_kwargs_crawl():
    args = Namespace(scan_js=False, crawl=True, max_pages=100, headed=False, backend="auto", no_safe_mode=False)
    kw = _discover_kwargs(args)
    assert kw["crawl"] is True
    assert kw["max_pages"] == 100
    assert kw["headless"] is True
    assert kw["safe_mode"] is True


def test_discover_kwargs_crawl_headed():
    args = Namespace(scan_js=False, crawl=True, max_pages=50, headed=True, backend="playwright", no_safe_mode=True)
    kw = _discover_kwargs(args)
    assert kw["headless"] is False
    assert kw["safe_mode"] is False
    assert kw["backend"] == "playwright"


def test_discover_kwargs_empty():
    args = Namespace(scan_js=False, crawl=False)
    kw = _discover_kwargs(args)
    assert kw == {}
