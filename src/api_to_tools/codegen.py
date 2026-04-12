"""SDK code generation from Tool definitions.

Generates typed Python client code from discovered Tools.
Each Tool becomes a method on a generated client class with
type-hinted parameters and docstrings.
"""

from __future__ import annotations

import re

from api_to_tools.types import Tool, ToolParameter

# Python type mapping from JSON Schema types
_TYPE_MAP = {
    "string": "str",
    "integer": "int",
    "number": "float",
    "boolean": "bool",
    "array": "list",
    "object": "dict",
    "null": "None",
}


def _py_type(param: ToolParameter) -> str:
    """Convert a ToolParameter type to a Python type annotation."""
    t = param.type
    if t.startswith("array["):
        inner = t[6:-1] if t.endswith("]") else "Any"
        inner_py = _TYPE_MAP.get(inner, "Any")
        return f"list[{inner_py}]"
    return _TYPE_MAP.get(t, "Any")


def _safe_method_name(name: str) -> str:
    """Convert a tool name to a valid Python method name."""
    name = re.sub(r"[^a-zA-Z0-9_]", "_", name)
    name = re.sub(r"_+", "_", name).strip("_").lower()
    if name and name[0].isdigit():
        name = f"call_{name}"
    return name or "unknown"


def _indent(text: str, level: int = 1) -> str:
    prefix = "    " * level
    return "\n".join(f"{prefix}{line}" if line else "" for line in text.split("\n"))


