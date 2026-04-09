"""API executors."""

from __future__ import annotations

from api_to_tools.types import Protocol
from api_to_tools.executors.rest import execute_rest
from api_to_tools.executors.soap import execute_soap
from api_to_tools.executors.graphql import execute_graphql

EXECUTORS = {
    "rest": execute_rest,
    "soap": execute_soap,
    "graphql": execute_graphql,
}


def get_executor(protocol: Protocol):
    executor = EXECUTORS.get(protocol)
    if not executor:
        raise NotImplementedError(f"Executor for '{protocol}' is not yet implemented")
    return executor
