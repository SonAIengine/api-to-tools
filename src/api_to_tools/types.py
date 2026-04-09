"""Core type definitions."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal

SpecType = Literal[
    "openapi", "wsdl", "graphql", "grpc", "asyncapi", "jsonrpc",
    "jsbundle", "crawler", "nexacro", "static_spa", "cdp",
]
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


AuthType = Literal["basic", "bearer", "api_key", "cookie", "oauth2_client", "custom"]


@dataclass
class AuthConfig:
    """Authentication configuration for API discovery and execution.

    Examples:
        # Basic Auth
        AuthConfig(type="basic", username="user", password="pass")

        # Bearer Token
        AuthConfig(type="bearer", token="eyJ...")

        # API Key (in header)
        AuthConfig(type="api_key", key="X-API-Key", value="abc123")

        # API Key (in query)
        AuthConfig(type="api_key", key="api_key", value="abc123", location="query")

        # Cookie / Session
        AuthConfig(type="cookie", cookies={"session_id": "abc", "csrf": "xyz"})

        # Login form → auto session
        AuthConfig(type="cookie", login_url="https://example.com/login",
                   username="user", password="pass",
                   login_fields={"username_field": "email", "password_field": "passwd"})

        # OAuth2 Client Credentials
        AuthConfig(type="oauth2_client", token_url="https://auth.example.com/token",
                   client_id="id", client_secret="secret", scope="read write")

        # Custom headers
        AuthConfig(type="custom", headers={"Authorization": "Custom xyz", "X-Tenant": "acme"})
    """
    type: AuthType
    # Basic Auth
    username: str | None = None
    password: str | None = None
    # Bearer
    token: str | None = None
    # API Key
    key: str | None = None
    value: str | None = None
    location: Literal["header", "query"] = "header"
    # Cookie
    cookies: dict[str, str] = field(default_factory=dict)
    login_url: str | None = None
    login_fields: dict[str, str] = field(default_factory=dict)
    # OAuth2
    token_url: str | None = None
    client_id: str | None = None
    client_secret: str | None = None
    scope: str | None = None
    # Custom
    headers: dict[str, str] = field(default_factory=dict)


@dataclass
class ExecutionResult:
    status: int
    data: Any
    headers: dict[str, str] = field(default_factory=dict)
    raw: str | None = None
