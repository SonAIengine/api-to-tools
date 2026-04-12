"""GraphQL executor."""

from __future__ import annotations

import httpx

from api_to_tools.constants import DEFAULT_EXECUTOR_TIMEOUT
from api_to_tools.types import AuthConfig, Tool, ExecutionResult


def _build_query(tool: Tool, args: dict) -> str:
    kind = tool.method  # 'query' or 'mutation'
    selection_set = tool.metadata.get("selection_set", "")

    used_params = [p for p in tool.parameters if p.name in args]
    if not used_params:
        return f"{kind} {{ {tool.name} {selection_set} }}"

    var_defs = ", ".join(f"${p.name}: {p.type}{'!' if p.required else ''}" for p in used_params)
    field_args = ", ".join(f"{p.name}: ${p.name}" for p in used_params)

    return f"{kind}({var_defs}) {{ {tool.name}({field_args}) {selection_set} }}"


def execute_graphql(tool: Tool, args: dict, *, auth: AuthConfig | None = None) -> ExecutionResult:
    """Execute a GraphQL query/mutation."""
    from api_to_tools.auth import build_auth_headers, build_auth_cookies, resolve_auth

    query = _build_query(tool, args)
    variables = {p.name: args[p.name] for p in tool.parameters if p.name in args}

    headers = {"Content-Type": "application/json"}
    cookies = {}
    if auth:
        resolved = resolve_auth(auth)
        headers.update(build_auth_headers(resolved))
        cookies = build_auth_cookies(resolved)

    verify = auth.verify_ssl if auth else True
    response = httpx.post(
        tool.endpoint,
        json={"query": query, "variables": variables},
        headers=headers,
        cookies=cookies or None,
        timeout=DEFAULT_EXECUTOR_TIMEOUT,
        verify=verify,
    )

    data = response.json()
    return ExecutionResult(
        status=response.status_code,
        data=data,
        headers=dict(response.headers),
        raw=response.text,
    )
