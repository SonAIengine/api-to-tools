"""OpenAPI 2.0/3.0/3.1 parser."""

from __future__ import annotations

import json
import re
from urllib.parse import urlparse

import httpx
import yaml

from api_to_tools.constants import DEFAULT_SPEC_FETCH_TIMEOUT
from api_to_tools.parsers._param_builder import schema_type_str, sanitize_name
from api_to_tools.types import AuthConfig, Tool, ToolParameter, ResponseFormat


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

# _schema_type_str is imported from _param_builder (as schema_type_str)
_schema_type_str = schema_type_str


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

    # Path/query/header/body parameters
    for p in operation.get("parameters", []):
        if not isinstance(p, dict):
            continue
        if "$ref" in p:
            p = _resolve_schema(p, root)
        if "name" not in p:
            continue

        param_in = p.get("in", "")

        # --- Swagger 2.0: in="body" parameter ---
        if param_in == "body":
            body_schema = p.get("schema", {})
            if isinstance(body_schema, dict) and "$ref" in body_schema:
                body_schema = _resolve_schema(body_schema, root)
            elif isinstance(body_schema, dict):
                body_schema = _resolve_schema(body_schema, root)
            body_params = _schema_to_params(body_schema, location="body")
            if body_params:
                params.extend(body_params)
            elif body_schema:
                params.append(ToolParameter(
                    name=p["name"],
                    type=_schema_type_str(body_schema),
                    required=p.get("required", False),
                    location="body",
                    description=p.get("description"),
                    schema=body_schema if body_schema.get("properties") else None,
                ))
            continue

        # --- Normal parameters (path/query/header/cookie) ---
        schema = p.get("schema", {})
        if isinstance(schema, dict) and "$ref" in schema:
            schema = _resolve_schema(schema, root)

        desc = p.get("description", "")
        # Example from parameter level or schema level
        example = p.get("example") or p.get("x-example")
        if example is None and isinstance(schema, dict):
            example = schema.get("example") or schema.get("default")
        if example is not None:
            desc = f"{desc} (example: {example})" if desc else f"example: {example}"

        # Enum: check both parameter level (Swagger 2.0) and schema level (OpenAPI 3.x)
        enum_values = None
        if isinstance(schema, dict) and schema.get("enum"):
            enum_values = schema["enum"]
        elif p.get("enum"):
            enum_values = p["enum"]

        # Type: Swagger 2.0 puts type at parameter level, 3.x in schema
        param_type = (
            (_schema_type_str(schema) if isinstance(schema, dict) and schema.get("type") else None)
            or p.get("type", "string")
        )

        params.append(ToolParameter(
            name=p["name"],
            type=param_type,
            required=p.get("required", param_in == "path"),
            location=param_in or None,
            description=desc or None,
            enum=enum_values,
            default=schema.get("default") if isinstance(schema, dict) else p.get("default"),
        ))

    # --- Request body (OpenAPI 3.x) ---
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
    """Extract the success response schema as a JSON Schema dict.

    Handles both OpenAPI 3.x (content.*.schema) and Swagger 2.0 (schema directly).
    """
    if not isinstance(responses, dict):
        return None

    success = responses.get("200") or responses.get("201") or responses.get("204")
    if not isinstance(success, dict):
        return None

    schema = None

    # OpenAPI 3.x: responses.200.content.*.schema
    content = success.get("content", {})
    if content:
        media = next(iter(content.values()), {})
        schema = media.get("schema", {}) if isinstance(media, dict) else {}

    # Swagger 2.0: responses.200.schema (directly on the response)
    if not schema and "schema" in success:
        schema = success["schema"]

    if not schema or not isinstance(schema, dict):
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
# Security scheme extraction
# ──────────────────────────────────────────────

