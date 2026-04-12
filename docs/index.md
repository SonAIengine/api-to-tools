# api-to-tools

**Universal library that converts any API into LLM-callable tool definitions.**

Give it a URL and it returns a list of Tools ready for Claude, OpenAI, Gemini, or an MCP server.

## Features

- **12+ API sources** — OpenAPI, Swagger, WSDL, GraphQL, gRPC, AsyncAPI, HAR files, and more
- **Auto-discovery** — Just provide a URL, authentication is handled automatically
- **6 LLM formats** — OpenAI, Anthropic, Gemini, Bedrock, LangChain, MCP
- **Execute tools** — Call discovered APIs with type-safe parameters
- **SDK generation** — Generate typed Python/TypeScript clients
- **Traffic capture** — Built-in proxy to record and convert browser traffic
- **350+ unit tests** — Comprehensive test coverage with CI/CD

## Quick Example

```python
from api_to_tools import discover, execute

tools = discover("https://petstore.swagger.io")
print(f"Found {len(tools)} tools")

tool = next(t for t in tools if "pet" in t.name.lower())
result = execute(tool, {"petId": 1})
print(result.data)
```

## Getting Started

- [Installation](getting-started/installation.md)
- [Quick Start](getting-started/quickstart.md)