def generate_python_sdk(
    tools: list[Tool],
    *,
    class_name: str = "APIClient",
    module_doc: str | None = None,
) -> str:
    """Generate a typed Python SDK client from Tool definitions.

    Args:
        tools: Tools to generate methods for.
        class_name: Name of the generated client class.
        module_doc: Optional module-level docstring.

    Returns:
        Python source code string.

    Example:
        tools = discover("https://api.example.com/docs")
        code = generate_python_sdk(tools, class_name="PetStoreClient")
        with open("petstore_client.py", "w") as f:
            f.write(code)
    """
    lines: list[str] = []

    # Module docstring
    if module_doc:
        lines.append(f'"""{module_doc}"""')
    else:
        lines.append('"""Auto-generated API client."""')
    lines.append("")

    # Imports
    lines.append("from __future__ import annotations")
    lines.append("")
    lines.append("from typing import Any")
    lines.append("")
    lines.append("import httpx")
    lines.append("")
    lines.append("")

    # Client class
    lines.append(f"class {class_name}:")
    lines.append(f'    """Typed API client with {len(tools)} endpoints."""')
    lines.append("")

    # __init__
    lines.append("    def __init__(")
    lines.append("        self,")
    lines.append("        base_url: str = \"\",")
    lines.append("        *,")
    lines.append("        headers: dict[str, str] | None = None,")
    lines.append("        timeout: float = 30.0,")
    lines.append("        verify_ssl: bool = True,")
    lines.append("    ):")
    lines.append('        """Initialize the API client.')
    lines.append("")
    lines.append("        Args:")
    lines.append("            base_url: Override base URL for all requests.")
    lines.append("            headers: Default headers (e.g. Authorization).")
    lines.append("            timeout: Request timeout in seconds.")
    lines.append("            verify_ssl: Verify TLS certificates.")
    lines.append('        """')
    lines.append("        self._base_url = base_url.rstrip(\"/\")")
    lines.append("        self._client = httpx.Client(")
    lines.append("            headers=headers or {},")
    lines.append("            timeout=timeout,")
    lines.append("            verify=verify_ssl,")
    lines.append("            follow_redirects=True,")
    lines.append("        )")
    lines.append("")

    # close
    lines.append("    def close(self):")
    lines.append('        """Close the HTTP client."""')
    lines.append("        self._client.close()")
    lines.append("")

    # Context manager
    lines.append("    def __enter__(self):")
    lines.append("        return self")
    lines.append("")
    lines.append("    def __exit__(self, *exc):")
    lines.append("        self.close()")
    lines.append("")

    # Group by tag for organization
    seen_methods: set[str] = set()

    for tool in tools:
        method_name = _safe_method_name(tool.name)
        if method_name in seen_methods:
            counter = 2
            while f"{method_name}_{counter}" in seen_methods:
                counter += 1
            method_name = f"{method_name}_{counter}"
        seen_methods.add(method_name)

        # Build method signature
        required_params = [p for p in tool.parameters if p.required]
        optional_params = [p for p in tool.parameters if not p.required]

        sig_parts = ["self"]
        for p in required_params:
            sig_parts.append(f"{p.name}: {_py_type(p)}")
        for p in optional_params:
            default = repr(p.default) if p.default is not None else "None"
            sig_parts.append(f"{p.name}: {_py_type(p)} | None = {default}")

        sig = ", ".join(sig_parts)

        # Method
        lines.append(f"    def {method_name}({sig}) -> Any:")
        # Docstring
        desc = tool.description.replace('"""', "'''")
        lines.append(f'        """{desc}')
        if tool.parameters:
            lines.append("")
            lines.append("        Args:")
            for p in tool.parameters:
                p_desc = p.description or p.type
                lines.append(f"            {p.name}: {p_desc}")
        lines.append('        """')

        # Build URL
        path_params = [p for p in tool.parameters if p.location == "path"]
        query_params = [p for p in tool.parameters if p.location == "query"]
        header_params = [p for p in tool.parameters if p.location == "header"]
        body_params = [p for p in tool.parameters if p.location in ("body", None)]

        # URL with path parameter substitution
        endpoint = tool.endpoint
        if path_params:
            lines.append(f'        url = f"{{self._base_url}}{_extract_path(endpoint)}"')
        else:
            lines.append(f'        url = self._base_url + "{_extract_path(endpoint)}"')

        # Query params
        if query_params:
            lines.append("        params = {}")
            for p in query_params:
                lines.append(f"        if {p.name} is not None:")
                lines.append(f'            params["{p.name}"] = {p.name}')
        else:
            lines.append("        params = None")

        # Headers
        if header_params:
            lines.append("        headers = {}")
            for p in header_params:
                lines.append(f"        if {p.name} is not None:")
                lines.append(f'            headers["{p.name}"] = str({p.name})')
        else:
            lines.append("        headers = None")

        # Body
        if body_params and tool.method in ("POST", "PUT", "PATCH"):
            lines.append("        body = {}")
            for p in body_params:
                lines.append(f"        if {p.name} is not None:")
                lines.append(f'            body["{p.name}"] = {p.name}')
        else:
            lines.append("        body = None")

        # Request
        lines.append(f'        response = self._client.request("{tool.method}", url, params=params, headers=headers, json=body)')
        lines.append("        response.raise_for_status()")

        # Parse response
        lines.append("        try:")
        lines.append("            return response.json()")
        lines.append("        except Exception:")
        lines.append("            return response.text")
        lines.append("")

    return "\n".join(lines)


def _extract_path(endpoint: str) -> str:
    """Extract path portion from a full endpoint URL."""
    from urllib.parse import urlparse
    parsed = urlparse(endpoint)
    return parsed.path or "/"


