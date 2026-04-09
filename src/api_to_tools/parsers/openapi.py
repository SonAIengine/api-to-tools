"""OpenAPI 2.0/3.0/3.1 parser."""

from __future__ import annotations

import json
import re
from urllib.parse import urlparse

import httpx
import yaml

from api_to_tools.types import Tool, ToolParameter, ResponseFormat


# ──────────────────────────────────────────────
# $ref resolver with circular reference detection
# ──────────────────────────────────────────────

def _resolve_ref(ref_string: str, root: dict) -> dict:
    """Resolve a single $ref string against the root spec."""
    path = ref_string.lstrip("#/").split("/")
    current = root
    for part in path:
        if isinstance(current, dict):
            current = current.get(part, {})
        else:
            return {}
    return current if isinstance(current, dict) else {}


def _resolve_schema(schema, root: dict, visited: set | None = None, max_depth: int = 5) -> dict:
    """Resolve a schema, handling $ref and circular references.

    Unlike the old global resolve, this only resolves schemas on-demand
    and tracks visited refs to avoid infinite loops.
    """
    if visited is None:
        visited = set()
    if not isinstance(schema, dict):
        return schema if isinstance(schema, dict) else {}
    if not schema:
        return {}

    # Handle $ref
    if "$ref" in schema:
        ref = schema["$ref"]
        if ref in visited or max_depth <= 0:
            return {"type": "object", "description": f"(circular ref: {ref.split('/')[-1]})"}
        visited = visited | {ref}
        resolved = _resolve_ref(ref, root)
        return _resolve_schema(resolved, root, visited, max_depth - 1)

    result = dict(schema)

    # Resolve nested properties
    if "properties" in result and isinstance(result["properties"], dict):
        resolved_props = {}
        for name, prop in result["properties"].items():
            resolved_props[name] = _resolve_schema(prop, root, visited, max_depth - 1)
        result["properties"] = resolved_props

    # Resolve items (arrays)
    if "items" in result and isinstance(result["items"], dict):
        result["items"] = _resolve_schema(result["items"], root, visited, max_depth - 1)

    # Resolve additionalProperties
    if "additionalProperties" in result and isinstance(result["additionalProperties"], dict):
        result["additionalProperties"] = _resolve_schema(
            result["additionalProperties"], root, visited, max_depth - 1
        )

    # Resolve allOf / oneOf / anyOf
    for key in ("allOf", "oneOf", "anyOf"):
        if key in result and isinstance(result[key], list):
            result[key] = [_resolve_schema(s, root, visited, max_depth - 1) for s in result[key]]
            # Merge allOf into flat properties
            if key == "allOf":
                merged = {}
                merged_required = []
                for sub in result[key]:
                    if isinstance(sub, dict):
                        merged.update(sub.get("properties", {}))
                        merged_required.extend(sub.get("required", []))
                if merged:
                    result["properties"] = {**result.get("properties", {}), **merged}
                    result["required"] = list(set(result.get("required", []) + merged_required))

    return result


# ──────────────────────────────────────────────
# Schema → ToolParameter extraction
# ──────────────────────────────────────────────

def _schema_type_str(schema: dict) -> str:
    """Get a human-readable type string from a schema."""
    t = schema.get("type", "object")
    if t == "array":
        items = schema.get("items", {})
        item_type = items.get("type", "object")
        return f"array[{item_type}]"
    return t


