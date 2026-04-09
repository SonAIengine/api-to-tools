"""WSDL/SOAP parser using zeep."""

from __future__ import annotations

from zeep import Client as ZeepClient

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
    clean = type_name.split("}")[-1] if "}" in type_name else type_name.split(":")[-1]
    return type_map.get(clean, "string")


def _extract_params_from_type(xsd_type) -> list[ToolParameter]:
    """Extract parameters from a zeep XSD type, handling nested ComplexTypes."""
    params: list[ToolParameter] = []

    # Method 1: elements attribute (ComplexType with sequence)
    if hasattr(xsd_type, "elements"):
        try:
            for name, element in xsd_type.elements:
                type_name = "string"
                if hasattr(element, "type") and hasattr(element.type, "name"):
                    type_name = str(element.type.name) or "string"

                is_required = True
                if hasattr(element, "is_optional"):
                    is_required = not element.is_optional
                elif hasattr(element, "min_occurs"):
                    is_required = element.min_occurs > 0

                desc = None
                if hasattr(element, "annotation") and element.annotation:
                    desc = str(element.annotation)

                params.append(ToolParameter(
                    name=name,
                    type=_xsd_type_to_json(type_name),
                    required=is_required,
                    location="body",
                    description=desc,
                ))
        except Exception:
            pass

    # Method 2: elements_nested (alternative accessor in some zeep versions)
    if not params and hasattr(xsd_type, "elements_nested"):
        try:
            for element_list in xsd_type.elements_nested:
                if hasattr(element_list, "__iter__"):
                    for element in element_list:
                        name = getattr(element, "name", None) or getattr(element, "attr_name", None)
                        if not name:
                            continue
                        type_name = "string"
                        if hasattr(element, "type") and hasattr(element.type, "name"):
                            type_name = str(element.type.name) or "string"
                        params.append(ToolParameter(
                            name=name,
                            type=_xsd_type_to_json(type_name),
                            required=True,
                            location="body",
                        ))
        except Exception:
            pass

    # Method 3: Fallback - use zeep's describe to get element info
    if not params:
        try:
            # Try accessing the type directly for simple types
            if hasattr(xsd_type, "type") and hasattr(xsd_type.type, "elements"):
                for name, element in xsd_type.type.elements:
                    type_name = str(element.type.name) if hasattr(element.type, "name") else "string"
                    params.append(ToolParameter(
                        name=name,
                        type=_xsd_type_to_json(type_name),
                        required=True,
                        location="body",
                    ))
        except Exception:
            pass

    return params


def _extract_response_fields(output_type) -> dict | None:
    """Extract response schema from WSDL output type."""
    fields = {}
    try:
        if hasattr(output_type, "elements"):
            for name, element in output_type.elements:
                type_name = "string"
                if hasattr(element, "type") and hasattr(element.type, "name"):
                    type_name = str(element.type.name) or "string"
                fields[name] = _xsd_type_to_json(type_name)
    except Exception:
        pass
    return fields if fields else None


def parse_wsdl(input_data: str | dict, source_url: str | None = None) -> list[Tool]:
    """Parse WSDL spec into tools."""
    url = input_data if isinstance(input_data, str) else input_data.get("url", "")
    client = ZeepClient(url)
    tools: list[Tool] = []

    for service_name, service in client.wsdl.services.items():
        for port_name, port in service.ports.items():
            for op_name, operation in port.binding._operations.items():
                # Extract input parameters
                input_type = operation.input.body
                params = _extract_params_from_type(input_type) if input_type else []

                # Extract output/response schema
                metadata: dict = {"service": service_name, "port": port_name}
                output_type = operation.output.body if hasattr(operation.output, "body") else None
                if output_type:
                    resp_fields = _extract_response_fields(output_type)
                    if resp_fields:
                        metadata["response_schema"] = resp_fields

                # Build description from documentation if available
                desc = f"{service_name}.{port_name}.{op_name}"
                if hasattr(operation, "documentation") and operation.documentation:
                    desc = f"{operation.documentation}\n({desc})"

                tools.append(Tool(
                    name=op_name,
                    description=desc,
                    parameters=params,
                    endpoint=url,
                    method=op_name,
                    protocol="soap",
                    response_format="xml",
                    tags=[service_name, port_name],
                    metadata=metadata,
                ))

    return tools
