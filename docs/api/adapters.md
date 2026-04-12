# Adapters

## LLM Format Converters

| Function | Target |
|----------|--------|
| `to_function_calling(tools)` | OpenAI function calling |
| `to_anthropic_tools(tools)` | Anthropic tool_use |
| `to_gemini_tools(tools)` | Google Gemini / Vertex AI |
| `to_bedrock_tools(tools)` | AWS Bedrock Converse API |
| `to_langchain_tools(tools)` | LangChain bind_tools |

All functions accept `list[Tool]` and return `list[dict]`.

## OpenAPI Export

```python
from api_to_tools import to_openapi_spec
from api_to_tools.adapters.openapi_export import to_openapi_json

spec = to_openapi_spec(tools, title="My API", version="1.0.0")
json_str = to_openapi_json(tools, title="My API")
```

## MCP Server

```python
from api_to_tools.adapters.mcp_adapter import create_mcp_server

server = create_mcp_server(tools, name="my-api")
server.run(transport="stdio")
```

## SDK Code Generation

```python
from api_to_tools import generate_python_sdk, generate_typescript_sdk

python_code = generate_python_sdk(tools, class_name="MyClient")
ts_code = generate_typescript_sdk(tools, class_name="MyClient")
```
