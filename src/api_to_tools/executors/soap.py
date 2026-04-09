"""SOAP executor using zeep."""

from __future__ import annotations

from functools import lru_cache

from zeep import Client as ZeepClient

from api_to_tools.types import AuthConfig, Tool, ExecutionResult


@lru_cache(maxsize=16)
def _get_client(wsdl_url: str) -> ZeepClient:
    return ZeepClient(wsdl_url)


def execute_soap(tool: Tool, args: dict, *, auth: AuthConfig | None = None) -> ExecutionResult:
    """Execute a SOAP call."""
    # TODO: pass auth to zeep transport if needed
    client = _get_client(tool.endpoint)
    service = client.service
    method = getattr(service, tool.method)
    result = method(**args)

    import json
    data = json.loads(json.dumps(result, default=str)) if result else None

    return ExecutionResult(
        status=200,
        data=data,
        raw=str(result),
    )
