"""Tests for executor and parser registry — ensure all types are registered."""

from api_to_tools.executors import EXECUTORS, get_executor
from api_to_tools.parsers import PARSERS, get_parser

import pytest


def test_grpc_executor_registered():
    assert "grpc" in EXECUTORS


def test_grpc_executor_callable():
    executor = get_executor("grpc")
    assert callable(executor)


def test_asyncapi_parser_registered():
    assert "asyncapi" in PARSERS


def test_asyncapi_parser_callable():
    parser = get_parser("asyncapi")
    assert callable(parser)


def test_har_parser_registered():
    assert "har" in PARSERS


def test_all_spec_types_have_parsers():
    """Every SpecType that should have a parser is registered."""
    expected = {"openapi", "wsdl", "graphql", "grpc", "jsbundle", "crawler", "nexacro", "static_spa", "cdp", "har", "asyncapi"}
    assert expected.issubset(set(PARSERS.keys()))


def test_all_protocols_have_executors():
    """Every Protocol that has an executor is registered."""
    expected = {"rest", "soap", "graphql", "grpc"}
    assert expected.issubset(set(EXECUTORS.keys()))


def test_unknown_parser_raises():
    with pytest.raises(NotImplementedError):
        get_parser("nonexistent")


def test_unknown_executor_raises():
    with pytest.raises(NotImplementedError):
        get_executor("nonexistent")
