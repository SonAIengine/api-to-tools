"""Core type definitions."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal

SpecType = Literal["openapi", "wsdl", "graphql", "grpc", "asyncapi", "jsonrpc"]
Protocol = Literal["rest", "soap", "graphql", "grpc", "jsonrpc", "async"]
ResponseFormat = Literal["json", "xml", "protobuf", "binary"]
ParameterIn = Literal["path", "query", "header", "body", "cookie"]


@dataclass
class ToolParameter:
    name: str
    type: str
    required: bool = False
    location: ParameterIn | None = None
    description: str | None = None
    enum: list[str] | None = None
    default: Any = None
    schema: dict[str, Any] | None = None


@dataclass
class Tool:
    name: str
    description: str
    parameters: list[ToolParameter]
    endpoint: str
    method: str
    protocol: Protocol
    response_format: ResponseFormat = "json"
    tags: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class DetectionResult:
    type: SpecType
    spec_url: str
    raw_content: str | None = None
    content_type: str | None = None


@dataclass
class ExecutionResult:
    status: int
    data: Any
    headers: dict[str, str] = field(default_factory=dict)
    raw: str | None = None
