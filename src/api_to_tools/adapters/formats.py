"""Format converters for LLM tool calling."""

from __future__ import annotations

from api_to_tools.types import Tool

# Valid JSON Schema primitive types
_VALID_JSON_TYPES = frozenset({"string", "number", "integer", "boolean", "array", "object", "null"})


def _to_json_schema_type(t: str) -> dict:
    """Convert a ToolParameter type string to a valid JSON Schema type descriptor.

    Handles custom types like 'array[object]', 'array[string]' from schema_type_str().
    """
    if t in _VALID_JSON_TYPES:
        return {"type": t}
    if t.startswith("array["):
        inner = t[6:-1] if t.endswith("]") else "object"
        items_type = inner if inner in _VALID_JSON_TYPES else "object"
        return {"type": "array", "items": {"type": items_type}}
    return {"type": "string"}


def _param_schema(p) -> dict:
    """Build a JSON Schema property for a single parameter."""
    schema = _to_json_schema_type(p.type)
    if p.description:
        schema["description"] = p.description
    if p.enum:
        schema["enum"] = p.enum
    return schema


def to_function_calling(tools: list[Tool]) -> list[dict]:
    """Convert to OpenAI function calling format."""
    return [
        {
            "type": "function",
            "function": {
                "name": tool.name,
                "description": tool.description,
                "parameters": {
                    "type": "object",
                    "properties": {
                        p.name: _param_schema(p) for p in tool.parameters
                    },
                    "required": [p.name for p in tool.parameters if p.required],
                },
            },
        }
        for tool in tools
    ]


def to_anthropic_tools(tools: list[Tool]) -> list[dict]:
    """Convert to Anthropic tool_use format."""
    return [
        {
            "name": tool.name,
            "description": tool.description,
            "input_schema": {
                "type": "object",
                "properties": {
                    p.name: _param_schema(p) for p in tool.parameters
                },
                "required": [p.name for p in tool.parameters if p.required],
            },
        }
        for tool in tools
    ]
