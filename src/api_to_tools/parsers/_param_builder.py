"""Shared utilities for building ToolParameters across parsers."""

from __future__ import annotations

import re
from typing import Any
from urllib.parse import urlparse

from api_to_tools.constants import API_PATH_MARKERS, COMMON_PATH_PREFIXES, STATIC_FILE_EXTENSIONS
from api_to_tools.types import ToolParameter


# ──────────────────────────────────────────────
# Type inference
# ──────────────────────────────────────────────

def infer_json_type(value: Any) -> str:
    """Infer a JSON Schema type from a Python value."""
    if isinstance(value, bool):
        return "boolean"
    if isinstance(value, int):
        return "integer"
    if isinstance(value, float):
        return "number"
    if isinstance(value, list):
        return "array"
    if isinstance(value, dict):
        return "object"
    return "string"


def schema_type_str(schema: dict) -> str:
    """Get a human-readable type string from a JSON Schema object."""
    if not isinstance(schema, dict):
        return "string"
    t = schema.get("type", "object")
    if t == "array":
        items = schema.get("items", {})
        item_type = items.get("type", "object") if isinstance(items, dict) else "object"
        return f"array[{item_type}]"
    return t


# ──────────────────────────────────────────────
# URL / path helpers
# ──────────────────────────────────────────────

def is_api_url(url: str) -> bool:
    """Determine if a URL looks like an API call (not a static asset)."""
    parsed = urlparse(url)
    path = parsed.path.lower()
    if any(path.endswith(ext) for ext in STATIC_FILE_EXTENSIONS):
        return False
    if "/_next/" in path or "/__nextjs" in path:
        return False
    return any(marker in path for marker in API_PATH_MARKERS)


def extract_tag_from_path(path: str) -> str:
    """Extract the most meaningful segment as a tag, skipping common prefixes."""
    segments = [s for s in path.split("/") if s]
    for seg in segments:
        if seg.lower() not in COMMON_PATH_PREFIXES:
            return seg
    return segments[0] if segments else "api"


def sanitize_name(raw: str) -> str:
    """Clean a name so it's safe as a Tool identifier."""
    cleaned = re.sub(r"[^a-zA-Z0-9_]", "_", raw)
    cleaned = re.sub(r"_+", "_", cleaned)
    return cleaned.strip("_") or "unknown"


def normalize_path_params(path: str) -> str:
    """Replace common ID patterns in a URL path with placeholders."""
    # UUIDs
    path = re.sub(
        r'/[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}(/|$)',
        r'/{uuid}\1', path,
    )
    # Pure numeric IDs
    path = re.sub(r'/\d+(/|$)', r'/{id}\1', path)
    # Uppercase alphanumeric codes (LA01010000 style)
    path = re.sub(r'/[A-Z][A-Z0-9]{4,}(/|$)', r'/{code}\1', path)
    # Long hex hashes
    path = re.sub(r'/[0-9a-f]{24,}(/|$)', r'/{hash}\1', path)
    return path


# ──────────────────────────────────────────────
# ToolParameter builders
# ──────────────────────────────────────────────

def build_param_from_value(
    name: str,
    value: Any,
    *,
    location: str = "body",
    required: bool = False,
) -> ToolParameter:
    """Build a ToolParameter from an observed value (used by crawlers)."""
    description = f"example: {value}" if value not in (None, "") else None
    return ToolParameter(
        name=name,
        type=infer_json_type(value),
        required=required,
        location=location,
        description=description,
    )


def build_params_from_json_schema(
    schema: dict,
    *,
    location: str = "body",
) -> list[ToolParameter]:
    """Convert a JSON Schema object into ToolParameters.

    Shared implementation used by OpenAPI/Swagger parsers.
    """
    if not isinstance(schema, dict):
        return []

    properties = schema.get("properties", {})
    required_fields = set(schema.get("required", []))
    if not properties:
        return []

    params: list[ToolParameter] = []
    for name, prop in properties.items():
        if not isinstance(prop, dict):
            continue

        nested_schema = None
        if prop.get("type") == "object" and prop.get("properties"):
            nested_schema = prop
        elif prop.get("type") == "array" and isinstance(prop.get("items"), dict):
            nested_schema = prop

        desc = prop.get("description", "")
        example = prop.get("example")
        if example is not None:
            desc = f"{desc} (example: {example})" if desc else f"example: {example}"

        params.append(ToolParameter(
            name=name,
            type=schema_type_str(prop),
            required=name in required_fields,
            location=location,
            description=desc or None,
            enum=prop.get("enum"),
            default=prop.get("default"),
            schema=nested_schema,
        ))

    return params


def schema_from_value(value: Any, *, max_depth: int = 3) -> dict:
    """Build a JSON Schema from an observed Python value.

    Useful for inferring response schemas from actual API responses.
    """
    if max_depth <= 0:
        return {"type": "object"}

    if isinstance(value, dict):
        properties = {}
        for k, v in list(value.items())[:30]:
            properties[k] = schema_from_value(v, max_depth=max_depth - 1)
        return {"type": "object", "properties": properties}

    if isinstance(value, list):
        if value:
            return {"type": "array", "items": schema_from_value(value[0], max_depth=max_depth - 1)}
        return {"type": "array", "items": {"type": "object"}}

    return {"type": infer_json_type(value)}
