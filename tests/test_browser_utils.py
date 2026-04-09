"""Tests for pure-function browser utilities (no Playwright dependency)."""

from api_to_tools.parsers._browser_utils import (
    is_mutation_request,
    normalize_route_url,
)


# ── is_mutation_request ─────────────────────

def test_get_is_never_mutation():
    assert not is_mutation_request("GET", "https://api.example.com/users/delete")
    assert not is_mutation_request("GET", "https://api.example.com/users")
    assert not is_mutation_request("HEAD", "https://api.example.com/anything")
    assert not is_mutation_request("OPTIONS", "https://api.example.com/anything")


def test_delete_is_always_mutation():
    assert is_mutation_request("DELETE", "https://api.example.com/users/123")


def test_put_and_patch_are_mutations():
    assert is_mutation_request("PUT", "https://api.example.com/users/123")
    assert is_mutation_request("PATCH", "https://api.example.com/users/123")


def test_auth_post_is_not_mutation():
    assert not is_mutation_request("POST", "https://api.example.com/api/login")
    assert not is_mutation_request("POST", "https://api.example.com/api/auth/token")
    assert not is_mutation_request("POST", "https://api.example.com/api/refresh")


def test_post_with_read_keyword_is_not_mutation():
    """RPC-style read endpoints (common in Korean enterprise)."""
    assert not is_mutation_request("POST", "https://api.example.com/api/getUserList")
    assert not is_mutation_request("POST", "https://api.example.com/api/findOrders")
    assert not is_mutation_request("POST", "https://api.example.com/api/searchProducts")


def test_post_with_mutation_keyword_is_mutation():
    assert is_mutation_request("POST", "https://api.example.com/api/deleteUser")
    assert is_mutation_request("POST", "https://api.example.com/api/saveOrder")
    assert is_mutation_request("POST", "https://api.example.com/api/createItem")


def test_post_default_is_mutation():
    """Unknown POST should be treated as mutation (safe side)."""
    assert is_mutation_request("POST", "https://api.example.com/api/xyz")


# ── normalize_route_url ─────────────────────

def test_normalize_absolute_url():
    assert normalize_route_url(
        "https://other.example.com/path", "https://example.com"
    ) == "https://other.example.com/path"


def test_normalize_absolute_path():
    assert normalize_route_url(
        "/admin/users", "https://example.com"
    ) == "https://example.com/admin/users"


def test_normalize_relative_path():
    assert normalize_route_url(
        "admin/users", "https://example.com"
    ) == "https://example.com/admin/users"


def test_normalize_strips_leading_slashes():
    assert normalize_route_url(
        "///admin", "https://example.com"
    ) == "https://example.com/admin"
