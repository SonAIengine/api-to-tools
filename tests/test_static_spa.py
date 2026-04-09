"""Tests for the static SPA scanner (no network)."""

from api_to_tools.parsers.static_spa import (
    _infer_method_from_path,
    _looks_like_api_path,
    _normalize_template_expressions,
    _walk_back_for_method,
    _walk_forward_for_body,
    extract_api_calls_from_js,
)


# ── URL classification ──────────────────────

def test_looks_like_api_rejects_static():
    assert not _looks_like_api_path("/static/app.js")
    assert not _looks_like_api_path("/logo.png")


def test_looks_like_api_accepts_api_prefix():
    assert _looks_like_api_path("/api/users")
    assert _looks_like_api_path("/api/v1/orders")


def test_looks_like_api_accepts_versioned():
    assert _looks_like_api_path("/v1/things")


# ── Template expression normalization ──────

def test_normalize_identifier_template():
    assert _normalize_template_expressions("/api/${id}") == "/api/{id}"


def test_normalize_property_access():
    assert _normalize_template_expressions("/api/${obj.prop}") == "/api/{prop}"


def test_normalize_complex_expression():
    assert _normalize_template_expressions("/api/${fn()+x}") == "/api/{param}"


def test_normalize_multiple():
    assert (
        _normalize_template_expressions("/api/${v}/items/${id}")
        == "/api/{v}/items/{id}"
    )


# ── Method inference from path ─────────────

def test_infer_get_from_get_prefix():
    assert _infer_method_from_path("/api/getUserList") == "GET"


def test_infer_delete_from_remove():
    assert _infer_method_from_path("/api/removeItem") == "DELETE"


def test_infer_post_from_save():
    assert _infer_method_from_path("/api/saveOrder") == "POST"


def test_infer_put_from_update():
    assert _infer_method_from_path("/api/updateItem") == "PUT"


def test_infer_default():
    assert _infer_method_from_path("/api/xyz") == "GET"


# ── Method backwalk ────────────────────────

def test_walk_back_axios_get():
    js = 'return axios.get("/api/users")'
    pos = js.index('"/api/users"')
    method, is_fetch = _walk_back_for_method(js, pos)
    assert method == "GET"
    assert is_fetch is False


def test_walk_back_axios_post():
    js = 'client.post("/api/save", data)'
    pos = js.index('"/api/save"')
    method, is_fetch = _walk_back_for_method(js, pos)
    assert method == "POST"


def test_walk_back_fetch():
    js = 'fetch("/api/users")'
    pos = js.index('"/api/users"')
    method, is_fetch = _walk_back_for_method(js, pos)
    assert method == "GET"  # default for fetch
    assert is_fetch is True


def test_walk_back_no_hint():
    js = 'const url="/api/users"'
    pos = js.index('"/api/users"')
    method, is_fetch = _walk_back_for_method(js, pos)
    assert method is None


# ── Body object extraction ─────────────────

def test_walk_forward_extracts_body_keys():
    js = 'axios.post("/api/x", { name, email, age: 20 })'
    pos = js.index('"/api/x"') + len('"/api/x"')
    method, keys = _walk_forward_for_body(js, pos)
    assert set(keys) == {"name", "email", "age"}


def test_walk_forward_method_override():
    js = 'fetch("/api/x", { method: "POST", body: data })'
    pos = js.index('"/api/x"') + len('"/api/x"')
    method, keys = _walk_forward_for_body(js, pos)
    assert method == "POST"


def test_walk_forward_no_body():
    js = 'axios.get("/api/list")'
    pos = js.index('"/api/list"') + len('"/api/list"')
    method, keys = _walk_forward_for_body(js, pos)
    assert method is None
    assert keys == []


# ── Full extraction pipeline ───────────────

def test_extract_simple_get():
    js = '''
    function loadUsers() {
        return axios.get("/api/v1/users");
    }
    '''
    calls = extract_api_calls_from_js(js)
    assert len(calls) == 1
    assert calls[0]["method"] == "GET"
    assert calls[0]["url"] == "/api/v1/users"


def test_extract_post_with_body():
    js = '''
    axios.post("/api/v1/users", { name: "foo", email: "bar" })
    '''
    calls = extract_api_calls_from_js(js)
    assert len(calls) == 1
    assert calls[0]["method"] == "POST"
    assert set(calls[0]["body_params"]) == {"name", "email"}


def test_extract_template_literal():
    js = 'axios.get(`/api/users/${userId}/posts`)'
    calls = extract_api_calls_from_js(js)
    assert len(calls) == 1
    assert calls[0]["url"] == "/api/users/{userId}/posts"


def test_extract_multiple_in_one_file():
    js = '''
    function x() {
        axios.get("/api/v1/items");
        axios.post("/api/v1/items", { name });
        axios.delete("/api/v1/items/${id}");
    }
    '''
    calls = extract_api_calls_from_js(js)
    methods = {c["method"] for c in calls}
    assert "GET" in methods
    assert "POST" in methods
    assert "DELETE" in methods


def test_extract_fetch_with_method_option():
    js = 'fetch("/api/v1/items", { method: "PUT", body: JSON.stringify(x) })'
    calls = extract_api_calls_from_js(js)
    assert len(calls) == 1
    assert calls[0]["method"] == "PUT"


def test_extract_ignores_static_files():
    js = '''
    import "/api/lib.js";
    import "/v1/style.css";
    '''
    calls = extract_api_calls_from_js(js)
    # Static asset URLs should not be picked up as API calls
    for c in calls:
        assert not c["url"].endswith(".js")
        assert not c["url"].endswith(".css")


def test_extract_minified_code():
    """Minified ES2020+ code must not crash the scanner."""
    js = 'const a=x?.y?.z;const b=[...arr];e.get("/api/v1/z")'
    calls = extract_api_calls_from_js(js)
    assert any(c["url"] == "/api/v1/z" for c in calls)
