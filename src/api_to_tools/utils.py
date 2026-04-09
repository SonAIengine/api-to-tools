"""Utility functions for working with tools."""

from __future__ import annotations

from collections import defaultdict

from api_to_tools.types import Tool


def group_by_tag(tools: list[Tool]) -> dict[str, list[Tool]]:
    groups: dict[str, list[Tool]] = defaultdict(list)
    for tool in tools:
        tags = tool.tags or ["untagged"]
        for tag in tags:
            groups[tag].append(tool)
    return dict(groups)


def group_by_method(tools: list[Tool]) -> dict[str, list[Tool]]:
    groups: dict[str, list[Tool]] = defaultdict(list)
    for tool in tools:
        groups[tool.method].append(tool)
    return dict(groups)


def summarize(tools: list[Tool]) -> dict:
    by_tag: dict[str, int] = defaultdict(int)
    by_method: dict[str, int] = defaultdict(int)
    by_protocol: dict[str, int] = defaultdict(int)

    for tool in tools:
        for tag in tool.tags or ["untagged"]:
            by_tag[tag] += 1
        by_method[tool.method] += 1
        by_protocol[tool.protocol] += 1

    return {
        "total": len(tools),
        "by_tag": dict(sorted(by_tag.items(), key=lambda x: -x[1])),
        "by_method": dict(sorted(by_method.items(), key=lambda x: -x[1])),
        "by_protocol": dict(by_protocol),
    }


def search_tools(tools: list[Tool], query: str) -> list[Tool]:
    q = query.lower()
    return [t for t in tools if q in t.name.lower() or q in t.description.lower()]
