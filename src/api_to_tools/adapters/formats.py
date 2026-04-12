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


def to_gemini_tools(tools: list[Tool]) -> list[dict]:
    """Convert to Google Gemini / Vertex AI function calling format.

    Returns a list of FunctionDeclaration dicts wrapped in a single Tool object,
    matching the Gemini API's `tools` parameter structure.
    """
    declarations = []
    for tool in tools:
        properties = {}
        required = []
        for p in tool.parameters:
            prop = _to_json_schema_type(p.type)
            if p.description:
                prop["description"] = p.description
            if p.enum:
                prop["enum"] = p.enum
            properties[p.name] = prop
            if p.required:
                required.append(p.name)

        decl: dict = {
            "name": tool.name,
            "description": tool.description,
            "parameters": {
                "type": "object",
                "properties": properties,
            },
        }
        if required:
            decl["parameters"]["required"] = required
        declarations.append(decl)

    return [{"function_declarations": declarations}]


# Alias: Vertex AI uses the same format as Gemini
to_vertex_ai_tools = to_gemini_tools


def to_bedrock_tools(tools: list[Tool]) -> list[dict]:
    """Convert to AWS Bedrock Converse API toolConfig format.

    Returns a list of tool specs matching Bedrock's `toolConfig.tools` structure.
    """
    return [
        {
            "toolSpec": {
                "name": tool.name,
                "description": tool.description,
                "inputSchema": {
                    "json": {
                        "type": "object",
                        "properties": {
                            p.name: _param_schema(p) for p in tool.parameters
                        },
                        "required": [p.name for p in tool.parameters if p.required],
                    },
                },
            },
        }
        for tool in tools
    ]


def to_langchain_tools(tools: list[Tool]) -> list[dict]:
    """Convert to LangChain-compatible tool schema format.

    Returns dicts that can be used with `StructuredTool.from_function()` or
    passed to `ChatModel.bind_tools()`.
    """
    result = []
    for tool in tools:
        properties = {}
        required = []
        for p in tool.parameters:
            prop = _to_json_schema_type(p.type)
            if p.description:
                prop["description"] = p.description
            if p.enum:
                prop["enum"] = p.enum
            properties[p.name] = prop
            if p.required:
                required.append(p.name)

        schema: dict = {
            "title": tool.name,
            "description": tool.description,
            "type": "object",
            "properties": properties,
        }
        if required:
            schema["required"] = required

        result.append({
            "type": "function",
            "function": {
                "name": tool.name,
                "description": tool.description,
                "parameters": schema,
            },
        })
    return result
