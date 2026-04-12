# LLM Integration

## Supported Formats

| Provider | Function | Import |
|----------|----------|--------|
| OpenAI | `to_function_calling()` | `from api_to_tools import to_function_calling` |
| Anthropic (Claude) | `to_anthropic_tools()` | `from api_to_tools import to_anthropic_tools` |
| Google Gemini | `to_gemini_tools()` | `from api_to_tools import to_gemini_tools` |
| Google Vertex AI | `to_vertex_ai_tools()` | `from api_to_tools import to_vertex_ai_tools` |
| AWS Bedrock | `to_bedrock_tools()` | `from api_to_tools import to_bedrock_tools` |
| LangChain | `to_langchain_tools()` | `from api_to_tools import to_langchain_tools` |
| MCP Server | `create_mcp_server()` | `from api_to_tools.adapters.mcp_adapter import create_mcp_server` |

## Claude / Anthropic

```python
from api_to_tools import discover, to_anthropic_tools
import anthropic

tools = discover("https://api.example.com/docs")
client = anthropic.Anthropic()
response = client.messages.create(
    model="claude-sonnet-4-5",
    tools=to_anthropic_tools(tools),
    messages=[{"role": "user", "content": "List available pets"}],
)
```

## OpenAI

```python
from api_to_tools import to_function_calling

response = openai.chat.completions.create(
    model="gpt-4",
    tools=to_function_calling(tools),
    messages=[...],
)
```

## Google Gemini

```python
from api_to_tools import to_gemini_tools
import google.generativeai as genai

model = genai.GenerativeModel("gemini-pro", tools=to_gemini_tools(tools))
```

## MCP Server

```python
from api_to_tools.adapters.mcp_adapter import create_mcp_server

server = create_mcp_server(tools, name="my-api")
server.run(transport="stdio")
```

## OpenAPI Export

Generate OpenAPI 3.0 spec from discovered tools (reverse export):

```python
from api_to_tools import to_openapi_spec

spec = to_openapi_spec(tools, title="My API", version="1.0.0")
```