def extract_security_schemes(spec: dict) -> list[dict]:
    """Extract security schemes from an OpenAPI spec as structured dicts.

    Returns a list of dicts, each representing one auth method.
    Internal keys prefixed with `_` (e.g. `_scheme_name`) are metadata
    and should not be passed to AuthConfig directly.
    Use `security_schemes_to_auth_configs()` for AuthConfig conversion.

    Supports:
    - http/basic → type="basic"
    - http/bearer → type="bearer"
    - apiKey (header or query) → type="api_key"
    - oauth2 (all flows) → type="oauth2_client" with token_url/scopes
    """
    # OpenAPI 3.x
    components = spec.get("components", {})
    schemes = components.get("securitySchemes", {})

    # Swagger 2.x
    if not schemes:
        schemes = spec.get("securityDefinitions", {})

    results: list[dict] = []
    for name, scheme in schemes.items():
        if not isinstance(scheme, dict):
            continue

        scheme_type = scheme.get("type", "")
        auth_dict: dict = {"_scheme_name": name}

        if scheme_type == "http":
            http_scheme = scheme.get("scheme", "").lower()
            if http_scheme == "basic":
                auth_dict.update(type="basic")
            elif http_scheme == "bearer":
                auth_dict.update(type="bearer", _bearer_format=scheme.get("bearerFormat"))
            else:
                continue

        elif scheme_type == "apiKey":
            location = scheme.get("in", "header")
            key_name = scheme.get("name", "")
            if not key_name:
                continue
            auth_dict.update(
                type="api_key",
                key=key_name,
                location="header" if location == "header" else "query",
            )

        elif scheme_type == "oauth2":
            flows = scheme.get("flows", {})
            # Prefer client_credentials, then authorizationCode, then implicit
            flow = (
                flows.get("clientCredentials")
                or flows.get("authorizationCode")
                or flows.get("password")
                or flows.get("implicit")
                or {}
            )
            token_url = flow.get("tokenUrl", "")
            scopes = list((flow.get("scopes") or {}).keys())
            auth_dict.update(
                type="oauth2_client",
                token_url=token_url,
                scope=" ".join(scopes) if scopes else None,
                _authorization_url=flow.get("authorizationUrl"),
            )

        # Swagger 2.x: type="basic"
        elif scheme_type == "basic":
            auth_dict.update(type="basic")

        else:
            continue

        results.append(auth_dict)

    return results


def security_schemes_to_auth_configs(spec: dict) -> list[AuthConfig]:
    """Convert OpenAPI security schemes to AuthConfig objects.

    Only returns configs that are usable without additional user input
    (i.e. api_key and oauth2_client with token_url). Basic and bearer
    require credentials/tokens from the user.
    """
    configs: list[AuthConfig] = []
    for scheme in extract_security_schemes(spec):
        auth_type = scheme.get("type")
        if auth_type == "api_key":
            configs.append(AuthConfig(
                type="api_key",
                key=scheme.get("key", ""),
                location=scheme.get("location", "header"),
            ))
        elif auth_type == "oauth2_client" and scheme.get("token_url"):
            configs.append(AuthConfig(
                type="oauth2_client",
                token_url=scheme.get("token_url"),
                scope=scheme.get("scope"),
            ))
        elif auth_type == "basic":
            configs.append(AuthConfig(type="basic"))
        elif auth_type == "bearer":
            configs.append(AuthConfig(type="bearer"))
    return configs


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
    """Build a safe tool name from HTTP method + path."""
    raw = re.sub(r"[{}]", "", f"{method}{path}")
    return sanitize_name(raw)


# ──────────────────────────────────────────────
# Main parser
# ──────────────────────────────────────────────

def parse_openapi(input_data: str | dict, source_url: str | None = None) -> list[Tool]:
    """Parse OpenAPI/Swagger spec into tools with rich parameter and response info."""
    if isinstance(input_data, str):
        if input_data.startswith("http://") or input_data.startswith("https://"):
            res = httpx.get(input_data, follow_redirects=True, timeout=DEFAULT_SPEC_FETCH_TIMEOUT)
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

    # Extract security schemes once for the entire spec
    security_schemes = extract_security_schemes(spec)
    # Global security requirements
    global_security = spec.get("security", [])

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

            # Security: operation-level overrides global
            op_security = operation.get("security", global_security)
            if op_security and security_schemes:
                # Map required scheme names to their definitions
                required_names = set()
                for req in op_security:
                    if isinstance(req, dict):
                        required_names.update(req.keys())
                matched = [s for s in security_schemes if s.get("_scheme_name") in required_names]
                if matched:
                    metadata["security_schemes"] = matched

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
