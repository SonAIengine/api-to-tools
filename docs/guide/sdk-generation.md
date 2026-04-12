# SDK Generation

Generate typed API client code from discovered tools.

## Python SDK

```python
from api_to_tools import discover, generate_python_sdk

tools = discover("https://petstore.swagger.io")
code = generate_python_sdk(tools, class_name="PetStoreClient")

with open("petstore_client.py", "w") as f:
    f.write(code)
```

Generated client features:

- Type-hinted parameters (`id: int`, `name: str | None`)
- Docstrings with parameter descriptions
- Context manager support (`with PetStoreClient() as client:`)
- Path/query/header/body parameter routing
- httpx-based HTTP client

### Usage

```python
from petstore_client import PetStoreClient

with PetStoreClient(
    base_url="https://petstore.swagger.io/v2",
    headers={"api_key": "special-key"},
) as client:
    pets = client.findpetsbystatus(status="available")
```

## TypeScript SDK

```python
from api_to_tools import generate_typescript_sdk

code = generate_typescript_sdk(tools, class_name="PetStoreClient")

with open("petstore_client.ts", "w") as f:
    f.write(code)
```

Generated client features:

- TypeScript types (`id: number`, `name?: string`)
- Async methods with `Promise<any>` return type
- Fetch API-based HTTP client
- Constructor with `baseUrl` and `headers` options
