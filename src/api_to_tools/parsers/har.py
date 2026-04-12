"""HAR (HTTP Archive 1.2) parser.

Converts recorded browser traffic into LLM-callable Tool definitions.
Works with HAR files exported from Chrome DevTools, Firefox, Fiddler, mitmproxy, etc.

Strategy:
1. Parse HAR JSON and filter for API-like requests (skip static assets).
2. Normalize path parameters (numeric IDs, UUIDs, etc.) to placeholders.
3. Group entries by (method, normalized_path) to deduplicate repeated calls.
4. For each group, merge observed parameters and infer types from values.
5. Infer response schema from the most recent successful response body.
"""

from __future__ import annotations

import json
import re
from urllib.parse import parse_qs, urlparse

from api_to_tools._logging import get_logger
from api_to_tools.parsers._param_builder import (
    build_param_from_value,
    extract_tag_from_path,
    infer_json_type,
    normalize_path_params,
    sanitize_name,
    schema_from_value,
)
from api_to_tools.types import Tool, ToolParameter

log = get_logger("har")

# Content types that indicate API responses (not pages/assets)
_API_CONTENT_TYPES = ("application/json", "application/xml", "text/xml", "application/graphql")

# Extensions / patterns to skip
_SKIP_EXTENSIONS = frozenset({
    ".js", ".css", ".png", ".jpg", ".jpeg", ".gif", ".svg", ".ico",
    ".woff", ".woff2", ".ttf", ".eot", ".map", ".html", ".htm",
    ".mp4", ".webp", ".avif", ".pdf", ".zip", ".gz",
})

_SKIP_PATH_PATTERNS = (
    "/_next/", "/__nextjs", "/static/", "/assets/", "/favicon",
    "/sockjs-node", "/hot-update", "/_nuxt/", "/chunk-",
    "/analytics", "/gtag/", "/gtm", "/pixel",
)


def _is_api_entry(entry: dict) -> bool:
    """Determine if a HAR entry looks like an API call."""
    request = entry.get("request", {})
    url = request.get("url", "")
    method = request.get("method", "GET").upper()

    parsed = urlparse(url)
    path = parsed.path.lower()

    # Skip static assets
    if any(path.endswith(ext) for ext in _SKIP_EXTENSIONS):
        return False

    # Skip known non-API paths
    if any(pat in path for pat in _SKIP_PATH_PATTERNS):
        return False

    # Skip OPTIONS (CORS preflight)
    if method == "OPTIONS":
        return False

    response = entry.get("response", {})
    status = response.get("status", 0)

    # Skip redirects and non-content responses
    if status in (0, 204, 301, 302, 304):
        return False

    # Check response content type — strong signal for API
    resp_ct = response.get("content", {}).get("mimeType", "")
    if any(ct in resp_ct for ct in _API_CONTENT_TYPES):
        return True

    # Check request content type (POST with JSON body = likely API)
    req_headers = {h["name"].lower(): h["value"] for h in request.get("headers", [])}
    req_ct = req_headers.get("content-type", "")
    if "json" in req_ct or "xml" in req_ct:
        return True

    # Check for API path markers
    api_markers = ("/api/", "/v1/", "/v2/", "/v3/", "/rest/", "/graphql", "/rpc/")
    if any(marker in path for marker in api_markers):
        return True

    return False


def _extract_path_params(normalized: str) -> list[ToolParameter]:
    """Extract path parameters from a normalized path like /users/{id}/posts."""
    params = []
    for m in re.finditer(r"\{(\w+)\}", normalized):
        name = m.group(1)
        params.append(ToolParameter(
            name=name,
            type="string",
            required=True,
            location="path",
            description=f"Path parameter: {name}",
        ))
    return params


def _extract_query_params(entries: list[dict]) -> list[ToolParameter]:
    """Merge query parameters from multiple entries for the same endpoint."""
    param_values: dict[str, list] = {}
    for entry in entries:
        qs = entry.get("request", {}).get("queryString", [])
        for q in qs:
            name = q.get("name", "")
            value = q.get("value", "")
            if name:
                param_values.setdefault(name, []).append(value)

    params = []
    for name, values in param_values.items():
        # Infer type from the most common non-empty value
        sample = next((v for v in values if v), "")
        param_type = _infer_type_from_string(sample)
        appears_in_all = len(values) == len(entries)
        params.append(ToolParameter(
            name=name,
            type=param_type,
            required=appears_in_all,
            location="query",
            description=f"example: {sample}" if sample else None,
        ))
    return params


def _extract_body_params(entries: list[dict]) -> list[ToolParameter]:
    """Extract body parameters from POST/PUT/PATCH request bodies."""
    all_keys: dict[str, list] = {}
    entry_count = 0

    for entry in entries:
        post_data = entry.get("request", {}).get("postData", {})
        if not post_data:
            continue

        mime = post_data.get("mimeType", "")
        text = post_data.get("text", "")

        if "json" in mime and text:
            try:
                body = json.loads(text)
                if isinstance(body, dict):
                    entry_count += 1
                    for k, v in body.items():
                        all_keys.setdefault(k, []).append(v)
            except (json.JSONDecodeError, ValueError):
                pass
        elif "form" in mime:
            params_list = post_data.get("params", [])
            if params_list:
                entry_count += 1
                for p in params_list:
                    name = p.get("name", "")
                    value = p.get("value", "")
                    if name:
                        all_keys.setdefault(name, []).append(value)

    if not all_keys:
        return []

    params = []
    for name, values in all_keys.items():
        sample = next((v for v in values if v is not None), "")
        if isinstance(sample, (dict, list)):
            param_type = infer_json_type(sample)
        else:
            param_type = infer_json_type(sample) if not isinstance(sample, str) else _infer_type_from_string(str(sample))
        appears_in_all = len(values) >= entry_count if entry_count > 0 else False
        desc = None
        if sample not in (None, "", {}, []):
            desc = f"example: {json.dumps(sample, ensure_ascii=False)}" if isinstance(sample, (dict, list)) else f"example: {sample}"
        params.append(ToolParameter(
            name=name,
            type=param_type,
            required=appears_in_all,
            location="body",
            description=desc,
        ))
    return params


