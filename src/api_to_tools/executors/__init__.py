"""API executors."""

from __future__ import annotations

from api_to_tools.types import Protocol
from api_to_tools.executors.rest import execute_rest
from api_to_tools.executors.soap import execute_soap
from api_to_tools.executors.graphql import execute_graphql


def _lazy_grpc(*args, **kwargs):
    """Lazy import to avoid requiring grpcio unless used."""
    from api_to_tools.executors.grpc_exec import execute_grpc
    return execute_grpc(*args, **kwargs)


EXECUTORS = {
    "rest": execute_rest,
    "soap": execute_soap,
    "graphql": execute_graphql,
    "grpc": _lazy_grpc,
}


def get_executor(protocol: Protocol):
    executor = EXECUTORS.get(protocol)
    if not executor:
        raise NotImplementedError(f"Executor for '{protocol}' is not yet implemented")
    return executor
