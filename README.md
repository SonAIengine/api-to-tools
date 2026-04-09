# api-to-tools

Universal library that converts **any API into LLM-callable tool definitions**.

Give it a website URL (with or without credentials) and it returns a list of
Tools that can be handed directly to Claude, OpenAI, or an MCP server — no
manual tool wiring required.

[![PyPI](https://img.shields.io/pypi/v/api-to-tools.svg)](https://pypi.org/project/api-to-tools/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

---

## What it does

```python
from api_to_tools import discover, AuthConfig

# Public OpenAPI / Swagger site
tools = discover("https://petstore.swagger.io")
# → 20 tools

# Private admin panel (login → auto-discover backend Swagger)
tools = discover(
    "https://admin.example.com/",
    auth=AuthConfig(type="cookie", username="admin", password="admin"),
)
# → 1090 tools (includes path parameters like {stdCtgNo}, body DTOs, enum values)

# Korean legacy enterprise (Nexacro/SSV, no Swagger at all)
tools = discover(
    "https://pro.example.com/",
    auth=AuthConfig(type="cookie", username="user", password="pass"),
)
# → Playwright crawler + SSV parser
```

One function call, one URL, one account — you get a complete tool catalog.

---

## Installation

```bash
pip install api-to-tools

# Optional: browser-based crawling for sites without a Swagger spec
pip install 'api-to-tools[crawler]'
python -m playwright install chromium
```

Requires Python 3.10+.

---

## Supported sources

| Source | Status | Notes |
|--------|:------:|-------|
| OpenAPI 3.0 / 3.1 | ✅ | Full body DTO, enum, response schema extraction |
| Swagger 2.0 (legacy) | ✅ | `parameters[].in=body`, `responses.200.schema` |
| WSDL / SOAP | ✅ | zeep-based, input/output schemas |
| GraphQL | ✅ | Introspection, selection set auto-build |
| gRPC / Protobuf | ✅ | `.proto` file parsing, streaming detection |
| AsyncAPI 3.0 | ✅ | WebSocket / MQTT operations |
| Authenticated Swagger | ✅ | Login → guess backend → Bearer probe |
| Nexacro / SSV | ✅ | Korean enterprise legacy (Lotte, 금융권 등) |
| JS bundle scanning | ✅ | Static analysis when no spec exists |
| Playwright crawler | ✅ | Dynamic SPA discovery with safe mode |

---

## How discovery works

`discover()` tries sources in priority order and stops at the first one that
works:

```
1. Direct spec URL (OpenAPI, WSDL, GraphQL)
2. Nexacro platform detection  → Nexacro crawler + SSV parser
3. Well-known paths probe     → /openapi.json, /swagger.json, /api-docs, ...
4. Authenticated Swagger      → login → guess backend → Bearer probe
5. JS bundle static scan      (opt-in: scan_js=True)
6. Playwright dynamic crawl   (opt-in: crawl=True)
```

Parallel probing and path priority mean most public APIs are discovered in
under 2 seconds.

---

## CLI

```bash
# Summarize an API
api-to-tools info https://admin.example.com \
  --login-user admin --login-pass admin

# List tools filtered by tag
api-to-tools list https://admin.example.com \
  --login-user admin --login-pass admin \
  --tag "회원 정보 관리"

# Export tool definitions
api-to-tools export https://admin.example.com \
  --login-user admin --login-pass admin \
  --format anthropic > tools.json

# Start an MCP server that exposes discovered APIs
api-to-tools serve https://admin.example.com \
  --login-user admin --login-pass admin \
  --name my-admin-api
```

### Authentication options (any subcommand)

```bash
--bearer TOKEN            # Bearer token
--basic USER:PASS         # HTTP Basic
--api-key NAME=VALUE      # API key (header/query)
--cookie NAME=VALUE       # Direct cookie (repeatable)
--header "Name: Value"    # Custom header (repeatable)
--login URL               # Form login URL
--login-user USERNAME     # Login username (shortcut for cookie login)
--login-pass PASSWORD     # Login password
```

### Discovery modes

```bash
--scan-js       # Static analysis of JavaScript bundles
--crawl         # Playwright browser crawl
--backend auto  # auto | system | playwright | lightpanda
--no-safe-mode  # DANGEROUS: allows destructive requests to reach server
```

---

## Python API

### Basic usage

```python
from api_to_tools import discover, execute, AuthConfig

tools = discover("https://date.nager.at/openapi/v3.json")
print(f"Found {len(tools)} tools")

# Execute a tool directly
tool = next(t for t in tools if "PublicHolidays" in t.name)
result = execute(tool, {"year": "2026", "countryCode": "KR"})
print(result.data)  # → list of 15 holidays
```

### Authentication

```python
# Basic Auth
AuthConfig(type="basic", username="admin", password="secret")

# Bearer token
AuthConfig(type="bearer", token="eyJ...")

# API key (header or query)
AuthConfig(type="api_key", key="X-API-Key", value="abc", location="header")

# Form login → session cookie
AuthConfig(type="cookie", username="user", password="pass")

# OAuth2 client credentials
AuthConfig(
    type="oauth2_client",
    token_url="https://auth.example.com/token",
    client_id="id",
    client_secret="secret",
)

# Custom headers
AuthConfig(type="custom", headers={"Authorization": "Custom xyz"})
```

### Filters

```python
tools = discover(
    url,
    auth=auth,
    tags=["users", "orders"],             # only specific tags
    methods=["GET"],                      # only GET
    path_filter=r"/api/v2/.*",            # regex on endpoint
    base_url="https://prod.example.com",  # override base URL
)
```

### LLM integration

```python
# Claude / Anthropic
from api_to_tools import to_anthropic_tools
import anthropic

client = anthropic.Anthropic()
response = client.messages.create(
    model="claude-sonnet-4-5",
    tools=to_anthropic_tools(tools),
    messages=[{"role": "user", "content": "Find orders from last week"}],
)

# OpenAI function calling
from api_to_tools import to_function_calling
openai_tools = to_function_calling(tools)

# MCP server (stdio)
from api_to_tools.adapters import create_mcp_server
server = create_mcp_server(tools, name="my-api")
server.run(transport="stdio")
```

### Utilities

```python
from api_to_tools import summarize, group_by_tag, search_tools

summary = summarize(tools)
# {"total": 1090, "by_method": {...}, "by_tag": {...}, "by_protocol": {...}}

groups = group_by_tag(tools)
order_tools = search_tools(tools, "order")
```

---

## Safe mode

When crawling a live production site, `safe_mode=True` (default) intercepts
mutation requests (POST/PUT/DELETE/PATCH) after login and fakes a success
response. The request is still captured for discovery, but **never reaches
the server** — so `deleteUser`, `save`, `send` etc. can't cause damage.

```python
discover(url, auth=auth, crawl=True, safe_mode=True)
```

A smart heuristic allows read-style POSTs (`getUserList`, `searchItems`,
auth endpoints) to pass through, since they're common in RPC-style APIs.

---

## Architecture

```
api_to_tools/
├── core.py              # discover, to_tools, execute
├── types.py             # Tool, ToolParameter, AuthConfig, …
├── constants.py         # Timeouts, well-known paths, keywords
├── auth.py              # Auth config → HTTP headers/cookies
│
├── detector/
│   ├── __init__.py            # Spec type detection, parallel probing
│   └── swagger_discovery.py   # Authenticated backend Swagger hunting
│
├── parsers/
│   ├── openapi.py       # OpenAPI 3.x + Swagger 2.0
│   ├── wsdl.py          # WSDL/SOAP via zeep
│   ├── graphql.py       # GraphQL introspection
│   ├── grpc.py          # .proto parsing
│   ├── ssv.py           # Nexacro SSV format
│   ├── nexacro.py       # Nexacro-specific crawler
│   ├── crawler.py       # Generic Playwright crawler
│   ├── jsbundle.py      # Static JS bundle scanner
│   ├── _param_builder.py  # Shared ToolParameter helpers
│   └── _browser_utils.py  # Shared Playwright helpers
│
├── executors/
│   ├── rest.py          # REST + Nexacro SSV execution
│   ├── soap.py          # SOAP calls via zeep
│   └── graphql.py       # GraphQL query execution
│
└── adapters/
    ├── formats.py       # OpenAI / Anthropic tool format
    └── mcp_adapter.py   # MCP server generation
```

---

## Development

```bash
git clone https://github.com/SonAIengine/api-to-tools.git
cd api-to-tools
pip install -e '.[dev]'

pytest              # 89 unit tests
```

### Debug logging

```python
from api_to_tools import enable_debug_logging
enable_debug_logging()
```

---

## License

MIT © SonAIengine
