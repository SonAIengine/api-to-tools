"""Tests for the OpenAPI parser using inline sample specs."""

import json

from api_to_tools.parsers.openapi import parse_openapi


MINIMAL_OPENAPI_3 = {
    "openapi": "3.0.0",
    "info": {"title": "Test", "version": "1.0"},
    "servers": [{"url": "https://api.example.com"}],
    "paths": {
        "/users/{id}": {
            "get": {
                "operationId": "getUser",
                "summary": "Get a user",
                "tags": ["users"],
                "parameters": [
                    {
                        "name": "id",
                        "in": "path",
                        "required": True,
                        "schema": {"type": "integer"},
                    }
                ],
                "responses": {
                    "200": {
                        "description": "OK",
                        "content": {
                            "application/json": {
                                "schema": {
                                    "type": "object",
                                    "properties": {
                                        "id": {"type": "integer"},
                                        "name": {"type": "string"},
                                    },
                                }
                            }
                        },
                    }
                },
            }
        },
        "/users": {
            "post": {
                "operationId": "createUser",
                "summary": "Create a user",
                "tags": ["users"],
                "requestBody": {
                    "required": True,
                    "content": {
                        "application/json": {
                            "schema": {
                                "type": "object",
                                "required": ["name", "email"],
                                "properties": {
                                    "name": {"type": "string", "description": "Full name"},
                                    "email": {"type": "string"},
                                    "role": {
                                        "type": "string",
                                        "enum": ["admin", "user"],
                                    },
                                },
                            }
                        }
                    },
                },
                "responses": {"201": {"description": "Created"}},
            }
        },
    },
}


SWAGGER_2_SAMPLE = {
    "swagger": "2.0",
    "info": {"title": "Legacy", "version": "1.0"},
    "host": "api.legacy.com",
    "basePath": "/v1",
    "schemes": ["https"],
    "paths": {
        "/items": {
            "get": {
                "operationId": "listItems",
                "parameters": [
                    {
                        "name": "status",
                        "in": "query",
                        "type": "string",
                        "enum": ["active", "inactive"],
                    }
                ],
                "responses": {
                    "200": {
                        "description": "OK",
                        "schema": {
                            "type": "object",
                            "properties": {
                                "items": {"type": "array"},
                                "total": {"type": "integer"},
                            },
                        },
                    }
                },
            },
            "post": {
                "operationId": "createItem",
                "parameters": [
                    {
                        "name": "body",
                        "in": "body",
                        "required": True,
                        "schema": {
                            "type": "object",
                            "required": ["name"],
                            "properties": {
                                "name": {"type": "string"},
                                "qty": {"type": "integer"},
                            },
                        },
                    }
                ],
                "responses": {"201": {"description": "Created"}},
            },
        }
    },
}


# ── OpenAPI 3.x ────────────────────────────

def test_openapi3_parses_both_operations():
    tools = parse_openapi(MINIMAL_OPENAPI_3)
    assert len(tools) == 2

    by_name = {t.name: t for t in tools}
    assert "getUser" in by_name
    assert "createUser" in by_name


def test_openapi3_extracts_path_param():
    tools = parse_openapi(MINIMAL_OPENAPI_3)
    get_user = next(t for t in tools if t.name == "getUser")
    id_param = next(p for p in get_user.parameters if p.name == "id")

    assert id_param.location == "path"
    assert id_param.required is True
    assert id_param.type == "integer"


def test_openapi3_extracts_body_params():
    tools = parse_openapi(MINIMAL_OPENAPI_3)
    create = next(t for t in tools if t.name == "createUser")
    by_name = {p.name: p for p in create.parameters}

    assert by_name["name"].type == "string"
    assert by_name["name"].required is True
    assert by_name["email"].required is True
    assert by_name["role"].enum == ["admin", "user"]


def test_openapi3_extracts_response_schema():
    tools = parse_openapi(MINIMAL_OPENAPI_3)
    get_user = next(t for t in tools if t.name == "getUser")
    assert get_user.metadata.get("response_schema") == {
        "id": "integer",
        "name": "string",
    }


