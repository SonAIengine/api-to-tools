"""REST API executor."""

from __future__ import annotations

import json

import httpx
import xmltodict

from api_to_tools.types import Tool, ExecutionResult


def execute_rest(tool: Tool, args: dict) -> ExecutionResult:
    """Execute a REST API call."""
    url = tool.endpoint

    # Path params
    for p in tool.parameters:
        if p.location == "path" and p.name in args:
            url = url.replace(f"{{{p.name}}}", str(args[p.name]))

    # Query params
    query_params = {p.name: args[p.name] for p in tool.parameters
                    if p.location == "query" and p.name in args}

    # Headers
    headers = {p.name: str(args[p.name]) for p in tool.parameters
               if p.location == "header" and p.name in args}

    # Body
    body_params = {p.name: args[p.name] for p in tool.parameters
                   if p.location == "body" and p.name in args}
    body = None
    if body_params:
        if "body" in body_params and len(body_params) == 1:
            body = body_params["body"]
        else:
            body = body_params

    if tool.method in ("POST", "PUT", "PATCH"):
        headers.setdefault("Content-Type", "application/json")
    headers.setdefault("Accept", "application/json")

    with httpx.Client() as client:
        response = client.request(
            method=tool.method,
            url=url,
            params=query_params or None,
            headers=headers,
            json=body if body and isinstance(body, (dict, list)) else None,
            content=str(body) if body and not isinstance(body, (dict, list)) else None,
            follow_redirects=True,
            timeout=30,
        )

    raw = response.text
    ct = response.headers.get("content-type", "")

    if "xml" in ct:
        data = xmltodict.parse(raw)
    elif "json" in ct:
        try:
            data = response.json()
        except json.JSONDecodeError:
            data = raw
    else:
        try:
            data = response.json()
        except (json.JSONDecodeError, ValueError):
            data = raw

    return ExecutionResult(
        status=response.status_code,
        data=data,
        headers=dict(response.headers),
        raw=raw,
    )