def _infer_type_from_string(value: str) -> str:
    """Infer JSON Schema type from a string value."""
    if not value:
        return "string"
    if value.lower() in ("true", "false"):
        return "boolean"
    try:
        int(value)
        return "integer"
    except ValueError:
        pass
    try:
        float(value)
        return "number"
    except ValueError:
        pass
    return "string"


def _infer_response_schema(entries: list[dict]) -> dict | None:
    """Infer a response schema from the most recent successful response."""
    for entry in reversed(entries):
        resp = entry.get("response", {})
        status = resp.get("status", 0)
        if status < 200 or status >= 300:
            continue

        content = resp.get("content", {})
        mime = content.get("mimeType", "")
        text = content.get("text", "")

        if "json" in mime and text:
            try:
                body = json.loads(text)
                return _schema_from_value(body)
            except (json.JSONDecodeError, ValueError):
                pass
    return None


_schema_from_value = schema_from_value


def _build_tool_name(method: str, path: str) -> str:
    """Generate a descriptive tool name from method + path."""
    segments = [s for s in path.split("/") if s and not s.startswith("{")]
    meaningful = [s for s in segments if s.lower() not in ("api", "v1", "v2", "v3", "rest")]
    name_parts = meaningful[-2:] if len(meaningful) > 2 else meaningful
    suffix = "_".join(name_parts) if name_parts else "root"
    raw = f"{method.lower()}_{suffix}"
    return sanitize_name(raw)


def parse_har(input_data: str | dict, source_url: str | None = None) -> list[Tool]:
    """Parse HAR (HTTP Archive) data into Tool definitions.

    Args:
        input_data: HAR file path, JSON string, or parsed dict.
        source_url: Original URL context (used for base_url fallback).

    Returns:
        list[Tool]: Discovered API tools with inferred parameters and response schemas.
    """
    # Load HAR data
    if isinstance(input_data, str):
        if input_data.endswith(".har") or input_data.endswith(".json"):
            with open(input_data) as f:
                har = json.load(f)
        else:
            har = json.loads(input_data)
    elif isinstance(input_data, dict):
        har = input_data
    else:
        raise ValueError(f"Unsupported input type: {type(input_data)}")

    log_data = har.get("log", {})
    entries = log_data.get("entries", [])

    if not entries:
        log.warning("HAR file contains no entries")
        return []

    # Filter to API-like entries
    api_entries = [e for e in entries if _is_api_entry(e)]
    log.info("HAR: %d total entries, %d API entries after filtering", len(entries), len(api_entries))

    if not api_entries:
        return []

    # Group by (method, normalized_path)
    groups: dict[tuple[str, str, str], list[dict]] = {}
    for entry in api_entries:
        request = entry["request"]
        method = request["method"].upper()
        url = request["url"]
        parsed = urlparse(url)
        origin = f"{parsed.scheme}://{parsed.netloc}"
        normalized = normalize_path_params(parsed.path.rstrip("/") or "/")

        key = (method, normalized, origin)
        groups.setdefault(key, []).append(entry)

    log.info("HAR: %d unique endpoints after grouping", len(groups))

    # Build tools
    tools: list[Tool] = []
    seen_names: set[str] = set()

    for (method, norm_path, origin), group_entries in groups.items():
        name = _build_tool_name(method, norm_path)

        # Deduplicate names
        if name in seen_names:
            counter = 2
            while f"{name}_{counter}" in seen_names:
                counter += 1
            name = f"{name}_{counter}"
        seen_names.add(name)

        # Build parameters
        params: list[ToolParameter] = []
        params.extend(_extract_path_params(norm_path))
        params.extend(_extract_query_params(group_entries))
        if method in ("POST", "PUT", "PATCH", "DELETE"):
            params.extend(_extract_body_params(group_entries))

        # Build endpoint URL
        endpoint = f"{origin}{norm_path}"

        # Infer response schema
        response_schema = _infer_response_schema(group_entries)

        # Description
        sample_count = len(group_entries)
        desc = f"{method} {norm_path}"
        if sample_count > 1:
            desc += f" ({sample_count} samples)"

        tag = extract_tag_from_path(norm_path)

        metadata: dict = {}
        if response_schema:
            metadata["response_schema"] = response_schema
        metadata["source"] = "har"
        metadata["sample_count"] = sample_count

        tools.append(Tool(
            name=name,
            description=desc,
            parameters=params,
            endpoint=endpoint,
            method=method,
            protocol="rest",
            response_format="json",
            tags=[tag],
            metadata=metadata,
        ))

    tools.sort(key=lambda t: (t.tags[0] if t.tags else "", t.method, t.name))
    log.info("HAR: generated %d tools", len(tools))
    return tools
