"""Tests for HAR parser."""

import json


from api_to_tools.parsers.har import (
    _build_tool_name,
    _extract_body_params,
    _extract_path_params,
    _extract_query_params,
    _infer_response_schema,
    _infer_type_from_string,
    _is_api_entry,
    _schema_from_value,
    parse_har,
)


# ──────────────────────────────────────────────
# Fixtures
# ──────────────────────────────────────────────

def _make_entry(
    method: str = "GET",
    url: str = "https://api.example.com/api/v1/users",
    status: int = 200,
    resp_mime: str = "application/json",
    resp_body: str | None = None,
    req_mime: str = "",
    req_body: str | None = None,
    query_string: list | None = None,
) -> dict:
    entry = {
        "request": {
            "method": method,
            "url": url,
            "headers": [],
            "queryString": query_string or [],
        },
        "response": {
            "status": status,
            "content": {
                "mimeType": resp_mime,
                "text": resp_body or "",
            },
        },
    }
    if req_body is not None:
        entry["request"]["postData"] = {
            "mimeType": req_mime or "application/json",
            "text": req_body,
        }
    if req_mime and not req_body:
        entry["request"]["headers"].append({"name": "Content-Type", "value": req_mime})
    return entry


def _make_har(*entries: dict) -> dict:
    return {"log": {"version": "1.2", "entries": list(entries)}}


# ──────────────────────────────────────────────
# _is_api_entry
# ──────────────────────────────────────────────

def test_is_api_entry_json_response():
    entry = _make_entry(resp_mime="application/json")
    assert _is_api_entry(entry) is True


def test_is_api_entry_rejects_static():
    entry = _make_entry(url="https://example.com/bundle.js")
    assert _is_api_entry(entry) is False


def test_is_api_entry_rejects_css():
    entry = _make_entry(url="https://example.com/style.css")
    assert _is_api_entry(entry) is False


def test_is_api_entry_rejects_image():
    entry = _make_entry(url="https://example.com/logo.png")
    assert _is_api_entry(entry) is False


def test_is_api_entry_rejects_options():
    entry = _make_entry(method="OPTIONS")
    assert _is_api_entry(entry) is False


def test_is_api_entry_rejects_redirect():
    entry = _make_entry(status=302)
    assert _is_api_entry(entry) is False


def test_is_api_entry_accepts_html_with_api_path():
    entry = _make_entry(url="https://example.com/api/v1/data", resp_mime="text/html")
    assert _is_api_entry(entry) is True


def test_is_api_entry_accepts_json_post():
    entry = _make_entry(
        method="POST",
        url="https://example.com/submit",
        resp_mime="text/plain",
        req_mime="application/json",
    )
    assert _is_api_entry(entry) is True


def test_is_api_entry_rejects_nextjs():
    entry = _make_entry(url="https://example.com/_next/data/abc.json", resp_mime="application/json")
    assert _is_api_entry(entry) is False


# ──────────────────────────────────────────────
# Type inference
# ──────────────────────────────────────────────

def test_infer_type_integer():
    assert _infer_type_from_string("42") == "integer"


def test_infer_type_float():
    assert _infer_type_from_string("3.14") == "number"


def test_infer_type_boolean():
    assert _infer_type_from_string("true") == "boolean"
    assert _infer_type_from_string("false") == "boolean"


def test_infer_type_string():
    assert _infer_type_from_string("hello") == "string"


def test_infer_type_empty():
    assert _infer_type_from_string("") == "string"


# ──────────────────────────────────────────────
# Path params
# ──────────────────────────────────────────────

def test_extract_path_params():
    params = _extract_path_params("/users/{id}/posts/{code}")
    assert len(params) == 2
    assert params[0].name == "id"
    assert params[0].location == "path"
    assert params[0].required is True
    assert params[1].name == "code"


def test_extract_path_params_none():
    assert _extract_path_params("/users/list") == []


# ──────────────────────────────────────────────
# Query params
# ──────────────────────────────────────────────

