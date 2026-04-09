"""Tests for the shared parameter builder utilities."""

from api_to_tools.parsers._param_builder import (
    build_params_from_json_schema,
    extract_tag_from_path,
    infer_json_type,
    is_api_url,
    normalize_path_params,
    sanitize_name,
    schema_type_str,
)


# ── infer_json_type ──────────────────────────

def test_infer_json_type_bool():
    assert infer_json_type(True) == "boolean"
    assert infer_json_type(False) == "boolean"


def test_infer_json_type_int():
    # bool is subclass of int in Python; bool check must come first
    assert infer_json_type(42) == "integer"


def test_infer_json_type_float():
    assert infer_json_type(3.14) == "number"


def test_infer_json_type_list():
    assert infer_json_type([1, 2, 3]) == "array"


def test_infer_json_type_dict():
    assert infer_json_type({"a": 1}) == "object"


def test_infer_json_type_string():
    assert infer_json_type("hello") == "string"
    assert infer_json_type(None) == "string"  # fallback


# ── schema_type_str ──────────────────────────

def test_schema_type_str_scalar():
    assert schema_type_str({"type": "integer"}) == "integer"
    assert schema_type_str({"type": "string"}) == "string"


def test_schema_type_str_array():
    assert schema_type_str({"type": "array", "items": {"type": "string"}}) == "array[string]"


def test_schema_type_str_array_of_objects():
    assert schema_type_str({"type": "array", "items": {"type": "object"}}) == "array[object]"


def test_schema_type_str_default():
    assert schema_type_str({}) == "object"


def test_schema_type_str_non_dict():
    assert schema_type_str(None) == "string"


# ── is_api_url ───────────────────────────────

def test_is_api_url_accepts_api_path():
    assert is_api_url("https://example.com/api/users")


def test_is_api_url_accepts_versioned():
    assert is_api_url("https://example.com/v1/things")
    assert is_api_url("https://example.com/v2/things")


def test_is_api_url_rejects_static_assets():
    assert not is_api_url("https://example.com/static/app.js")
    assert not is_api_url("https://example.com/logo.png")
    assert not is_api_url("https://example.com/style.css")


def test_is_api_url_rejects_nextjs_internal():
    assert not is_api_url("https://example.com/_next/static/chunks/foo.js")


def test_is_api_url_accepts_graphql():
    assert is_api_url("https://example.com/graphql")


# ── extract_tag_from_path ───────────────────

def test_extract_tag_skips_prefixes():
    assert extract_tag_from_path("/api/bo/v1/users/list") == "users"


def test_extract_tag_bare():
    assert extract_tag_from_path("/orders") == "orders"


def test_extract_tag_empty():
    assert extract_tag_from_path("") == "api"


# ── sanitize_name ───────────────────────────

def test_sanitize_name_basic():
    assert sanitize_name("getUser") == "getUser"


def test_sanitize_name_replaces_special_chars():
    assert sanitize_name("get-user.list") == "get_user_list"
    assert sanitize_name("GET/api/users") == "GET_api_users"


def test_sanitize_name_collapses_underscores():
    assert sanitize_name("foo---bar") == "foo_bar"


def test_sanitize_name_strips_edges():
    assert sanitize_name("_foo_") == "foo"


def test_sanitize_name_fallback():
    assert sanitize_name("!!!") == "unknown"


# ── normalize_path_params ───────────────────

def test_normalize_numeric_id():
    assert normalize_path_params("/api/users/123") == "/api/users/{id}"
    assert normalize_path_params("/api/users/123/posts") == "/api/users/{id}/posts"


def test_normalize_uuid():
    uid = "550e8400-e29b-41d4-a716-446655440000"
    assert normalize_path_params(f"/api/items/{uid}") == "/api/items/{uuid}"


def test_normalize_alphanumeric_code():
    assert normalize_path_params("/api/category/LA01010000") == "/api/category/{code}"


def test_normalize_leaves_normal_segments():
    assert normalize_path_params("/api/users/list") == "/api/users/list"


# ── build_params_from_json_schema ───────────

def test_build_params_basic():
    schema = {
        "type": "object",
        "properties": {
            "name": {"type": "string", "description": "User name"},
            "age": {"type": "integer"},
        },
        "required": ["name"],
    }
    params = build_params_from_json_schema(schema)
    by_name = {p.name: p for p in params}

    assert by_name["name"].type == "string"
    assert by_name["name"].required is True
    assert by_name["name"].description == "User name"
    assert by_name["age"].required is False


def test_build_params_with_enum_and_example():
    schema = {
        "type": "object",
        "properties": {
            "status": {
                "type": "string",
                "enum": ["ACTIVE", "INACTIVE"],
                "example": "ACTIVE",
            },
        },
    }
    params = build_params_from_json_schema(schema)
    assert params[0].enum == ["ACTIVE", "INACTIVE"]
    assert "example: ACTIVE" in params[0].description


def test_build_params_empty_schema():
    assert build_params_from_json_schema({}) == []
    assert build_params_from_json_schema({"type": "object"}) == []


def test_build_params_nested_object_kept_as_schema():
    schema = {
        "type": "object",
        "properties": {
            "address": {
                "type": "object",
                "properties": {"city": {"type": "string"}},
            },
        },
    }
    params = build_params_from_json_schema(schema)
    assert params[0].schema is not None
    assert params[0].schema["type"] == "object"
