# Tool Execution

## Basic Execution

```python
from api_to_tools import discover, execute

tools = discover("https://api.example.com/docs")
tool = tools[0]
result = execute(tool, {"param": "value"})

print(result.status)   # HTTP status code
print(result.data)     # parsed response body
print(result.headers)  # response headers
print(result.raw)      # raw response text
```

## Rate Limiting

All requests are automatically rate-limited per domain:

- **Discovery**: 20 req/s
- **Execution**: 10 req/s

No configuration needed.

## Response Schema Enrichment

When a tool has no `response_schema` (e.g., from HAR/crawler), the first successful `execute()` call automatically infers and stores the schema:

```python
# Before: tool.metadata.get("response_schema") → None
result = execute(tool, args)
# After: tool.metadata["response_schema"] → {"type": "object", ...}
```

## Supported Protocols

| Protocol | Executor | Notes |
|----------|----------|-------|
| REST | `execute_rest` | JSON/XML, path/query/header/body params |
| SOAP | `execute_soap` | Via zeep |
| GraphQL | `execute_graphql` | Auto query builder |
| gRPC | `execute_grpc` | Reflection + JSON fallback |
| WebSocket/SSE | `execute_async` | Requires `pip install 'api-to-tools[websocket]'` |
