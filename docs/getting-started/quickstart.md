# Quick Start

## Discover APIs

```python
from api_to_tools import discover

# From an OpenAPI spec URL
tools = discover("https://petstore.swagger.io")

# From a HAR file (browser recording)
tools = discover("recording.har")

# From multiple sources
from api_to_tools import discover_all
tools = discover_all([
    "https://api.example.com/openapi.json",
    "recording.har",
])
```

## Execute Tools

```python
from api_to_tools import execute

tool = tools[0]
result = execute(tool, {"param": "value"})
print(result.status)  # 200
print(result.data)    # response body
```

## Convert to LLM Format

```python
from api_to_tools import to_anthropic_tools, to_function_calling

# For Claude
claude_tools = to_anthropic_tools(tools)

# For OpenAI
openai_tools = to_function_calling(tools)
```

## With Authentication

```python
from api_to_tools import discover, AuthConfig

tools = discover(
    "https://admin.example.com/",
    auth=AuthConfig(type="cookie", username="admin", password="admin"),
)
```

## Generate SDK

```python
from api_to_tools import generate_python_sdk

code = generate_python_sdk(tools, class_name="MyClient")
with open("client.py", "w") as f:
    f.write(code)
```
