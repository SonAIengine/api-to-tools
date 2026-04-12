"""Tool serialization — save/load Tool lists to/from JSON."""

from __future__ import annotations

import json
from dataclasses import asdict
from pathlib import Path

from api_to_tools.types import Tool, ToolParameter


# Fields in auth metadata that may contain secrets
_SENSITIVE_AUTH_FIELDS = frozenset({
    "password", "token", "client_secret", "refresh_token", "cookies", "value",
})


def _sanitize_auth(auth_dict: dict) -> dict:
    """Remove sensitive fields from auth metadata."""
    return {k: v for k, v in auth_dict.items() if k not in _SENSITIVE_AUTH_FIELDS}


def tool_to_dict(tool: Tool, *, include_auth: bool = False) -> dict:
    """Convert a Tool to a JSON-serializable dict.

    Args:
        tool: The Tool to serialize.
        include_auth: If True, keeps auth secrets (token, password, cookies).
            Default False — strips sensitive fields from metadata.
    """
    d = asdict(tool)
    if not include_auth and "auth" in d.get("metadata", {}):
        d["metadata"]["auth"] = _sanitize_auth(d["metadata"]["auth"])
    return d


def dict_to_tool(data: dict) -> Tool:
    """Reconstruct a Tool from a dict (inverse of tool_to_dict)."""
    params = [ToolParameter(**p) for p in data.get("parameters", [])]
    return Tool(
        name=data["name"],
        description=data["description"],
        parameters=params,
        endpoint=data["endpoint"],
        method=data["method"],
        protocol=data["protocol"],
        response_format=data.get("response_format", "json"),
        tags=data.get("tags", []),
        metadata=data.get("metadata", {}),
    )


def save_tools(
    tools: list[Tool],
    path: str | Path,
    *,
    include_auth: bool = False,
    indent: int = 2,
) -> None:
    """Save a list of Tools to a JSON file.

    Args:
        tools: Tools to save.
        path: Destination file path.
        include_auth: Preserve auth secrets (default False for safety).
        indent: JSON indentation.

    Example:
        tools = discover("https://api.example.com/docs")
        save_tools(tools, "my_tools.json")
    """
    data = {
        "version": 1,
        "tools": [tool_to_dict(t, include_auth=include_auth) for t in tools],
    }
    Path(path).write_text(json.dumps(data, indent=indent, ensure_ascii=False), encoding="utf-8")


def load_tools(path: str | Path) -> list[Tool]:
    """Load Tools from a JSON file saved by save_tools().

    Args:
        path: Source file path.

    Returns:
        list[Tool]: Reconstructed Tool objects.

    Example:
        tools = load_tools("my_tools.json")
        result = execute(tools[0], {"id": 1})
    """
    data = json.loads(Path(path).read_text(encoding="utf-8"))

    # Support both: {"tools": [...]} wrapper format and raw list
    if isinstance(data, dict) and "tools" in data:
        raw_tools = data["tools"]
    elif isinstance(data, list):
        raw_tools = data
    else:
        raise ValueError(f"Unsupported tool file format: {path}")

    return [dict_to_tool(t) for t in raw_tools]


def tools_to_json(tools: list[Tool], *, include_auth: bool = False, indent: int = 2) -> str:
    """Serialize Tools to a JSON string without writing to disk."""
    data = {
        "version": 1,
        "tools": [tool_to_dict(t, include_auth=include_auth) for t in tools],
    }
    return json.dumps(data, indent=indent, ensure_ascii=False)


def tools_from_json(json_str: str) -> list[Tool]:
    """Load Tools from a JSON string."""
    data = json.loads(json_str)
    if isinstance(data, dict) and "tools" in data:
        raw_tools = data["tools"]
    elif isinstance(data, list):
        raw_tools = data
    else:
        raise ValueError("Unsupported tool JSON format")
    return [dict_to_tool(t) for t in raw_tools]
