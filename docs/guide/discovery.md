# API Discovery

## How It Works

`discover()` automatically detects the API type and parses it into Tool definitions:

```
1. Direct spec (OpenAPI, WSDL, GraphQL, HAR, AsyncAPI)
2. Nexacro platform detection
3. Well-known paths probe (/openapi.json, /swagger.json, etc.)
4. Authenticated Swagger (login → guess backend → probe)
5. JS bundle static scan (opt-in)
6. Playwright browser crawl (opt-in)
```

## Supported Sources

| Source | Auto-detected | Notes |
|--------|:---:|-------|
| OpenAPI 3.x | Yes | Full $ref resolution, security schemes |
| Swagger 2.0 | Yes | Legacy format support |
| WSDL/SOAP | Yes | Via zeep |
| GraphQL | Yes | Introspection query |
| gRPC | Manual | `.proto` file path |
| AsyncAPI 2.x/3.x | Yes | Channels → Tools |
| HAR files | Yes | `.har` file extension |
| Nexacro/SSV | Yes | Korean enterprise |

## Caching

Cache results to avoid re-fetching:

```python
tools = discover(url, cache_ttl=300)  # 5 minute TTL
```

## Multi-Source

Merge tools from multiple APIs:

```python
from api_to_tools import discover_all

tools = discover_all([
    "https://api-a.example.com/docs",
    "https://api-b.example.com/docs",
    "traffic.har",
])
```

Duplicate endpoints are deduplicated by `(method, path)`.
