"""GraphQL introspection parser."""

from __future__ import annotations

import json

import httpx
from graphql import (
    build_client_schema,
    get_introspection_query,
    is_enum_type,
    is_list_type,
    is_non_null_type,
    is_object_type,
    is_scalar_type,
)

from api_to_tools.types import Tool, ToolParameter


def _unwrap_type(gql_type):
    """Unwrap NonNull/List wrappers to get the named type."""
    current = gql_type
    required = is_non_null_type(current)
    if is_non_null_type(current):
        current = current.of_type
    if is_list_type(current):
        current = current.of_type
    if is_non_null_type(current):
        current = current.of_type
    type_name = str(gql_type).replace("[", "").replace("]", "").replace("!", "")
    return type_name, required, current


def _build_selection_set(gql_type, depth: int = 0, max_depth: int = 2) -> str | None:
    """Build selection set for object types."""
    current = gql_type
    if is_non_null_type(current):
        current = current.of_type
    if is_list_type(current):
        current = current.of_type
    if is_non_null_type(current):
        current = current.of_type

    if is_scalar_type(current) or is_enum_type(current):
        return None
    if not is_object_type(current) or depth >= max_depth:
        return None

    selections = []
    for name, field in current.fields.items():
        if field.args:
            continue
        sub = _build_selection_set(field.type, depth + 1, max_depth)
        if sub:
            selections.append(f"{name} {sub}")
        else:
            ft = field.type
            if is_non_null_type(ft):
                ft = ft.of_type
            if is_list_type(ft):
                ft = ft.of_type
            if is_non_null_type(ft):
                ft = ft.of_type
            if is_scalar_type(ft) or is_enum_type(ft):
                selections.append(name)

    if not selections:
        return None
    return "{ " + " ".join(selections) + " }"


def _extract_response_fields(gql_type) -> dict | None:
    """Extract top-level response field names and types from a GraphQL return type."""
    current = gql_type
    if is_non_null_type(current):
        current = current.of_type
    if is_list_type(current):
        current = current.of_type
    if is_non_null_type(current):
        current = current.of_type

    if not is_object_type(current):
        return None

    fields = {}
    for fname, ffield in current.fields.items():
        type_name, _, _ = _unwrap_type(ffield.type)
        fields[fname] = type_name

    return fields if fields else None


def _field_to_tool(field, kind: str, endpoint: str, field_name: str = "") -> Tool:
    params = []
    for arg_name, arg in field.args.items():
        type_name, required, _ = _unwrap_type(arg.type)
        params.append(ToolParameter(
            name=arg_name,
            type=type_name,
            required=required,
            description=arg.description or None,
            default=arg.default_value if arg.default_value is not None else None,
        ))

    name = field_name or getattr(field, "name", "unknown")
    selection_set = _build_selection_set(field.type)
    metadata = {"return_type": str(field.type)}
    if selection_set:
        metadata["selection_set"] = selection_set

    # Build response_schema from return type fields
    response_schema = _extract_response_fields(field.type)
    if response_schema:
        metadata["response_schema"] = response_schema

    return Tool(
        name=name,
        description=field.description or f"{kind}: {name}",
        parameters=params,
        endpoint=endpoint,
        method=kind,
        protocol="graphql",
        response_format="json",
        tags=[kind],
        metadata=metadata,
    )


def _fetch_schema(url: str):
    """Fetch GraphQL schema via introspection."""
    res = httpx.post(
        url,
        json={"query": get_introspection_query()},
        headers={"Content-Type": "application/json"},
        timeout=30,
    )
    data = res.json()
    return build_client_schema(data["data"])


def parse_graphql(input_data: str | dict, source_url: str | None = None) -> list[Tool]:
    """Parse GraphQL schema into tools."""
    if isinstance(input_data, str) and input_data.startswith("http"):
        schema = _fetch_schema(input_data)
        endpoint = input_data
    elif isinstance(input_data, str):
        data = json.loads(input_data)
        schema = build_client_schema(data["data"])
        endpoint = source_url or ""
    else:
        schema = build_client_schema(input_data["data"])
        endpoint = source_url or ""

    tools: list[Tool] = []

    query_type = schema.query_type
    if query_type:
        for field_name, field in query_type.fields.items():
            tools.append(_field_to_tool(field, "query", endpoint, field_name))

    mutation_type = schema.mutation_type
    if mutation_type:
        for field_name, field in mutation_type.fields.items():
            tools.append(_field_to_tool(field, "mutation", endpoint, field_name))

    return tools