def _schema_to_params(schema: dict, location: str = "body") -> list[ToolParameter]:
    """Convert a resolved schema's properties into ToolParameters."""
    if not isinstance(schema, dict):
        return []

    properties = schema.get("properties", {})
    required_fields = set(schema.get("required", []))

    if not properties:
        # No properties — treat as single opaque body param
        return []

    params = []
    for name, prop in properties.items():
        if not isinstance(prop, dict):
            continue

        # Build nested schema description for complex types
        nested_schema = None
        if prop.get("type") == "object" and prop.get("properties"):
            nested_schema = prop
        elif prop.get("type") == "array" and isinstance(prop.get("items"), dict):
            nested_schema = prop

        # Build description with nested field info
        desc = prop.get("description", "")
        example = prop.get("example")
        if example is not None:
            desc = f"{desc} (example: {example})" if desc else f"example: {example}"

        params.append(ToolParameter(
            name=name,
            type=_schema_type_str(prop),
            required=name in required_fields,
            location=location,
            description=desc or None,
            enum=prop.get("enum"),
            default=prop.get("default"),
            schema=nested_schema,
        ))

    return params


def _extract_params(operation: dict, root: dict) -> list[ToolParameter]:
    """Extract all parameters from an operation (path/query/header/body)."""
    params: list[ToolParameter] = []

    # Path/query/header parameters
    for p in operation.get("parameters", []):
        if not isinstance(p, dict):
            continue
        # Resolve parameter $ref
        if "$ref" in p:
            p = _resolve_schema(p, root)
        if "name" not in p:
            continue

        schema = p.get("schema", {})
        if isinstance(schema, dict) and "$ref" in schema:
            schema = _resolve_schema(schema, root)

        desc = p.get("description", "")
        example = p.get("example")
        if example is not None:
            desc = f"{desc} (example: {example})" if desc else f"example: {example}"

        params.append(ToolParameter(
            name=p["name"],
            type=_schema_type_str(schema) if isinstance(schema, dict) else p.get("type", "string"),
            required=p.get("required", p.get("in") == "path"),
            location=p.get("in"),
            description=desc or None,
            enum=schema.get("enum") if isinstance(schema, dict) else p.get("enum"),
            default=schema.get("default") if isinstance(schema, dict) else None,
        ))

    # Request body (OpenAPI 3.x)
    request_body = operation.get("requestBody", {})
    if isinstance(request_body, dict) and "$ref" in request_body:
        request_body = _resolve_schema(request_body, root)

    content = request_body.get("content", {}) if isinstance(request_body, dict) else {}
    media = (
        content.get("application/json")
        or content.get("application/x-www-form-urlencoded")
        or content.get("multipart/form-data")
        or content.get("application/xml")
        or (next(iter(content.values()), {}) if content else {})
    )
    body_schema = media.get("schema", {}) if isinstance(media, dict) else {}

    if body_schema:
        resolved_body = _resolve_schema(body_schema, root)
        body_params = _schema_to_params(resolved_body, location="body")
        if body_params:
            params.extend(body_params)
        elif resolved_body.get("type"):
            # Opaque body (no properties extracted)
            params.append(ToolParameter(
                name="body",
                type=_schema_type_str(resolved_body),
                required=request_body.get("required", False) if isinstance(request_body, dict) else False,
                location="body",
                description=resolved_body.get("description"),
                schema=resolved_body if resolved_body.get("properties") else None,
            ))

    return params


# ──────────────────────────────────────────────
# Response schema extraction
# ──────────────────────────────────────────────

def _extract_response_schema(responses: dict, root: dict) -> dict | None:
    """Extract the success response schema as a JSON Schema dict."""
    if not isinstance(responses, dict):
        return None

    success = responses.get("200") or responses.get("201") or responses.get("204")
    if not isinstance(success, dict):
        return None

    content = success.get("content", {})
    if not content:
        return None

    media = next(iter(content.values()), {})
    schema = media.get("schema", {}) if isinstance(media, dict) else {}
    if not schema:
        return None

    resolved = _resolve_schema(schema, root, max_depth=3)

    # Simplify for LLM consumption: extract top-level field names and types
    summary = {}
    if resolved.get("properties"):
        for name, prop in resolved["properties"].items():
            if isinstance(prop, dict):
                summary[name] = _schema_type_str(prop)
    elif resolved.get("type") == "array" and isinstance(resolved.get("items"), dict):
        items = resolved["items"]
        if items.get("properties"):
            summary = {f"[]{name}": _schema_type_str(prop)
                       for name, prop in items["properties"].items()
                       if isinstance(prop, dict)}
        else:
            summary = {"items": _schema_type_str(items)}
    else:
        summary = {"type": _schema_type_str(resolved)}

    return summary


