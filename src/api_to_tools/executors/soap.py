"""SOAP executor using zeep."""

from __future__ import annotations

from functools import lru_cache

from zeep import Client as ZeepClient

from api_to_tools.types import Tool, ExecutionResult


@lru_cache(maxsize=16)
def _get_client(wsdl_url: str) -> ZeepClient:
    return ZeepClient(wsdl_url)


def execute_soap(tool: Tool, args: dict) -> ExecutionResult:
    """Execute a SOAP call."""
    client = _get_client(tool.endpoint)
    service = client.service
    method = getattr(service, tool.method)
    result = method(**args)

    # zeep returns ordered dicts or simple values
    import json
    data = json.loads(json.dumps(result, default=str)) if result else None

    return ExecutionResult(
        status=200,
        data=data,
        raw=str(result),
    )