def test_openapi3_endpoint_uses_server_url():
    tools = parse_openapi(MINIMAL_OPENAPI_3)
    get_user = next(t for t in tools if t.name == "getUser")
    assert get_user.endpoint == "https://api.example.com/users/{id}"


def test_openapi3_preserves_tags():
    tools = parse_openapi(MINIMAL_OPENAPI_3)
    for t in tools:
        assert "users" in t.tags


# ── Swagger 2.0 ────────────────────────────

def test_swagger2_parses_host_and_basepath():
    tools = parse_openapi(SWAGGER_2_SAMPLE)
    list_items = next(t for t in tools if t.name == "listItems")
    assert list_items.endpoint == "https://api.legacy.com/v1/items"


def test_swagger2_extracts_query_enum():
    tools = parse_openapi(SWAGGER_2_SAMPLE)
    list_items = next(t for t in tools if t.name == "listItems")
    status_param = next(p for p in list_items.parameters if p.name == "status")
    assert status_param.enum == ["active", "inactive"]
    assert status_param.location == "query"


def test_swagger2_extracts_body_in_body_param():
    """Swagger 2.0 uses parameters[].in='body' instead of requestBody."""
    tools = parse_openapi(SWAGGER_2_SAMPLE)
    create = next(t for t in tools if t.name == "createItem")
    body_fields = {p.name for p in create.parameters if p.location == "body"}

    assert "name" in body_fields
    assert "qty" in body_fields


def test_swagger2_extracts_response_schema_directly():
    """Swagger 2.0 has responses.200.schema, not content.*.schema."""
    tools = parse_openapi(SWAGGER_2_SAMPLE)
    list_items = next(t for t in tools if t.name == "listItems")
    rs = list_items.metadata.get("response_schema")
    assert rs is not None
    assert "items" in rs
    assert rs["total"] == "integer"


# ── JSON string input ─────────────────────

def test_parse_openapi_accepts_json_string():
    tools = parse_openapi(json.dumps(MINIMAL_OPENAPI_3))
    assert len(tools) == 2


# ── $ref resolution ───────────────────────

def test_ref_resolution_basic():
    spec = {
        "openapi": "3.0.0",
        "info": {"title": "T", "version": "1"},
        "servers": [{"url": "https://api.example.com"}],
        "components": {
            "schemas": {
                "User": {
                    "type": "object",
                    "properties": {
                        "id": {"type": "integer"},
                        "name": {"type": "string"},
                    },
                }
            }
        },
        "paths": {
            "/users": {
                "post": {
                    "operationId": "create",
                    "requestBody": {
                        "content": {
                            "application/json": {
                                "schema": {"$ref": "#/components/schemas/User"}
                            }
                        }
                    },
                    "responses": {"200": {"description": "ok"}},
                }
            }
        },
    }
    tools = parse_openapi(spec)
    create = tools[0]
    names = {p.name for p in create.parameters}
    assert "id" in names
    assert "name" in names


def test_ref_resolution_handles_circular():
    """Must not recurse infinitely on self-referencing schemas."""
    spec = {
        "openapi": "3.0.0",
        "info": {"title": "T", "version": "1"},
        "servers": [{"url": "https://api.example.com"}],
        "components": {
            "schemas": {
                "Node": {
                    "type": "object",
                    "properties": {
                        "name": {"type": "string"},
                        "child": {"$ref": "#/components/schemas/Node"},
                    },
                }
            }
        },
        "paths": {
            "/tree": {
                "get": {
                    "operationId": "getTree",
                    "responses": {
                        "200": {
                            "description": "ok",
                            "content": {
                                "application/json": {
                                    "schema": {"$ref": "#/components/schemas/Node"}
                                }
                            },
                        }
                    },
                }
            }
        },
    }
    tools = parse_openapi(spec)
    assert len(tools) == 1
    # response_schema should be present (doesn't infinite loop)
    assert tools[0].metadata.get("response_schema") is not None