def test_extract_query_params_merges():
    entries = [
        _make_entry(query_string=[{"name": "page", "value": "1"}, {"name": "size", "value": "10"}]),
        _make_entry(query_string=[{"name": "page", "value": "2"}, {"name": "size", "value": "10"}]),
    ]
    params = _extract_query_params(entries)
    names = {p.name for p in params}
    assert names == {"page", "size"}
    page_param = next(p for p in params if p.name == "page")
    assert page_param.type == "integer"
    assert page_param.required is True


def test_extract_query_params_optional():
    entries = [
        _make_entry(query_string=[{"name": "q", "value": "search"}]),
        _make_entry(query_string=[]),
    ]
    params = _extract_query_params(entries)
    q_param = next(p for p in params if p.name == "q")
    assert q_param.required is False


# ──────────────────────────────────────────────
# Body params
# ──────────────────────────────────────────────

def test_extract_body_params_json():
    entries = [
        _make_entry(
            method="POST",
            req_mime="application/json",
            req_body='{"name": "Alice", "age": 30, "active": true}',
        ),
    ]
    params = _extract_body_params(entries)
    names = {p.name for p in params}
    assert names == {"name", "age", "active"}
    age_param = next(p for p in params if p.name == "age")
    assert age_param.type == "integer"
    active_param = next(p for p in params if p.name == "active")
    assert active_param.type == "boolean"


def test_extract_body_params_form():
    entries = [
        {
            "request": {
                "method": "POST",
                "url": "https://example.com/login",
                "headers": [],
                "queryString": [],
                "postData": {
                    "mimeType": "application/x-www-form-urlencoded",
                    "params": [
                        {"name": "username", "value": "admin"},
                        {"name": "password", "value": "secret"},
                    ],
                },
            },
            "response": {"status": 200, "content": {"mimeType": "application/json", "text": "{}"}},
        }
    ]
    params = _extract_body_params(entries)
    names = {p.name for p in params}
    assert names == {"username", "password"}


def test_extract_body_params_empty():
    entries = [_make_entry(method="GET")]
    assert _extract_body_params(entries) == []


# ──────────────────────────────────────────────
# Response schema inference
# ──────────────────────────────────────────────

def test_infer_response_schema_object():
    entries = [
        _make_entry(resp_body='{"id": 1, "name": "Alice", "tags": ["a", "b"]}'),
    ]
    schema = _infer_response_schema(entries)
    assert schema is not None
    assert schema["type"] == "object"
    assert "id" in schema["properties"]
    assert schema["properties"]["id"]["type"] == "integer"
    assert schema["properties"]["tags"]["type"] == "array"


def test_infer_response_schema_array():
    entries = [
        _make_entry(resp_body='[{"id": 1}, {"id": 2}]'),
    ]
    schema = _infer_response_schema(entries)
    assert schema["type"] == "array"
    assert schema["items"]["type"] == "object"


def test_infer_response_schema_skips_errors():
    entries = [
        _make_entry(status=500, resp_body='{"error": "fail"}'),
        _make_entry(status=200, resp_body='{"ok": true}'),
    ]
    schema = _infer_response_schema(entries)
    assert "ok" in schema["properties"]


def test_infer_response_schema_none():
    entries = [_make_entry(resp_body="not json", resp_mime="text/plain")]
    assert _infer_response_schema(entries) is None


# ──────────────────────────────────────────────
# Schema from value
# ──────────────────────────────────────────────

def test_schema_from_value_nested():
    schema = _schema_from_value({"user": {"name": "Alice", "age": 30}})
    assert schema["properties"]["user"]["type"] == "object"
    assert schema["properties"]["user"]["properties"]["name"]["type"] == "string"


# ──────────────────────────────────────────────
# Tool name generation
# ──────────────────────────────────────────────

def test_build_tool_name_basic():
    assert _build_tool_name("GET", "/api/v1/users") == "get_users"


def test_build_tool_name_nested():
    assert _build_tool_name("POST", "/api/v1/users/{id}/posts") == "post_users_posts"


