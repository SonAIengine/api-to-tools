# Parsers

All parsers follow the signature: `(input_data, source_url=None) -> list[Tool]`

## OpenAPI / Swagger

```python
from api_to_tools.parsers.openapi import parse_openapi

tools = parse_openapi("https://api.example.com/openapi.json")
tools = parse_openapi(spec_dict)
tools = parse_openapi(yaml_string)
```

## AsyncAPI

```python
from api_to_tools.parsers.asyncapi import parse_asyncapi

tools = parse_asyncapi(asyncapi_dict)  # v2.x or v3.x
```

## HAR

```python
from api_to_tools.parsers.har import parse_har

tools = parse_har("recording.har")
tools = parse_har(har_dict)
```

## GraphQL

```python
from api_to_tools.parsers.graphql import parse_graphql

tools = parse_graphql("https://api.example.com/graphql")
```

## gRPC

```python
from api_to_tools.parsers.grpc import parse_grpc

tools = parse_grpc("service.proto")
tools = parse_grpc(proto_content_string)
```

## WSDL / SOAP

```python
from api_to_tools.parsers.wsdl import parse_wsdl

tools = parse_wsdl("https://example.com/service?wsdl")
```
