"""Universal API-to-LLM-tools converter."""

from api_to_tools._logging import enable_debug_logging
from api_to_tools.adapters.formats import (
    to_anthropic_tools,
    to_bedrock_tools,
    to_function_calling,
    to_gemini_tools,
    to_langchain_tools,
    to_vertex_ai_tools,
)
from api_to_tools.core import discover, execute, to_tools
from api_to_tools.types import (
    AuthConfig,
    DetectionResult,
    ExecutionResult,
    Protocol,
    SpecType,
    Tool,
    ToolParameter,
)
from api_to_tools.utils import (
    group_by_method,
    group_by_tag,
    search_tools,
    summarize,
)

__all__ = [
    "discover",
    "to_tools",
    "execute",
    "to_function_calling",
    "to_anthropic_tools",
    "to_gemini_tools",
    "to_vertex_ai_tools",
    "to_bedrock_tools",
    "to_langchain_tools",
    "group_by_tag",
    "group_by_method",
    "summarize",
    "search_tools",
    "enable_debug_logging",
    "Tool",
    "ToolParameter",
    "AuthConfig",
    "DetectionResult",
    "ExecutionResult",
    "SpecType",
    "Protocol",
]
