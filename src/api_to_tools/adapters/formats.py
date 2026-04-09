"""Format converters for LLM tool calling."""

from __future__ import annotations

from api_to_tools.types import Tool


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
                        p.name: {
                            "type": p.type,
                            **({"description": p.description} if p.description else {}),
                            **({"enum": p.enum} if p.enum else {}),
                        }
                        for p in tool.parameters
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
                    p.name: {
                        "type": p.type,
                        **({"description": p.description} if p.description else {}),
                        **({"enum": p.enum} if p.enum else {}),
                    }
                    for p in tool.parameters
                },
                "required": [p.name for p in tool.parameters if p.required],
            },
        }
        for tool in tools
    ]
