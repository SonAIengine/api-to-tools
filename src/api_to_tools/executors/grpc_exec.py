"""gRPC executor using grpcio.

Supports unary-unary calls via generic (byte-level) invocation.
Requires the server to support gRPC reflection for runtime schema discovery,
or falls back to sending JSON-encoded payloads as raw bytes.

Limitations:
- Only unary-unary calls (no streaming) in this version.
- Without reflection, request/response are JSON-encoded (not protobuf binary).
"""

from __future__ import annotations

import json

from api_to_tools._logging import get_logger
from api_to_tools.constants import DEFAULT_EXECUTOR_TIMEOUT
from api_to_tools.types import AuthConfig, ExecutionResult, Tool

log = get_logger("grpc_exec")


def _build_channel(endpoint: str, *, auth: AuthConfig | None = None, timeout: float = DEFAULT_EXECUTOR_TIMEOUT):
    """Create a gRPC channel to the target server."""
    import grpc

    # Extract host:port from endpoint (e.g. "pkg.Service.Method" → use metadata)
    # The actual target is in tool.metadata["grpc_target"] or derived from endpoint
    target = endpoint

    # Check if target looks like host:port
    if ":" in target and "/" not in target:
        pass  # already host:port
    else:
        # Default to localhost:50051 if endpoint is a method path
        target = "localhost:50051"

    verify_ssl = True
    if auth:
        verify_ssl = auth.verify_ssl

    if not verify_ssl or target.startswith("localhost") or target.startswith("127."):
        channel = grpc.insecure_channel(target)
    else:
        credentials = grpc.ssl_channel_credentials()
        channel = grpc.secure_channel(target, credentials)

    return channel, target


def _try_reflection_call(
    channel,
    full_method: str,
    args: dict,
    timeout: float,
) -> ExecutionResult | None:
    """Attempt to call via gRPC reflection (fully typed protobuf)."""
    try:
        from grpc_reflection.v1alpha import reflection_pb2, reflection_pb2_grpc
        from google.protobuf import descriptor_pool, descriptor_pb2
        from google.protobuf.json_format import MessageToDict, ParseDict
    except ImportError:
        return None

    try:
        stub = reflection_pb2_grpc.ServerReflectionStub(channel)

        # Parse method path: "package.Service/Method" or "package.Service.Method"
        if "/" in full_method:
            service_name, method_name = full_method.rsplit("/", 1)
        elif "." in full_method:
            parts = full_method.rsplit(".", 1)
            service_name, method_name = parts[0], parts[1]
        else:
            return None

        # Request service file descriptor
        responses = stub.ServerReflectionInfo(iter([
            reflection_pb2.ServerReflectionRequest(
                file_containing_symbol=service_name,
            ),
        ]))

        pool = descriptor_pool.DescriptorPool()
        for resp in responses:
            if resp.HasField("file_descriptor_response"):
                for fd_bytes in resp.file_descriptor_response.file_descriptor_proto:
                    fd = descriptor_pb2.FileDescriptorProto()
                    fd.ParseFromString(fd_bytes)
                    try:
                        pool.Add(fd)
                    except Exception:
                        pass

        # Find service and method descriptors
        svc_desc = pool.FindServiceByName(service_name)
        method_desc = svc_desc.FindMethodByName(method_name)

        # Get message types
        req_desc = pool.FindMessageTypeByName(method_desc.input_type.full_name)
        resp_desc = pool.FindMessageTypeByName(method_desc.output_type.full_name)

        # Build request message
        from google.protobuf import message_factory
        factory = message_factory.MessageFactory(pool)
        req_class = factory.GetPrototype(req_desc)
        resp_class = factory.GetPrototype(resp_desc)

        request = ParseDict(args, req_class())

        # Make the call
        full_path = f"/{service_name}/{method_name}"
        response_bytes = channel.unary_unary(
            full_path,
            request_serializer=req_class.SerializeToString,
            response_deserializer=resp_class.FromString,
        )(request, timeout=timeout)

        data = MessageToDict(response_bytes, preserving_proto_field_name=True)
        return ExecutionResult(status=200, data=data, raw=str(data))

    except Exception as e:
        log.debug("Reflection call failed: %s", e)
        return None


def _generic_json_call(
    channel,
    full_method: str,
    args: dict,
    timeout: float,
) -> ExecutionResult:
    """Fallback: send args as JSON bytes, receive JSON bytes."""
    import grpc

    # Build method path
    if "/" in full_method:
        method_path = f"/{full_method}"
    elif "." in full_method:
        parts = full_method.rsplit(".", 1)
        method_path = f"/{parts[0]}/{parts[1]}"
    else:
        method_path = f"/{full_method}"

    request_bytes = json.dumps(args).encode("utf-8")

    try:
        response_bytes = channel.unary_unary(
            method_path,
            request_serializer=lambda x: x,
            response_deserializer=lambda x: x,
        )(request_bytes, timeout=timeout)

        try:
            data = json.loads(response_bytes)
        except (json.JSONDecodeError, ValueError, TypeError):
            data = response_bytes.decode("utf-8", errors="replace") if isinstance(response_bytes, bytes) else str(response_bytes)

        return ExecutionResult(status=200, data=data, raw=str(data))

    except grpc.RpcError as e:
        code = e.code() if hasattr(e, "code") else None
        status = 500
        if code:
            # Map gRPC codes to approximate HTTP status
            grpc_to_http = {
                grpc.StatusCode.OK: 200,
                grpc.StatusCode.NOT_FOUND: 404,
                grpc.StatusCode.PERMISSION_DENIED: 403,
                grpc.StatusCode.UNAUTHENTICATED: 401,
                grpc.StatusCode.INVALID_ARGUMENT: 400,
                grpc.StatusCode.UNIMPLEMENTED: 501,
                grpc.StatusCode.UNAVAILABLE: 503,
                grpc.StatusCode.DEADLINE_EXCEEDED: 504,
            }
            status = grpc_to_http.get(code, 500)

        details = e.details() if hasattr(e, "details") else str(e)
        return ExecutionResult(
            status=status,
            data={"error": details, "grpc_code": str(code) if code else "UNKNOWN"},
            raw=details,
        )


def execute_grpc(tool: Tool, args: dict, *, auth: AuthConfig | None = None) -> ExecutionResult:
    """Execute a gRPC call.

    Uses the tool's endpoint as the full method path (e.g. 'package.Service.Method').
    The gRPC target (host:port) is read from tool.metadata['grpc_target'],
    falling back to localhost:50051.
    """
    import grpc

    full_method = tool.endpoint
    target = tool.metadata.get("grpc_target", "")
    timeout = DEFAULT_EXECUTOR_TIMEOUT

    # Override endpoint with actual target if provided
    if target:
        channel_endpoint = target
    elif ":" in full_method and "/" not in full_method and "." not in full_method:
        channel_endpoint = full_method
    else:
        channel_endpoint = "localhost:50051"

    verify = auth.verify_ssl if auth else True
    if not verify or channel_endpoint.startswith("localhost") or channel_endpoint.startswith("127."):
        channel = grpc.insecure_channel(channel_endpoint)
    else:
        credentials = grpc.ssl_channel_credentials()
        channel = grpc.secure_channel(channel_endpoint, credentials)

    try:
        # Try reflection first (proper protobuf serialization)
        result = _try_reflection_call(channel, full_method, args, timeout)
        if result:
            return result

        # Fallback to generic JSON call
        log.info("Using generic JSON call for %s", full_method)
        return _generic_json_call(channel, full_method, args, timeout)
    finally:
        channel.close()
