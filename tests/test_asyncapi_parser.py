"""Tests for AsyncAPI parser — pure function tests (no network)."""

from api_to_tools.parsers.asyncapi import (
    _extract_payload_schema,
    _get_server_url,
    _parse_v2,
    _parse_v3,
    _resolve_ref,
    parse_asyncapi,
)


# ──────────────────────────────────────────────
# Fixtures
# ──────────────────────────────────────────────

ASYNCAPI_V2_SPEC = {
    "asyncapi": "2.6.0",
    "info": {"title": "User Service", "version": "1.0.0"},
    "servers": {
        "production": {"url": "mqtt://broker.example.com", "protocol": "mqtt"},
    },
    "channels": {
        "user/created": {
            "publish": {
                "operationId": "onUserCreated",
                "summary": "User was created",
                "tags": [{"name": "user"}],
                "message": {
                    "payload": {
                        "type": "object",
                        "properties": {
                            "id": {"type": "integer"},
                            "name": {"type": "string"},
                            "email": {"type": "string"},
                        },
                        "required": ["id", "name"],
                    },
                },
            },
        },
        "user/{userId}/updated": {
            "parameters": {
                "userId": {
                    "description": "The user ID",
                    "schema": {"type": "string"},
                },
            },
            "subscribe": {
                "operationId": "subscribeUserUpdated",
                "summary": "Subscribe to user updates",
                "message": {
                    "payload": {
                        "type": "object",
                        "properties": {
                            "field": {"type": "string"},
                            "newValue": {"type": "string"},
                        },
                    },
                },
            },
        },
    },
}

ASYNCAPI_V2_WITH_REFS = {
    "asyncapi": "2.6.0",
    "info": {"title": "Test", "version": "1.0.0"},
    "channels": {
        "orders/new": {
            "publish": {
                "operationId": "onNewOrder",
                "message": {"$ref": "#/components/messages/NewOrder"},
            },
        },
    },
    "components": {
        "messages": {
            "NewOrder": {
                "name": "NewOrder",
                "payload": {
                    "$ref": "#/components/schemas/Order",
                },
            },
        },
        "schemas": {
            "Order": {
                "type": "object",
                "properties": {
                    "orderId": {"type": "string"},
                    "amount": {"type": "number"},
                },
                "required": ["orderId"],
            },
        },
    },
}

ASYNCAPI_V3_SPEC = {
    "asyncapi": "3.0.0",
    "info": {"title": "Notifications", "version": "2.0.0"},
    "servers": {
        "ws": {"host": "ws.example.com", "url": "wss://ws.example.com", "protocol": "websocket"},
    },
    "channels": {
        "notifications": {
            "address": "/notifications",
            "messages": {
                "Notification": {
                    "payload": {
                        "type": "object",
                        "properties": {
                            "title": {"type": "string"},
                            "body": {"type": "string"},
                            "level": {"type": "string", "enum": ["info", "warn", "error"]},
                        },
                        "required": ["title"],
                    },
                },
            },
        },
    },
    "operations": {
        "sendNotification": {
            "action": "send",
            "summary": "Send a notification",
            "channel": {"$ref": "#/channels/notifications"},
            "messages": [{"$ref": "#/channels/notifications/messages/Notification"}],
        },
        "receiveNotification": {
            "action": "receive",
            "summary": "Receive notifications",
            "channel": {"$ref": "#/channels/notifications"},
        },
    },
}


# ──────────────────────────────────────────────
# $ref resolution
# ──────────────────────────────────────────────

def test_resolve_ref():
    spec = {"components": {"schemas": {"User": {"type": "object"}}}}
    result = _resolve_ref(spec, "#/components/schemas/User")
    assert result == {"type": "object"}


def test_resolve_ref_missing():
    result = _resolve_ref({}, "#/components/schemas/Missing")
    assert result == {}


def test_resolve_ref_invalid():
    result = _resolve_ref({}, "not-a-ref")
    assert result == {}


# ──────────────────────────────────────────────
# Server URL
# ──────────────────────────────────────────────

def test_get_server_url():
    url = _get_server_url(ASYNCAPI_V2_SPEC)
    assert url == "mqtt://broker.example.com"


def test_get_server_url_empty():
    assert _get_server_url({}) == ""


# ──────────────────────────────────────────────
# Payload schema extraction
# ──────────────────────────────────────────────

def test_extract_payload_schema_direct():
    message = {"payload": {"type": "object", "properties": {"id": {"type": "integer"}}}}
    schema = _extract_payload_schema({}, message)
    assert schema["type"] == "object"
    assert "id" in schema["properties"]


def test_extract_payload_schema_ref():
    spec = ASYNCAPI_V2_WITH_REFS
    message = {"$ref": "#/components/messages/NewOrder"}
    schema = _extract_payload_schema(spec, message)
    assert schema is not None
    assert schema["type"] == "object"
    assert "orderId" in schema["properties"]


