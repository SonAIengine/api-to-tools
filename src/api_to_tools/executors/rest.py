"""REST API executor (with Nexacro SSV support)."""

from __future__ import annotations

import json

import httpx
import xmltodict

from api_to_tools.auth import (
    build_auth_cookies,
    build_auth_headers,
    build_auth_params,
    resolve_auth,
)
from api_to_tools.parsers.ssv import build_request_ssv, is_ssv_content, parse_ssv
from api_to_tools.types import AuthConfig, ExecutionResult, Tool


def _execute_nexacro(tool: Tool, args: dict, *, auth: AuthConfig | None = None) -> ExecutionResult:
    """Execute a Nexacro-style API call (SSV request/response)."""
    body_params = {
        p.name: args[p.name]
        for p in tool.parameters
        if p.location == "body" and p.name in args
    }
    ssv_body = build_request_ssv(body_params)

    headers = {
        "Content-Type": "text/plain; charset=UTF-8",
        "Accept": "text/plain, */*",
    }
    cookies: dict[str, str] = {}
    if auth:
        resolved = resolve_auth(auth)
        headers.update(build_auth_headers(resolved))
        cookies = build_auth_cookies(resolved)

    with httpx.Client(verify=False) as client:
        response = client.request(
            method=tool.method or "POST",
            url=tool.endpoint,
            content=ssv_body,
            headers=headers,
            cookies=cookies or None,
            follow_redirects=True,
            timeout=30,
        )

    raw = response.text
    data = parse_ssv(raw) if is_ssv_content(raw) else raw

    return ExecutionResult(
        status=response.status_code,
        data=data,
        headers=dict(response.headers),
        raw=raw,
    )


def execute_rest(tool: Tool, args: dict, *, auth: AuthConfig | None = None) -> ExecutionResult:
    """Execute a REST API call (with Nexacro SSV support)."""
    # Nexacro SSV variant: encode body as SSV, parse response as SSV
    if tool.metadata.get("protocol_variant") == "nexacro-ssv":
        return _execute_nexacro(tool, args, auth=auth)

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

    # Apply auth
    cookies = {}
    if auth:
        resolved = resolve_auth(auth)
        headers.update(build_auth_headers(resolved))
        query_params.update(build_auth_params(resolved))
        cookies = build_auth_cookies(resolved)

    with httpx.Client() as client:
        response = client.request(
            method=tool.method,
            url=url,
            params=query_params or None,
            headers=headers,
            cookies=cookies or None,
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
