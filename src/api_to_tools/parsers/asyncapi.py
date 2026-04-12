"""AsyncAPI 2.x / 3.x parser.

Converts AsyncAPI specs (WebSocket, MQTT, Kafka, AMQP, etc.) into Tool definitions.
Each channel/operation becomes a Tool with message schema as parameters.

Supports:
- AsyncAPI 2.x: channels → publish/subscribe operations
- AsyncAPI 3.x: channels + operations (new structure)
- $ref resolution (single-level, inline components)
- Message payload → ToolParameter conversion
"""

from __future__ import annotations

import json

import httpx
import yaml

from api_to_tools._logging import get_logger
from api_to_tools.constants import DEFAULT_SPEC_FETCH_TIMEOUT
from api_to_tools.parsers._param_builder import (
    build_params_from_json_schema,
    sanitize_name,
    schema_type_str,
)
from api_to_tools.types import Tool, ToolParameter

log = get_logger("asyncapi")


def _resolve_ref(spec: dict, ref: str) -> dict:
    """Resolve a $ref pointer within the spec (e.g. '#/components/messages/UserCreated')."""
    if not ref.startswith("#/"):
        return {}
    parts = ref[2:].split("/")
    node = spec
    for part in parts:
        if isinstance(node, dict):
            node = node.get(part, {})
        else:
            return {}
    return node if isinstance(node, dict) else {}


def _resolve_if_ref(spec: dict, obj: dict | str) -> dict:
    """If obj is a $ref or contains $ref, resolve it."""
    if isinstance(obj, str):
        return {}
    if "$ref" in obj:
        return _resolve_ref(spec, obj["$ref"])
    return obj


def _extract_payload_schema(spec: dict, message: dict) -> dict | None:
    """Extract the payload JSON Schema from a message object."""
    message = _resolve_if_ref(spec, message)
    if not message:
        return None

    # oneOf messages — take first
    if "oneOf" in message:
        candidates = message["oneOf"]
        if candidates:
            message = _resolve_if_ref(spec, candidates[0])

    payload = message.get("payload")
    if payload:
        return _resolve_if_ref(spec, payload)

    return None


def _get_server_url(spec: dict) -> str:
    """Extract the first server URL from the spec."""
    servers = spec.get("servers", {})
    if isinstance(servers, dict):
        for server in servers.values():
            if isinstance(server, dict):
                url = server.get("url", "")
                protocol = server.get("protocol", "")
                if url:
                    if not url.startswith(("ws://", "wss://", "http://", "https://",
                                           "mqtt://", "amqp://", "kafka://")):
                        url = f"{protocol}://{url}" if protocol else url
                    return url
    return ""


def _parse_v2(spec: dict) -> list[Tool]:
    """Parse AsyncAPI 2.x spec."""
    tools: list[Tool] = []
    channels = spec.get("channels", {})
    server_url = _get_server_url(spec)

    for channel_name, channel_obj in channels.items():
        if not isinstance(channel_obj, dict):
            continue

        # Channel-level parameters (e.g. {userId} in path)
        channel_params: list[ToolParameter] = []
        for param_name, param_obj in (channel_obj.get("parameters", {}) or {}).items():
            param_obj = _resolve_if_ref(spec, param_obj)
            channel_params.append(ToolParameter(
                name=param_name,
                type=schema_type_str(param_obj.get("schema", {})) if isinstance(param_obj, dict) else "string",
                required=True,
                location="path",
                description=param_obj.get("description") if isinstance(param_obj, dict) else None,
            ))

        for op_type in ("publish", "subscribe"):
            operation = channel_obj.get(op_type)
            if not operation or not isinstance(operation, dict):
                continue

            op_id = operation.get("operationId", "")
            summary = operation.get("summary", "")
            description = operation.get("description", "")
            message = operation.get("message", {})
            tags = [t["name"] if isinstance(t, dict) else str(t) for t in operation.get("tags", [])]

            # Build tool name
            if op_id:
                name = sanitize_name(op_id)
            else:
                name = sanitize_name(f"{op_type}_{channel_name.replace('/', '_')}")

            # Extract payload parameters
            payload_schema = _extract_payload_schema(spec, message)
            params = list(channel_params)
            if payload_schema:
                params.extend(build_params_from_json_schema(payload_schema, location="body"))

            # Method: publish = send, subscribe = receive
            method = "PUBLISH" if op_type == "publish" else "SUBSCRIBE"

            ch = channel_name if channel_name.startswith("/") else f"/{channel_name}"
            endpoint = f"{server_url}{ch}" if server_url else channel_name

            desc = summary or description or f"{op_type} on {channel_name}"
            if len(desc) > 200:
                desc = desc[:200]

            metadata: dict = {"source": "asyncapi", "operation_type": op_type}
            if payload_schema:
                metadata["message_schema"] = payload_schema

            message_resolved = _resolve_if_ref(spec, message)
            if isinstance(message_resolved, dict) and message_resolved.get("name"):
                metadata["message_name"] = message_resolved["name"]

            if not tags:
                # Derive tag from channel name
                segments = [s for s in channel_name.split("/") if s and not s.startswith("{")]
                tags = [segments[0]] if segments else ["default"]

            tools.append(Tool(
                name=name,
                description=desc,
                parameters=params,
                endpoint=endpoint,
                method=method,
                protocol="async",
                response_format="json",
                tags=tags,
                metadata=metadata,
            ))

    return tools


