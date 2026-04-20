# api-to-tools

Universal library that converts **any API into LLM-callable tool definitions**.

Give it a website URL (with or without credentials) and it returns a list of
Tools that can be handed directly to Claude, OpenAI, Gemini, or an MCP server — no
manual tool wiring required.

[![PyPI](https://img.shields.io/pypi/v/api-to-tools.svg)](https://pypi.org/project/api-to-tools/)
[![CI](https://github.com/SonAIengine/api-to-tools/actions/workflows/ci.yml/badge.svg)](https://github.com/SonAIengine/api-to-tools/actions/workflows/ci.yml)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![SafeSkill 93/100](https://img.shields.io/badge/SafeSkill-93%2F100_Verified%20Safe-brightgreen)](https://safeskill.dev/scan/sonaiengine-api-to-tools)

---

## What it does

```python
from api_to_tools import discover, discover_all, AuthConfig

# Public OpenAPI / Swagger site
tools = discover("https://petstore.swagger.io")
# → 20 tools

# Browser network recording (no Swagger at all)
tools = discover("recording.har")
# → Tools inferred from actual HTTP traffic

# Multiple sources merged
tools = discover_all([
    "https://api.example.com/openapi.json",
    "https://internal.example.com/api-docs",
    "recording.har",
])

# Private admin panel (login → auto-discover backend Swagger)
tools = discover(
    "https://admin.example.com/",
    auth=AuthConfig(type="cookie", username="admin", password="admin"),
)
# → 1090 tools
```

One function call, one URL, one account — you get a complete tool catalog.

---

## Installation

```bash
pip install api-to-tools

# Optional extras
pip install 'api-to-tools[crawler]'     # Playwright browser crawling
pip install 'api-to-tools[websocket]'   # WebSocket/SSE executor
python -m playwright install chromium   # for crawler
```

Requires Python 3.10+.

---

## Supported sources

| Source | Status | Notes |
|--------|:------:|-------|
| OpenAPI 3.0 / 3.1 | ✅ | Full body DTO, enum, response schema, security scheme extraction |
| Swagger 2.0 (legacy) | ✅ | `parameters[].in=body`, `responses.200.schema`, `securityDefinitions` |
| WSDL / SOAP | ✅ | zeep-based, input/output schemas |
| GraphQL | ✅ | Introspection, selection set auto-build |
| gRPC / Protobuf | ✅ | `.proto` file parsing, streaming detection, executor with reflection |
| AsyncAPI 2.x / 3.x | ✅ | WebSocket, MQTT, Kafka, AMQP channels → Tools |
| HAR files | ✅ | Browser DevTools network recordings → Tools with inferred schemas |
| Traffic proxy | ✅ | Built-in HTTP proxy → auto-record → Tools |
| Authenticated Swagger | ✅ | Login → guess backend → Bearer probe |
| Nexacro / SSV | ✅ | Korean enterprise legacy (Lotte, 금융권 등) |
| JS bundle scanning | ✅ | Static analysis when no spec exists |
| Playwright crawler | ✅ | Dynamic SPA discovery with safe mode |
| CDP crawler | ✅ | Chrome DevTools Protocol (no Playwright needed) |

---

## How discovery works

`discover()` tries sources in priority order and stops at the first one that
works:

```
1. Direct spec URL (OpenAPI, WSDL, GraphQL, HAR, AsyncAPI)
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

### Multiple sources

```python
from api_to_tools import discover_all

tools = discover_all([
    "https://api.example.com/openapi.json",
    "https://internal.example.com/api-docs",
    "recording.har",
])
# Merges tools, deduplicates by (endpoint, method), resolves name collisions
```

### HAR file parsing

```python
# Export HAR from browser DevTools → Network → Export HAR
tools = discover("recording.har")

# Or parse directly
from api_to_tools.parsers.har import parse_har
tools = parse_har("recording.har")
```

### Traffic proxy capture

```python
from api_to_tools.proxy import TrafficRecorder

# Start proxy, browse the site, stop → Tools
with TrafficRecorder(port=8080, target_host="api.example.com") as recorder:
    print("Configure browser proxy to http://localhost:8080")
    input("Press Enter when done browsing...")

tools = recorder.to_tools()
recorder.save_har("captured.har")  # save for later

# Or quick capture for a fixed duration
from api_to_tools.proxy import capture_traffic
tools = capture_traffic(port=8080, duration=60, target_host="api.example.com")
```

### Caching

```python
# Cache discovery results for 5 minutes
tools = discover("https://api.example.com/docs", cache_ttl=300)
tools = discover("https://api.example.com/docs", cache_ttl=300)  # instant cache hit

# Manual invalidation
from api_to_tools.cache import get_discover_cache
get_discover_cache().invalidate("https://api.example.com/docs")
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

# OAuth2 client credentials (auto-renewal on expiry)
AuthConfig(
    type="oauth2_client",
    token_url="https://auth.example.com/token",
    client_id="id",
    client_secret="secret",
    scope="read write",
)

# OAuth2 with refresh token
AuthConfig(
    type="oauth2_client",
    token_url="https://auth.example.com/token",
    client_id="id",
    client_secret="secret",
    refresh_token="rt_...",
)

# Custom headers
AuthConfig(type="custom", headers={"Authorization": "Custom xyz"})

# Disable TLS verification (self-signed certs)
AuthConfig(type="bearer", token="...", verify_ssl=False)
```

OAuth2 tokens are automatically refreshed before expiry. On 401 responses,
`execute()` refreshes the token and retries once.

### LLM integration

```python
# Claude / Anthropic
from api_to_tools import to_anthropic_tools
response = client.messages.create(
    model="claude-sonnet-4-5",
    tools=to_anthropic_tools(tools),
    messages=[...],
)

# OpenAI function calling
from api_to_tools import to_function_calling
openai_tools = to_function_calling(tools)

# Google Gemini / Vertex AI
from api_to_tools import to_gemini_tools
gemini_tools = to_gemini_tools(tools)

# AWS Bedrock
from api_to_tools import to_bedrock_tools
bedrock_tools = to_bedrock_tools(tools)

# LangChain
from api_to_tools import to_langchain_tools
lc_tools = to_langchain_tools(tools)

# MCP server (stdio)
from api_to_tools.adapters.mcp_adapter import create_mcp_server
server = create_mcp_server(tools, name="my-api")
server.run(transport="stdio")
```

### OpenAPI spec export

```python
from api_to_tools import to_openapi_spec

# Generate OpenAPI 3.0 spec from discovered tools
spec = to_openapi_spec(tools, title="My API", version="1.0.0")

# Save as JSON
from api_to_tools.adapters.openapi_export import to_openapi_json
with open("openapi.json", "w") as f:
    f.write(to_openapi_json(tools, title="My API"))
```

### SDK code generation

```python
from api_to_tools import generate_python_sdk, generate_typescript_sdk

# Generate typed Python client
code = generate_python_sdk(tools, class_name="PetStoreClient")
with open("petstore_client.py", "w") as f:
    f.write(code)

# Generate TypeScript client
ts_code = generate_typescript_sdk(tools, class_name="PetStoreClient")
with open("petstore_client.ts", "w") as f:
    f.write(ts_code)
```

### Smoke testing

```python
from api_to_tools import run_smoke_tests, generate_test_code

# Run smoke tests (GET only by default)
report = run_smoke_tests(tools, auth=auth)
print(report.summary)  # "15 passed, 2 failed, 8 skipped / 25 total"

# Include mutations (POST/PUT/DELETE)
report = run_smoke_tests(tools, include_mutations=True)

# Dry run (no network calls)
report = run_smoke_tests(tools, dry_run=True)

# Generate pytest file
code = generate_test_code(tools)
with open("test_api_smoke.py", "w") as f:
    f.write(code)
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

## Rate limiting

All outgoing requests are rate-limited per domain to prevent overwhelming
target servers:

- **Discovery probing**: 20 requests/second
- **API execution**: 10 requests/second

Rate limiting is automatic and requires no configuration.

---

## Architecture

```
api_to_tools/
├── core.py              # discover, discover_all, to_tools, execute
├── types.py             # Tool, ToolParameter, AuthConfig, ExecutionResult, …
├── constants.py         # Timeouts, rate limits, well-known paths
├── auth.py              # Auth config → HTTP headers/cookies, TokenManager
├── cache.py             # TTL-based discover() result cache
├── rate_limiter.py      # Per-domain token bucket rate limiter
├── testing.py           # Smoke test runner + pytest code generator
├── codegen.py           # Python / TypeScript SDK code generator
├── proxy.py             # HTTP traffic capture proxy → HAR → Tools
│
├── detector/
│   ├── __init__.py            # Spec type detection, parallel probing
│   └── swagger_discovery.py   # Authenticated backend Swagger hunting
│
├── parsers/
│   ├── openapi.py       # OpenAPI 3.x + Swagger 2.0 + security schemes
│   ├── asyncapi.py      # AsyncAPI 2.x / 3.x
│   ├── har.py           # HAR file parser (browser recordings)
│   ├── wsdl.py          # WSDL/SOAP via zeep
│   ├── graphql.py       # GraphQL introspection
│   ├── grpc.py          # .proto parsing
│   ├── ssv.py           # Nexacro SSV format
│   ├── nexacro.py       # Nexacro-specific crawler
│   ├── crawler.py       # Generic Playwright crawler
│   ├── cdp_crawler.py   # Chrome DevTools Protocol crawler
│   ├── static_spa.py    # Browserless JS bundle analysis
│   ├── jsbundle.py      # Static JS bundle scanner
│   ├── _param_builder.py  # Shared ToolParameter helpers
│   └── _browser_utils.py  # Shared Playwright helpers
│
├── executors/
│   ├── rest.py          # REST + Nexacro SSV execution
│   ├── soap.py          # SOAP calls via zeep
│   ���── graphql.py       # GraphQL query execution
│   ├── grpc_exec.py     # gRPC execution (reflection + JSON fallback)
│   └── async_exec.py    # WebSocket / SSE execution
│
└── adapters/
    ├── formats.py         # OpenAI / Anthropic / Gemini / Bedrock / LangChain
    ├── openapi_export.py  # Tool → OpenAPI 3.0 spec (reverse export)
    └── mcp_adapter.py     # MCP server generation
```

---

## Development

```bash
git clone https://github.com/SonAIengine/api-to-tools.git
cd api-to-tools
pip install -e '.[dev]'

pytest              # 350 unit tests
ruff check src/     # lint
```

### Debug logging

```python
from api_to_tools import enable_debug_logging
enable_debug_logging()
```

---

## License

MIT © SonAIengine
