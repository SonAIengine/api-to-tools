"""Universal API-to-LLM-tools converter."""

from api_to_tools.types import Tool, ToolParameter, AuthConfig, DetectionResult, SpecType, Protocol
from api_to_tools.core import discover, to_tools, execute
from api_to_tools.adapters.formats import to_function_calling, to_anthropic_tools
from api_to_tools.utils import group_by_tag, group_by_method, summarize, search_tools

__all__ = [
    "discover",
    "to_tools",
    "execute",
    "to_function_calling",
    "to_anthropic_tools",
    "group_by_tag",
    "group_by_method",
    "summarize",
    "search_tools",
    "Tool",
    "ToolParameter",
    "AuthConfig",
    "DetectionResult",
    "SpecType",
    "Protocol",
]
