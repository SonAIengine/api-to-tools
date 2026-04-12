# Types

## `Tool`

```python
@dataclass
class Tool:
    name: str                    # Unique identifier
    description: str             # Human-readable description
    parameters: list[ToolParameter]
    endpoint: str                # Full URL
    method: str                  # HTTP method or protocol-specific
    protocol: Protocol           # "rest", "soap", "graphql", "grpc", "async"
    response_format: ResponseFormat = "json"
    tags: list[str] = []
    metadata: dict = {}          # response_schema, security_schemes, etc.
```

## `ToolParameter`

```python
@dataclass
class ToolParameter:
    name: str
    type: str                    # JSON Schema type
    required: bool = False
    location: ParameterIn | None = None  # "path", "query", "header", "body"
    description: str | None = None
    enum: list[str] | None = None
    default: Any = None
    schema: dict | None = None   # Nested JSON Schema
```

## `AuthConfig`

```python
@dataclass
class AuthConfig:
    type: AuthType               # "basic", "bearer", "api_key", "cookie", "oauth2_client", "custom"
    username: str | None = None
    password: str | None = None
    token: str | None = None
    key: str | None = None
    value: str | None = None
    location: Literal["header", "query"] = "header"
    cookies: dict[str, str] = {}
    login_url: str | None = None
    login_fields: dict[str, str] = {}
    token_url: str | None = None
    client_id: str | None = None
    client_secret: str | None = None
    scope: str | None = None
    refresh_token: str | None = None
    headers: dict[str, str] = {}
    verify_ssl: bool = True
```

## `ExecutionResult`

```python
@dataclass
class ExecutionResult:
    status: int          # HTTP status code
    data: Any            # Parsed response body
    headers: dict = {}   # Response headers
    raw: str | None = None  # Raw response text
```
