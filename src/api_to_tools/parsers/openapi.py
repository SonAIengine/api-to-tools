"""OpenAPI 2.0/3.0/3.1 parser."""

from __future__ import annotations

import json
import re
from urllib.parse import urlparse

import httpx
import yaml

from api_to_tools.types import Tool, ToolParameter, ResponseFormat


def _resolve_refs(spec: dict, root: dict | None = None) -> dict:
    """Simple $ref resolver (single-level)."""
    if root is None:
        root = spec
    if isinstance(spec, dict):
        if "$ref" in spec:
            ref_path = spec["$ref"].lstrip("#/").split("/")
            resolved = root
            for part in ref_path:
                resolved = resolved.get(part, {})
            return _resolve_refs(resolved, root)
        return {k: _resolve_refs(v, root) for k, v in spec.items()}
    if isinstance(spec, list):
        return [_resolve_refs(item, root) for item in spec]
    return spec


def _get_base_url(spec: dict, source_url: str | None = None) -> str:
    """Extract base URL from spec."""
    # OpenAPI 3.x
    servers = spec.get("servers", [])
    if servers:
        server_url = servers[0].get("url", "")
        if server_url.startswith("/") and source_url:
            parsed = urlparse(source_url)
            return f"{parsed.scheme}://{parsed.netloc}{server_url}"
        if server_url.startswith("http"):
            return server_url

    # Swagger 2.0
    host = spec.get("host")
    if host:
        scheme = (spec.get("schemes") or ["https"])[0]
        base_path = spec.get("basePath", "")
        return f"{scheme}://{host}{base_path}"

    # Fallback
    if source_url:
        parsed = urlparse(source_url)
        return f"{parsed.scheme}://{parsed.netloc}"
    return ""


def _detect_response_format(responses: dict | None) -> ResponseFormat:
    if not responses:
        return "json"
    success = responses.get("200") or responses.get("201") or next(iter(responses.values()), {})
    content = success.get("content", {}) if isinstance(success, dict) else {}
    if any("xml" in ct for ct in content):
        return "xml"
    return "json"


def _schema_to_params(schema: dict) -> list[ToolParameter]:
    properties = schema.get("properties", {})
    required_fields = schema.get("required", [])
    params = []
    for name, prop in properties.items():
        params.append(ToolParameter(
            name=name,
            type=prop.get("type", "string"),
            required=name in required_fields,
            location="body",
            description=prop.get("description"),
            enum=prop.get("enum"),
            default=prop.get("default"),
            schema=prop if prop.get("type") == "object" and prop.get("properties") else None,
        ))
    return params


def _extract_params(operation: dict) -> list[ToolParameter]:
    params: list[ToolParameter] = []

    # Path/query/header params
    for p in operation.get("parameters", []):
        schema = p.get("schema", {})
        params.append(ToolParameter(
            name=p["name"],
            type=schema.get("type") or p.get("type", "string"),
            required=p.get("required", p.get("in") == "path"),
            location=p.get("in"),
            description=p.get("description"),
            enum=schema.get("enum") or p.get("enum"),
        ))

    # Request body (OpenAPI 3.x)
    request_body = operation.get("requestBody", {})
    content = request_body.get("content", {})
    media = content.get("application/json") or content.get("application/xml") or next(iter(content.values()), {})
    schema = media.get("schema", {}) if media else {}
    if schema:
        body_params = _schema_to_params(schema)
        if body_params:
            params.extend(body_params)
        elif schema.get("type"):
            params.append(ToolParameter(
                name="body",
                type=schema.get("type", "object"),
                required=request_body.get("required", False),
                location="body",
                schema=schema,
            ))

    return params


def _sanitize_name(method: str, path: str) -> str:
    name = f"{method}{path}"
    name = re.sub(r"[{}]", "", name)
    name = re.sub(r"[^a-zA-Z0-9]", "_", name)
    name = re.sub(r"_+", "_", name)
    return name.strip("_")


def parse_openapi(input_data: str | dict, source_url: str | None = None) -> list[Tool]:
    """Parse OpenAPI/Swagger spec into tools."""
    if isinstance(input_data, str):
        if input_data.startswith("http://") or input_data.startswith("https://"):
            res = httpx.get(input_data, follow_redirects=True, timeout=30)
            input_data = res.text
            source_url = source_url or res.url.__str__()

        # Try JSON, then YAML
        try:
            spec = json.loads(input_data)
        except json.JSONDecodeError:
            spec = yaml.safe_load(input_data)
    else:
        spec = input_data

    # Resolve $ref
    spec = _resolve_refs(spec)

    base_url = _get_base_url(spec, source_url)
    http_methods = {"get", "post", "put", "patch", "delete", "head", "options"}
    tools: list[Tool] = []

    for path, methods in spec.get("paths", {}).items():
        if not isinstance(methods, dict):
            continue
        for method, operation in methods.items():
            if method not in http_methods or not isinstance(operation, dict):
                continue

            name = operation.get("operationId") or _sanitize_name(method, path)
            tools.append(Tool(
                name=name,
                description=operation.get("summary") or operation.get("description") or f"{method.upper()} {path}",
                parameters=_extract_params(operation),
                endpoint=f"{base_url}{path}",
                method=method.upper(),
                protocol="rest",
                response_format=_detect_response_format(operation.get("responses")),
                tags=operation.get("tags", []),
            ))

    return tools
