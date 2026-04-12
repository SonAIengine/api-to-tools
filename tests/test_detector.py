"""Tests for detector — _detect_from_content (pure function)."""

from api_to_tools.detector import _detect_from_content


# ──────────────────────────────────────────────
# OpenAPI / Swagger
# ──────────────────────────────────────────────

def test_detect_openapi_json():
    content = '{"openapi": "3.0.0", "info": {}, "paths": {}}'
    assert _detect_from_content(content, "application/json") == "openapi"


def test_detect_swagger_json():
    content = '{"swagger": "2.0", "info": {}, "paths": {}}'
    assert _detect_from_content(content, "application/json") == "openapi"


def test_detect_openapi_yaml():
    content = "openapi: 3.0.0\ninfo:\n  title: Test"
    assert _detect_from_content(content, "text/yaml") == "openapi"


def test_detect_swagger_yaml():
    content = "swagger: '2.0'\ninfo:\n  title: Test"
    assert _detect_from_content(content, "text/yaml") == "openapi"


# ──────────────────────────────────────────────
# AsyncAPI
# ──────────────────────────────────────────────

def test_detect_asyncapi_json():
    content = '{"asyncapi": "2.0.0", "info": {}}'
    assert _detect_from_content(content, "application/json") == "asyncapi"


def test_detect_asyncapi_yaml():
    content = "asyncapi: 2.0.0\ninfo:\n  title: Test"
    assert _detect_from_content(content, "text/yaml") == "asyncapi"


# ──────────────────────────────────────────────
# GraphQL
# ──────────────────────────────────────────────

def test_detect_graphql():
    content = '{"data": {"__schema": {"types": []}}}'
    assert _detect_from_content(content, "application/json") == "graphql"


# ──────────────────────────────────────────────
# WSDL
# ──────────────────────────────────────────────

def test_detect_wsdl():
    content = '<?xml version="1.0"?><definitions xmlns="http://schemas.xmlsoap.org/wsdl/"></definitions>'
    assert _detect_from_content(content, "text/xml") == "wsdl"


def test_detect_wsdl_prefixed():
    content = '<?xml version="1.0"?><wsdl:definitions></wsdl:definitions>'
    assert _detect_from_content(content, "text/xml") == "wsdl"


# ──────────────────────────────────────────────
# HAR
# ──────────────────────────────────────────────

def test_detect_har():
    content = '{"log": {"version": "1.2", "entries": []}}'
    assert _detect_from_content(content, "application/json") == "har"


# ──────────────────────────────────────────────
# Unknown / None
# ──────────────────────────────────────────────

def test_detect_unknown_json():
    content = '{"some": "random", "data": "here"}'
    assert _detect_from_content(content, "application/json") is None


def test_detect_unknown_text():
    content = "Hello world"
    assert _detect_from_content(content, "text/plain") is None


def test_detect_invalid_json():
    content = "{not valid json"
    assert _detect_from_content(content, "application/json") is None


def test_detect_empty():
    assert _detect_from_content("", "") is None
