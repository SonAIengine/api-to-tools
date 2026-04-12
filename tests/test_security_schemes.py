"""Tests for OpenAPI security scheme extraction."""

from api_to_tools.parsers.openapi import (
    extract_security_schemes,
    security_schemes_to_auth_configs,
    parse_openapi,
)


# ──────────────────────────────────────────────
# OpenAPI 3.x securitySchemes
# ──────────────────────────────────────────────

OPENAPI3_SPEC = {
    "openapi": "3.0.0",
    "info": {"title": "Test", "version": "1.0.0"},
    "components": {
        "securitySchemes": {
            "bearerAuth": {
                "type": "http",
                "scheme": "bearer",
                "bearerFormat": "JWT",
            },
            "basicAuth": {
                "type": "http",
                "scheme": "basic",
            },
            "apiKeyHeader": {
                "type": "apiKey",
                "in": "header",
                "name": "X-API-Key",
            },
            "apiKeyQuery": {
                "type": "apiKey",
                "in": "query",
                "name": "api_key",
            },
            "oauth2": {
                "type": "oauth2",
                "flows": {
                    "clientCredentials": {
                        "tokenUrl": "https://auth.example.com/token",
                        "scopes": {"read": "Read access", "write": "Write access"},
                    },
                },
            },
        },
    },
    "security": [{"bearerAuth": []}],
    "paths": {
        "/users": {
            "get": {
                "operationId": "listUsers",
                "summary": "List users",
                "responses": {"200": {"description": "OK"}},
            },
            "post": {
                "operationId": "createUser",
                "summary": "Create user",
                "security": [{"oauth2": ["write"]}],
                "responses": {"201": {"description": "Created"}},
            },
        },
        "/public": {
            "get": {
                "operationId": "publicEndpoint",
                "summary": "Public",
                "security": [],
                "responses": {"200": {"description": "OK"}},
            },
        },
    },
}


def test_extract_bearer():
    schemes = extract_security_schemes(OPENAPI3_SPEC)
    bearer = next(s for s in schemes if s.get("type") == "bearer")
    assert bearer["_scheme_name"] == "bearerAuth"
    assert bearer["_bearer_format"] == "JWT"


def test_extract_basic():
    schemes = extract_security_schemes(OPENAPI3_SPEC)
    basic = next(s for s in schemes if s.get("type") == "basic")
    assert basic["_scheme_name"] == "basicAuth"


def test_extract_api_key_header():
    schemes = extract_security_schemes(OPENAPI3_SPEC)
    api_key = next(s for s in schemes if s.get("_scheme_name") == "apiKeyHeader")
    assert api_key["type"] == "api_key"
    assert api_key["key"] == "X-API-Key"
    assert api_key["location"] == "header"


def test_extract_api_key_query():
    schemes = extract_security_schemes(OPENAPI3_SPEC)
    api_key = next(s for s in schemes if s.get("_scheme_name") == "apiKeyQuery")
    assert api_key["type"] == "api_key"
    assert api_key["key"] == "api_key"
    assert api_key["location"] == "query"


def test_extract_oauth2():
    schemes = extract_security_schemes(OPENAPI3_SPEC)
    oauth = next(s for s in schemes if s.get("type") == "oauth2_client")
    assert oauth["token_url"] == "https://auth.example.com/token"
    assert "read" in oauth["scope"]
    assert "write" in oauth["scope"]


def test_extract_count():
    schemes = extract_security_schemes(OPENAPI3_SPEC)
    assert len(schemes) == 5


# ──────────────────────────────────────────────
# Swagger 2.x securityDefinitions
# ──────────────────────────────────────────────

SWAGGER2_SPEC = {
    "swagger": "2.0",
    "info": {"title": "Test", "version": "1.0.0"},
    "securityDefinitions": {
        "basicAuth": {"type": "basic"},
        "apiKey": {"type": "apiKey", "in": "header", "name": "Authorization"},
    },
    "paths": {},
}


def test_extract_swagger2_basic():
    schemes = extract_security_schemes(SWAGGER2_SPEC)
    basic = next(s for s in schemes if s.get("type") == "basic")
    assert basic["_scheme_name"] == "basicAuth"


def test_extract_swagger2_api_key():
    schemes = extract_security_schemes(SWAGGER2_SPEC)
    api_key = next(s for s in schemes if s.get("type") == "api_key")
    assert api_key["key"] == "Authorization"


# ──────────────────────────────────────────────
# security_schemes_to_auth_configs
# ──────────────────────────────────────────────

def test_to_auth_configs():
    configs = security_schemes_to_auth_configs(OPENAPI3_SPEC)
    types = {c.type for c in configs}
    assert "bearer" in types
    assert "basic" in types
    assert "api_key" in types
    assert "oauth2_client" in types


def test_to_auth_configs_oauth_has_token_url():
    configs = security_schemes_to_auth_configs(OPENAPI3_SPEC)
    oauth = next(c for c in configs if c.type == "oauth2_client")
    assert oauth.token_url == "https://auth.example.com/token"
    assert "read" in oauth.scope


def test_to_auth_configs_api_key():
    configs = security_schemes_to_auth_configs(OPENAPI3_SPEC)
    api_keys = [c for c in configs if c.type == "api_key"]
    assert len(api_keys) == 2
    names = {c.key for c in api_keys}
    assert names == {"X-API-Key", "api_key"}


# ──────────────────────────────────────────────
# Integration: parse_openapi metadata
# ──────────────────────────────────────────────

def test_parse_openapi_attaches_security():
    tools = parse_openapi(OPENAPI3_SPEC)
    # listUsers uses global security (bearerAuth)
    list_users = next(t for t in tools if t.name == "listUsers")
    assert "security_schemes" in list_users.metadata
    scheme_names = {s["_scheme_name"] for s in list_users.metadata["security_schemes"]}
    assert "bearerAuth" in scheme_names


def test_parse_openapi_operation_level_security():
    tools = parse_openapi(OPENAPI3_SPEC)
    # createUser has operation-level security (oauth2)
    create_user = next(t for t in tools if t.name == "createUser")
    assert "security_schemes" in create_user.metadata
    scheme_names = {s["_scheme_name"] for s in create_user.metadata["security_schemes"]}
    assert "oauth2" in scheme_names
    assert "bearerAuth" not in scheme_names


def test_parse_openapi_no_security():
    tools = parse_openapi(OPENAPI3_SPEC)
    # publicEndpoint has security: [] (explicitly no auth)
    public = next(t for t in tools if t.name == "publicEndpoint")
    assert "security_schemes" not in public.metadata


def test_parse_openapi_empty_security_schemes():
    spec = {
        "openapi": "3.0.0",
        "info": {"title": "Test", "version": "1.0.0"},
        "paths": {
            "/data": {
                "get": {
                    "operationId": "getData",
                    "responses": {"200": {"description": "OK"}},
                },
            },
        },
    }
    tools = parse_openapi(spec)
    assert "security_schemes" not in tools[0].metadata