def test_build_tool_name_root():
    assert _build_tool_name("GET", "/") == "get_root"


# ──────────────────────────────────────────────
# Full parse_har
# ──────────────────────────────────────────────

def test_parse_har_basic():
    har = _make_har(
        _make_entry(
            method="GET",
            url="https://api.example.com/api/v1/users?page=1",
            query_string=[{"name": "page", "value": "1"}],
            resp_body='[{"id": 1, "name": "Alice"}]',
        ),
        _make_entry(
            method="POST",
            url="https://api.example.com/api/v1/users",
            req_mime="application/json",
            req_body='{"name": "Bob", "email": "bob@example.com"}',
            resp_body='{"id": 2, "name": "Bob"}',
        ),
    )
    tools = parse_har(har)
    assert len(tools) == 2
    names = {t.name for t in tools}
    assert "get_users" in names
    assert "post_users" in names

    get_tool = next(t for t in tools if t.name == "get_users")
    assert get_tool.method == "GET"
    assert any(p.name == "page" for p in get_tool.parameters)
    assert get_tool.metadata.get("source") == "har"

    post_tool = next(t for t in tools if t.name == "post_users")
    assert post_tool.method == "POST"
    assert any(p.name == "name" for p in post_tool.parameters)
    assert any(p.name == "email" for p in post_tool.parameters)


def test_parse_har_groups_by_path():
    """Multiple calls to the same endpoint should merge into one tool."""
    har = _make_har(
        _make_entry(url="https://api.example.com/api/v1/users?page=1",
                     query_string=[{"name": "page", "value": "1"}]),
        _make_entry(url="https://api.example.com/api/v1/users?page=2",
                     query_string=[{"name": "page", "value": "2"}]),
    )
    tools = parse_har(har)
    assert len(tools) == 1
    assert tools[0].metadata["sample_count"] == 2


def test_parse_har_normalizes_ids():
    """Numeric IDs in paths should become {id} placeholders."""
    har = _make_har(
        _make_entry(url="https://api.example.com/api/v1/users/123"),
        _make_entry(url="https://api.example.com/api/v1/users/456"),
    )
    tools = parse_har(har)
    assert len(tools) == 1
    assert "{id}" in tools[0].endpoint
    assert any(p.name == "id" and p.location == "path" for p in tools[0].parameters)


def test_parse_har_filters_static():
    """Static assets should be excluded."""
    har = _make_har(
        _make_entry(url="https://example.com/bundle.js", resp_mime="application/javascript"),
        _make_entry(url="https://example.com/style.css", resp_mime="text/css"),
        _make_entry(url="https://api.example.com/api/v1/data", resp_mime="application/json",
                     resp_body='{"ok": true}'),
    )
    tools = parse_har(har)
    assert len(tools) == 1
    assert tools[0].name == "get_data"


def test_parse_har_empty():
    har = _make_har()
    tools = parse_har(har)
    assert tools == []


def test_parse_har_json_string():
    """parse_har should accept a JSON string."""
    har = _make_har(
        _make_entry(resp_body='{"status": "ok"}'),
    )
    tools = parse_har(json.dumps(har))
    assert len(tools) == 1


def test_parse_har_response_schema():
    """Response schema should be inferred and stored in metadata."""
    har = _make_har(
        _make_entry(resp_body='{"id": 1, "name": "Alice", "active": true}'),
    )
    tools = parse_har(har)
    schema = tools[0].metadata.get("response_schema")
    assert schema is not None
    assert schema["type"] == "object"
    assert "id" in schema["properties"]


def test_parse_har_deduplicates_names():
    """Tools with the same generated name should get numbered suffixes."""
    har = _make_har(
        _make_entry(method="GET", url="https://api.example.com/api/v1/users",
                     resp_body='[{"id": 1}]'),
        _make_entry(method="GET", url="https://other.example.com/api/v1/users",
                     resp_body='[{"id": 2}]'),
    )
    tools = parse_har(har)
    assert len(tools) == 2
    names = {t.name for t in tools}
    assert len(names) == 2  # no duplicates
