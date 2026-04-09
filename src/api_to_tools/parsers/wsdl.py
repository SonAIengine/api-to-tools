"""WSDL/SOAP parser using zeep."""

from __future__ import annotations

from zeep import Client as ZeepClient
from zeep.xsd import Element

from api_to_tools.types import Tool, ToolParameter


def _xsd_type_to_json(type_name: str) -> str:
    type_map = {
        "string": "string", "normalizedString": "string", "token": "string",
        "int": "integer", "integer": "integer", "long": "integer", "short": "integer",
        "unsignedInt": "integer", "unsignedLong": "integer", "unsignedShort": "integer",
        "float": "number", "double": "number", "decimal": "number",
        "boolean": "boolean",
        "date": "string", "dateTime": "string", "time": "string",
    }
    # Strip namespace prefix
    clean = type_name.split("}")[-1] if "}" in type_name else type_name.split(":")[-1]
    return type_map.get(clean, "string")


def _extract_params(input_type) -> list[ToolParameter]:
    """Extract parameters from WSDL input message type."""
    params: list[ToolParameter] = []
    try:
        if hasattr(input_type, "elements"):
            for name, element in input_type.elements:
                type_name = str(element.type.name) if hasattr(element.type, "name") else "string"
                params.append(ToolParameter(
                    name=name,
                    type=_xsd_type_to_json(type_name),
                    required=not element.is_optional if hasattr(element, "is_optional") else True,
                    location="body",
                ))
    except Exception:
        pass
    return params


def parse_wsdl(input_data: str | dict, source_url: str | None = None) -> list[Tool]:
    """Parse WSDL spec into tools."""
    url = input_data if isinstance(input_data, str) else input_data.get("url", "")
    client = ZeepClient(url)
    tools: list[Tool] = []

    for service_name, service in client.wsdl.services.items():
        for port_name, port in service.ports.items():
            for op_name, operation in port.binding._operations.items():
                input_type = operation.input.body
                params = _extract_params(input_type) if input_type else []

                tools.append(Tool(
                    name=op_name,
                    description=f"{service_name}.{port_name}.{op_name}",
                    parameters=params,
                    endpoint=url,
                    method=op_name,
                    protocol="soap",
                    response_format="xml",
                    tags=[service_name, port_name],
                    metadata={"service": service_name, "port": port_name},
                ))

    return tools