def test_extract_payload_schema_none():
    schema = _extract_payload_schema({}, {})
    assert schema is None


# ──────────────────────────────────────────────
# AsyncAPI v2 parsing
# ──────────────────────────────────────────────

def test_parse_v2_basic():
    tools = _parse_v2(ASYNCAPI_V2_SPEC)
    assert len(tools) == 2
    names = {t.name for t in tools}
    assert "onUserCreated" in names
    assert "subscribeUserUpdated" in names


def test_parse_v2_publish_tool():
    tools = _parse_v2(ASYNCAPI_V2_SPEC)
    pub = next(t for t in tools if t.name == "onUserCreated")
    assert pub.method == "PUBLISH"
    assert pub.protocol == "async"
    assert pub.description == "User was created"
    assert "user" in pub.tags
    # Check payload params
    param_names = {p.name for p in pub.parameters}
    assert "id" in param_names
    assert "name" in param_names
    assert "email" in param_names
    id_param = next(p for p in pub.parameters if p.name == "id")
    assert id_param.required is True


def test_parse_v2_subscribe_with_channel_params():
    tools = _parse_v2(ASYNCAPI_V2_SPEC)
    sub = next(t for t in tools if t.name == "subscribeUserUpdated")
    assert sub.method == "SUBSCRIBE"
    # Should have channel param + payload params
    path_params = [p for p in sub.parameters if p.location == "path"]
    assert len(path_params) == 1
    assert path_params[0].name == "userId"
    body_params = [p for p in sub.parameters if p.location == "body"]
    assert len(body_params) == 2


def test_parse_v2_endpoint():
    tools = _parse_v2(ASYNCAPI_V2_SPEC)
    pub = next(t for t in tools if t.name == "onUserCreated")
    assert pub.endpoint == "mqtt://broker.example.com/user/created"


def test_parse_v2_with_refs():
    tools = _parse_v2(ASYNCAPI_V2_WITH_REFS)
    assert len(tools) == 1
    tool = tools[0]
    assert tool.name == "onNewOrder"
    param_names = {p.name for p in tool.parameters}
    assert "orderId" in param_names
    assert "amount" in param_names
    orderId = next(p for p in tool.parameters if p.name == "orderId")
    assert orderId.required is True


def test_parse_v2_metadata():
    tools = _parse_v2(ASYNCAPI_V2_SPEC)
    pub = next(t for t in tools if t.name == "onUserCreated")
    assert pub.metadata["source"] == "asyncapi"
    assert pub.metadata["operation_type"] == "publish"
    assert "message_schema" in pub.metadata


# ──────────────────────────────────────────────
# AsyncAPI v3 parsing
# ──────────────────────────────────────────────

def test_parse_v3_basic():
    tools = _parse_v3(ASYNCAPI_V3_SPEC)
    assert len(tools) == 2
    names = {t.name for t in tools}
    assert "sendNotification" in names
    assert "receiveNotification" in names


def test_parse_v3_send():
    tools = _parse_v3(ASYNCAPI_V3_SPEC)
    send = next(t for t in tools if t.name == "sendNotification")
    assert send.method == "PUBLISH"
    assert send.description == "Send a notification"
    param_names = {p.name for p in send.parameters}
    assert "title" in param_names
    assert "body" in param_names


def test_parse_v3_receive():
    tools = _parse_v3(ASYNCAPI_V3_SPEC)
    recv = next(t for t in tools if t.name == "receiveNotification")
    assert recv.method == "SUBSCRIBE"


def test_parse_v3_endpoint():
    tools = _parse_v3(ASYNCAPI_V3_SPEC)
    send = next(t for t in tools if t.name == "sendNotification")
    assert send.endpoint == "wss://ws.example.com/notifications"


# ──────────────────────────────────────────────
# Top-level parse_asyncapi
# ──────────────────────────────────────────────

def test_parse_asyncapi_v2_dict():
    tools = parse_asyncapi(ASYNCAPI_V2_SPEC)
    assert len(tools) == 2


def test_parse_asyncapi_v3_dict():
    tools = parse_asyncapi(ASYNCAPI_V3_SPEC)
    assert len(tools) == 2


def test_parse_asyncapi_json_string():
    import json
    tools = parse_asyncapi(json.dumps(ASYNCAPI_V2_SPEC))
    assert len(tools) == 2


def test_parse_asyncapi_yaml_string():
    yaml_str = """
asyncapi: "2.6.0"
info:
  title: Test
  version: "1.0.0"
channels:
  events/test:
    publish:
      operationId: onTestEvent
      message:
        payload:
          type: object
          properties:
            data:
              type: string
"""
    tools = parse_asyncapi(yaml_str)
    assert len(tools) == 1
    assert tools[0].name == "onTestEvent"


def test_parse_asyncapi_empty():
    tools = parse_asyncapi({"asyncapi": "2.0.0", "channels": {}})
    assert tools == []