def generate_typescript_sdk(
    tools: list[Tool],
    *,
    class_name: str = "APIClient",
) -> str:
    """Generate a TypeScript SDK client from Tool definitions.

    Args:
        tools: Tools to generate methods for.
        class_name: Name of the generated client class.

    Returns:
        TypeScript source code string.
    """
    ts_type_map = {
        "string": "string",
        "integer": "number",
        "number": "number",
        "boolean": "boolean",
        "array": "any[]",
        "object": "Record<string, any>",
    }

    def ts_type(p: ToolParameter) -> str:
        t = p.type
        if t.startswith("array["):
            inner = t[6:-1] if t.endswith("]") else "any"
            return f"{ts_type_map.get(inner, 'any')}[]"
        return ts_type_map.get(t, "any")

    lines: list[str] = []
    lines.append("// Auto-generated API client")
    lines.append("")
    lines.append(f"export class {class_name} {{")
    lines.append("  private baseUrl: string;")
    lines.append("  private headers: Record<string, string>;")
    lines.append("")
    lines.append("  constructor(baseUrl: string = '', headers: Record<string, string> = {}) {")
    lines.append("    this.baseUrl = baseUrl.replace(/\\/$/, '');")
    lines.append("    this.headers = headers;")
    lines.append("  }")
    lines.append("")

    # Helper
    lines.append("  private async request(method: string, path: string, options: {")
    lines.append("    params?: Record<string, any>;")
    lines.append("    body?: any;")
    lines.append("    headers?: Record<string, string>;")
    lines.append("  } = {}): Promise<any> {")
    lines.append("    const url = new URL(path, this.baseUrl);")
    lines.append("    if (options.params) {")
    lines.append("      Object.entries(options.params).forEach(([k, v]) => {")
    lines.append("        if (v !== undefined && v !== null) url.searchParams.set(k, String(v));")
    lines.append("      });")
    lines.append("    }")
    lines.append("    const response = await fetch(url.toString(), {")
    lines.append("      method,")
    lines.append("      headers: { 'Content-Type': 'application/json', ...this.headers, ...options.headers },")
    lines.append("      body: options.body ? JSON.stringify(options.body) : undefined,")
    lines.append("    });")
    lines.append("    if (!response.ok) throw new Error(`${response.status}: ${await response.text()}`);")
    lines.append("    return response.json();")
    lines.append("  }")
    lines.append("")

    seen: set[str] = set()
    for tool in tools:
        method_name = _safe_method_name(tool.name)
        if method_name in seen:
            counter = 2
            while f"{method_name}{counter}" in seen:
                counter += 1
            method_name = f"{method_name}{counter}"
        seen.add(method_name)

        # Build params
        required = [p for p in tool.parameters if p.required]
        optional = [p for p in tool.parameters if not p.required]

        params_parts = []
        for p in required:
            params_parts.append(f"{p.name}: {ts_type(p)}")
        for p in optional:
            params_parts.append(f"{p.name}?: {ts_type(p)}")

        params_str = ", ".join(params_parts)
        desc = tool.description.replace("*/", "* /")

        lines.append(f"  /** {desc} */")
        lines.append(f"  async {method_name}({params_str}): Promise<any> {{")

        path = _extract_path(tool.endpoint)
        # Path param substitution
        path_ts = re.sub(r"\{(\w+)\}", r"${\\1}", path)
        if "{" in tool.endpoint:
            lines.append(f"    const path = `{path_ts}`;")
        else:
            lines.append(f"    const path = '{path}';")

        query_params = [p for p in tool.parameters if p.location == "query"]
        body_params = [p for p in tool.parameters if p.location in ("body", None)]

        q_obj = ""
        if query_params:
            q_parts = ", ".join(p.name for p in query_params)
            q_obj = f"{{ {q_parts} }}"

        b_obj = ""
        if body_params and tool.method in ("POST", "PUT", "PATCH"):
            b_parts = ", ".join(p.name for p in body_params)
            b_obj = f"{{ {b_parts} }}"

        opts = []
        if q_obj:
            opts.append(f"params: {q_obj}")
        if b_obj:
            opts.append(f"body: {b_obj}")

        opts_str = f"{{ {', '.join(opts)} }}" if opts else "{}"
        lines.append(f"    return this.request('{tool.method}', path, {opts_str});")
        lines.append("  }")
        lines.append("")

    lines.append("}")
    lines.append("")

    return "\n".join(lines)