# ──────────────────────────────────────────────
# Description builder
# ──────────────────────────────────────────────

def _build_description(operation: dict, path: str, method: str) -> str:
    """Build a rich description from summary + description."""
    parts = []

    summary = operation.get("summary", "")
    if summary:
        parts.append(summary)

    description = operation.get("description", "")
    if description:
        # Clean markdown, keep first meaningful paragraph
        clean = description.strip()
        # Remove markdown headers
        clean = re.sub(r'^#{1,3}\s+\S+\n', '', clean)
        # Take first 200 chars of meaningful content
        clean = clean.strip()
        if clean and clean != summary:
            if len(clean) > 200:
                clean = clean[:200].rsplit(" ", 1)[0] + "..."
            parts.append(clean)

    if not parts:
        parts.append(f"{method.upper()} {path}")

    return "\n".join(parts)


# ──────────────────────────────────────────────
# Utilities
# ──────────────────────────────────────────────

def _get_base_url(spec: dict, source_url: str | None = None) -> str:
    servers = spec.get("servers", [])
    if servers:
        server_url = servers[0].get("url", "")
        if server_url.startswith("/") and source_url:
            parsed = urlparse(source_url)
            return f"{parsed.scheme}://{parsed.netloc}{server_url}"
        if server_url.startswith("http"):
            return server_url

    host = spec.get("host")
    if host:
        scheme = (spec.get("schemes") or ["https"])[0]
        base_path = spec.get("basePath", "")
        return f"{scheme}://{host}{base_path}"

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


def _sanitize_name(method: str, path: str) -> str:
    name = f"{method}{path}"
    name = re.sub(r"[{}]", "", name)
    name = re.sub(r"[^a-zA-Z0-9]", "_", name)
    name = re.sub(r"_+", "_", name)
    return name.strip("_")


# ──────────────────────────────────────────────
# Main parser
# ──────────────────────────────────────────────

def parse_openapi(input_data: str | dict, source_url: str | None = None) -> list[Tool]:
    """Parse OpenAPI/Swagger spec into tools with rich parameter and response info."""
    if isinstance(input_data, str):
        if input_data.startswith("http://") or input_data.startswith("https://"):
            res = httpx.get(input_data, follow_redirects=True, timeout=30)
            input_data = res.text
            source_url = source_url or res.url.__str__()

        try:
            spec = json.loads(input_data)
        except json.JSONDecodeError:
            spec = yaml.safe_load(input_data)
    else:
        spec = input_data

    # NOTE: we do NOT globally resolve $ref anymore.
    # Instead, we resolve on-demand per operation for safety.

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
            endpoint = f"{base_url.rstrip('/')}/{path.lstrip('/')}" if path.startswith("/") else f"{base_url}{path}"

            # Extract parameters with resolved $ref
            parameters = _extract_params(operation, spec)

            # Build rich description
            description = _build_description(operation, path, method)

            # Extract response schema
            response_schema = _extract_response_schema(operation.get("responses", {}), spec)

            # Build metadata
            metadata: dict = {}
            if response_schema:
                metadata["response_schema"] = response_schema

            # Deprecated flag
            if operation.get("deprecated"):
                metadata["deprecated"] = True
                description = f"[DEPRECATED] {description}"

            tools.append(Tool(
                name=name,
                description=description,
                parameters=parameters,
                endpoint=endpoint,
                method=method.upper(),
                protocol="rest",
                response_format=_detect_response_format(operation.get("responses")),
                tags=operation.get("tags", []),
                metadata=metadata,
            ))

    return tools