def _parse_v3(spec: dict) -> list[Tool]:
    """Parse AsyncAPI 3.x spec."""
    tools: list[Tool] = []
    channels = spec.get("channels", {})
    operations = spec.get("operations", {})
    server_url = _get_server_url(spec)

    # Build channel lookup
    channel_map: dict[str, dict] = {}
    for ch_name, ch_obj in channels.items():
        if isinstance(ch_obj, dict):
            channel_map[ch_name] = ch_obj
            # Also map by $ref path
            channel_map[f"#/channels/{ch_name}"] = ch_obj

    for op_id, op_obj in operations.items():
        if not isinstance(op_obj, dict):
            continue

        action = op_obj.get("action", "send")  # "send" or "receive"
        summary = op_obj.get("summary", "")
        description = op_obj.get("description", "")
        tags = [t["name"] if isinstance(t, dict) else str(t) for t in op_obj.get("tags", [])]

        # Resolve channel
        channel_ref = op_obj.get("channel", {})
        if isinstance(channel_ref, dict) and "$ref" in channel_ref:
            ch_name = channel_ref["$ref"].split("/")[-1]
            channel_obj = _resolve_ref(spec, channel_ref["$ref"])
        elif isinstance(channel_ref, str):
            ch_name = channel_ref
            channel_obj = channel_map.get(channel_ref, {})
        else:
            ch_name = op_id
            channel_obj = channel_ref if isinstance(channel_ref, dict) else {}

        channel_address = channel_obj.get("address", ch_name) if isinstance(channel_obj, dict) else ch_name

        # Extract messages from operation
        messages = op_obj.get("messages", [])
        payload_schema = None
        if messages:
            first_msg = messages[0] if isinstance(messages, list) else next(iter(messages.values()), {})
            first_msg = _resolve_if_ref(spec, first_msg)
            payload_schema = _extract_payload_schema(spec, first_msg)

        # If no messages on operation, check channel messages
        if not payload_schema and isinstance(channel_obj, dict):
            ch_messages = channel_obj.get("messages", {})
            if ch_messages:
                first_ch_msg = next(iter(ch_messages.values()), {}) if isinstance(ch_messages, dict) else {}
                first_ch_msg = _resolve_if_ref(spec, first_ch_msg)
                payload_schema = _extract_payload_schema(spec, first_ch_msg)

        name = sanitize_name(op_id)
        params: list[ToolParameter] = []
        if payload_schema:
            params.extend(build_params_from_json_schema(payload_schema, location="body"))

        method = "PUBLISH" if action == "send" else "SUBSCRIBE"
        endpoint = f"{server_url}{channel_address}" if server_url else channel_address
        desc = summary or description or f"{action} on {channel_address}"
        if len(desc) > 200:
            desc = desc[:200]

        metadata: dict = {"source": "asyncapi", "operation_type": action}
        if payload_schema:
            metadata["message_schema"] = payload_schema

        if not tags:
            segments = [s for s in channel_address.split("/") if s and not s.startswith("{")]
            tags = [segments[0]] if segments else ["default"]

        tools.append(Tool(
            name=name,
            description=desc,
            parameters=params,
            endpoint=endpoint,
            method=method,
            protocol="async",
            response_format="json",
            tags=tags,
            metadata=metadata,
        ))

    return tools


def parse_asyncapi(input_data: str | dict, source_url: str | None = None) -> list[Tool]:
    """Parse an AsyncAPI spec into Tool definitions.

    Args:
        input_data: AsyncAPI spec as URL, JSON/YAML string, or parsed dict.
        source_url: Original URL context.

    Returns:
        list[Tool]: Tools derived from channels/operations.
    """
    if isinstance(input_data, str):
        if input_data.startswith("http://") or input_data.startswith("https://"):
            res = httpx.get(input_data, follow_redirects=True, timeout=DEFAULT_SPEC_FETCH_TIMEOUT)
            input_data = res.text
            source_url = source_url or str(res.url)

        try:
            spec = json.loads(input_data)
        except (json.JSONDecodeError, ValueError):
            spec = yaml.safe_load(input_data)
    elif isinstance(input_data, dict):
        spec = input_data
    else:
        raise ValueError(f"Unsupported input type: {type(input_data)}")

    if not isinstance(spec, dict):
        log.warning("AsyncAPI spec is not a valid object")
        return []

    version = str(spec.get("asyncapi", ""))
    log.info("Parsing AsyncAPI %s spec", version)

    if version.startswith("3"):
        tools = _parse_v3(spec)
    else:
        tools = _parse_v2(spec)

    log.info("AsyncAPI: generated %d tools", len(tools))
    return tools
