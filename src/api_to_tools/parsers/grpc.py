"""gRPC / Protocol Buffers parser."""

from __future__ import annotations

import subprocess
import tempfile
from pathlib import Path

from api_to_tools.types import Tool, ToolParameter

# protobuf type -> JSON Schema type
PROTO_TYPE_MAP = {
    "TYPE_DOUBLE": "number", "TYPE_FLOAT": "number",
    "TYPE_INT64": "integer", "TYPE_UINT64": "integer",
    "TYPE_INT32": "integer", "TYPE_UINT32": "integer",
    "TYPE_FIXED64": "integer", "TYPE_FIXED32": "integer",
    "TYPE_SFIXED32": "integer", "TYPE_SFIXED64": "integer",
    "TYPE_SINT32": "integer", "TYPE_SINT64": "integer",
    "TYPE_BOOL": "boolean",
    "TYPE_STRING": "string",
    "TYPE_BYTES": "string",
    "TYPE_ENUM": "string",
}


def parse_grpc(input_data: str | dict, source_url: str | None = None) -> list[Tool]:
    """Parse .proto file into tools.

    input_data: path to .proto file or raw proto content string
    """
    from google.protobuf import descriptor_pb2
    from google.protobuf.compiler import plugin_pb2

    proto_path: Path
    if isinstance(input_data, str) and (input_data.endswith(".proto") or Path(input_data).exists()):
        proto_path = Path(input_data)
        proto_content = proto_path.read_text()
    elif isinstance(input_data, str):
        proto_content = input_data
        # Write to temp file for protoc
        tmp = tempfile.NamedTemporaryFile(suffix=".proto", mode="w", delete=False)
        tmp.write(proto_content)
        tmp.flush()
        proto_path = Path(tmp.name)
    else:
        raise ValueError("gRPC parser expects a .proto file path or proto content string")

    # Use protoc to get FileDescriptorSet
    with tempfile.NamedTemporaryFile(suffix=".bin", delete=False) as out_file:
        try:
            subprocess.run(
                ["python3", "-m", "grpc_tools.protoc",
                 f"--proto_path={proto_path.parent}",
                 f"--descriptor_set_out={out_file.name}",
                 "--include_source_info",
                 proto_path.name],
                check=True, capture_output=True, text=True,
            )
        except (subprocess.CalledProcessError, FileNotFoundError):
            # Fallback: simple regex-based parsing
            return _parse_proto_regex(proto_content)

        descriptor_set = descriptor_pb2.FileDescriptorSet()
        descriptor_set.ParseFromString(Path(out_file.name).read_bytes())

    tools: list[Tool] = []
    for file_desc in descriptor_set.file:
        # Build message field lookup
        msg_fields: dict[str, list[ToolParameter]] = {}
        for msg in file_desc.message_type:
            params = []
            for field in msg.field:
                field_type_name = descriptor_pb2.FieldDescriptorProto.Type.Name(field.type)
                params.append(ToolParameter(
                    name=field.name,
                    type=PROTO_TYPE_MAP.get(field_type_name, "object"),
                    required=field.label == descriptor_pb2.FieldDescriptorProto.LABEL_REQUIRED,
                    location="body",
                ))
            msg_fields[msg.name] = params

        pkg = file_desc.package
        for service in file_desc.service:
            for method in service.method:
                req_type = method.input_type.split(".")[-1]
                resp_type = method.output_type.split(".")[-1]
                full_name = f"{pkg}.{service.name}.{method.name}" if pkg else f"{service.name}.{method.name}"

                tools.append(Tool(
                    name=f"{service.name}_{method.name}",
                    description=f"gRPC: {full_name}",
                    parameters=msg_fields.get(req_type, []),
                    endpoint=full_name,
                    method=method.name,
                    protocol="grpc",
                    response_format="protobuf",
                    tags=[service.name],
                    metadata={
                        "service": service.name,
                        "request_type": req_type,
                        "response_type": resp_type,
                        "client_streaming": method.client_streaming,
                        "server_streaming": method.server_streaming,
                    },
                ))

    return tools


def _parse_proto_regex(content: str) -> list[Tool]:
    """Fallback regex-based .proto parser."""
    import re

    tools: list[Tool] = []

    # Find package
    pkg_match = re.search(r"package\s+([\w.]+);", content)
    pkg = pkg_match.group(1) if pkg_match else ""

    # Find messages and their fields
    msg_fields: dict[str, list[ToolParameter]] = {}
    for msg_match in re.finditer(r"message\s+(\w+)\s*\{([^}]+)\}", content):
        msg_name = msg_match.group(1)
        fields_text = msg_match.group(2)
        params = []
        for field_match in re.finditer(r"(\w+)\s+(\w+)\s*=\s*\d+", fields_text):
            field_type, field_name = field_match.group(1), field_match.group(2)
            json_type = {"string": "string", "int32": "integer", "int64": "integer",
                         "float": "number", "double": "number", "bool": "boolean",
                         "bytes": "string"}.get(field_type, "object")
            params.append(ToolParameter(name=field_name, type=json_type, required=False, location="body"))
        msg_fields[msg_name] = params

    # Find services
    for svc_match in re.finditer(r"service\s+(\w+)\s*\{([^}]+)\}", content):
        svc_name = svc_match.group(1)
        svc_body = svc_match.group(2)
        for rpc_match in re.finditer(r"rpc\s+(\w+)\s*\(\s*(stream\s+)?(\w+)\s*\)\s*returns\s*\(\s*(stream\s+)?(\w+)\s*\)", svc_body):
            method_name = rpc_match.group(1)
            req_stream = bool(rpc_match.group(2))
            req_type = rpc_match.group(3)
            resp_stream = bool(rpc_match.group(4))
            resp_type = rpc_match.group(5)
            full_name = f"{pkg}.{svc_name}.{method_name}" if pkg else f"{svc_name}.{method_name}"

            tools.append(Tool(
                name=f"{svc_name}_{method_name}",
                description=f"gRPC: {full_name}",
                parameters=msg_fields.get(req_type, []),
                endpoint=full_name,
                method=method_name,
                protocol="grpc",
                response_format="protobuf",
                tags=[svc_name],
                metadata={
                    "service": svc_name,
                    "request_type": req_type,
                    "response_type": resp_type,
                    "client_streaming": req_stream,
                    "server_streaming": resp_stream,
                },
            ))

    return tools
