"""Export Tool definitions as an OpenAPI 3.0 spec.

Useful for documenting APIs discovered from HAR files, crawlers, or
other sources that don't have a formal spec.
"""

from __future__ import annotations

import json
from urllib.parse import urlparse

from api_to_tools.adapters.formats import _to_json_schema_type
from api_to_tools.types import Tool


def to_openapi_spec(
    tools: list[Tool],
    *,
    title: str = "API",
    version: str = "1.0.0",
    description: str | None = None,
) -> dict:
    """Convert a list of Tools into an OpenAPI 3.0 specification dict.

    Args:
        tools: Tools to include in the spec.
        title: API title.
        version: API version string.
        description: Optional API description.

    Returns:
        OpenAPI 3.0 spec as a dict (JSON-serializable).
    """
    spec: dict = {
        "openapi": "3.0.0",
        "info": {
            "title": title,
            "version": version,
        },
        "paths": {},
    }
    if description:
        spec["info"]["description"] = description

    # Derive servers from tool endpoints
    origins: set[str] = set()
    for tool in tools:
        parsed = urlparse(tool.endpoint)
        if parsed.scheme and parsed.netloc:
            origins.add(f"{parsed.scheme}://{parsed.netloc}")

    if origins:
        spec["servers"] = [{"url": url} for url in sorted(origins)]

    # Collect tags
    all_tags: set[str] = set()

    # Group tools by path
    for tool in tools:
        parsed = urlparse(tool.endpoint)
        path = parsed.path or "/"

        method = tool.method.lower()
        if method not in ("get", "post", "put", "patch", "delete", "head", "options"):
            method = "post"

        operation: dict = {
            "operationId": tool.name,
            "summary": tool.description[:200] if tool.description else "",
            "responses": {
                "200": {"description": "Successful response"},
            },
        }

        if tool.tags:
            operation["tags"] = tool.tags
            all_tags.update(tool.tags)

        # Parameters
        parameters = []
        request_body_props = {}
        request_body_required = []

        for p in tool.parameters:
            if p.location in ("path", "query", "header"):
                param: dict = {
                    "name": p.name,
                    "in": p.location,
                    "required": p.required,
                    "schema": _to_json_schema_type(p.type),
                }
                if p.description:
                    param["description"] = p.description
                if p.enum:
                    param["schema"]["enum"] = p.enum
                parameters.append(param)
            else:
                # body parameter
                prop = _to_json_schema_type(p.type)
                if p.description:
                    prop["description"] = p.description
                if p.enum:
                    prop["enum"] = p.enum
                request_body_props[p.name] = prop
                if p.required:
                    request_body_required.append(p.name)

        if parameters:
            operation["parameters"] = parameters

        if request_body_props and method in ("post", "put", "patch"):
            body_schema: dict = {
                "type": "object",
                "properties": request_body_props,
            }
            if request_body_required:
                body_schema["required"] = request_body_required
            operation["requestBody"] = {
                "content": {
                    "application/json": {"schema": body_schema},
                },
            }

        # Response schema from metadata
        response_schema = tool.metadata.get("response_schema")
        if response_schema:
            operation["responses"]["200"]["content"] = {
                "application/json": {"schema": response_schema},
            }

        # Add to paths
        if path not in spec["paths"]:
            spec["paths"][path] = {}
        spec["paths"][path][method] = operation

    # Tags
    if all_tags:
        spec["tags"] = [{"name": tag} for tag in sorted(all_tags)]

    return spec


def to_openapi_json(tools: list[Tool], **kwargs) -> str:
    """Convert Tools to an OpenAPI 3.0 JSON string."""
    return json.dumps(to_openapi_spec(tools, **kwargs), indent=2, ensure_ascii=False)
