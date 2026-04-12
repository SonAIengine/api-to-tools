# Authentication

## Auth Types

```python
from api_to_tools import AuthConfig

# Basic Auth
auth = AuthConfig(type="basic", username="user", password="pass")

# Bearer Token
auth = AuthConfig(type="bearer", token="eyJ...")

# API Key
auth = AuthConfig(type="api_key", key="X-API-Key", value="abc123")

# Cookie / Form Login
auth = AuthConfig(type="cookie", username="user", password="pass")

# OAuth2 Client Credentials
auth = AuthConfig(
    type="oauth2_client",
    token_url="https://auth.example.com/token",
    client_id="id",
    client_secret="secret",
)

# Custom Headers
auth = AuthConfig(type="custom", headers={"X-Tenant": "acme"})
```

## OAuth2 Token Renewal

OAuth2 tokens are automatically managed:

- Tokens are cached and reused until expiry
- Automatic refresh 30 seconds before expiration
- `refresh_token` flow supported
- 401 responses trigger automatic token refresh + retry

```python
auth = AuthConfig(
    type="oauth2_client",
    token_url="https://auth.example.com/token",
    client_id="id",
    client_secret="secret",
    refresh_token="rt_...",  # optional
)
```

## TLS Verification

Disable for self-signed certificates:

```python
auth = AuthConfig(type="bearer", token="...", verify_ssl=False)
```

## Security Scheme Extraction

OpenAPI security schemes are automatically parsed and attached to tools:

```python
from api_to_tools.parsers.openapi import security_schemes_to_auth_configs

configs = security_schemes_to_auth_configs(spec)
# Returns AuthConfig objects for each security scheme
```
