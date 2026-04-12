"""Automatic smoke test generation and execution for discovered Tools.

Generate test code or run live smoke tests against discovered API endpoints.
GET endpoints are called with sample/default parameters.
Mutation endpoints (POST/PUT/PATCH/DELETE) are dry-run by default.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any

from api_to_tools._logging import get_logger
from api_to_tools.types import AuthConfig, ExecutionResult, Tool

log = get_logger("testing")

# Methods considered safe to call in smoke tests
_SAFE_METHODS = frozenset({"GET", "HEAD", "OPTIONS"})


@dataclass
class SmokeTestResult:
    """Result of a single smoke test."""
    tool_name: str
    method: str
    endpoint: str
    status: int | None = None
    success: bool = False
    skipped: bool = False
    skip_reason: str | None = None
    error: str | None = None
    response_preview: str | None = None


@dataclass
class SmokeTestReport:
    """Aggregated smoke test report."""
    total: int = 0
    passed: int = 0
    failed: int = 0
    skipped: int = 0
    results: list[SmokeTestResult] = field(default_factory=list)

    @property
    def summary(self) -> str:
        return f"{self.passed} passed, {self.failed} failed, {self.skipped} skipped / {self.total} total"


def _build_sample_args(tool: Tool) -> dict[str, Any]:
    """Build sample arguments from parameter defaults and type hints."""
    args: dict[str, Any] = {}
    for p in tool.parameters:
        if not p.required:
            continue

        # Use default if available
        if p.default is not None:
            args[p.name] = p.default
            continue

        # Use first enum value
        if p.enum:
            args[p.name] = p.enum[0]
            continue

        # Extract example from description
        if p.description and "example:" in p.description:
            example_str = p.description.split("example:", 1)[1].strip()
            args[p.name] = example_str
            continue

        # Type-based fallback
        type_defaults = {
            "string": "test",
            "integer": 1,
            "number": 1.0,
            "boolean": True,
            "array": [],
            "object": {},
        }
        base_type = p.type.split("[")[0] if "[" in p.type else p.type
        args[p.name] = type_defaults.get(base_type, "test")

    return args


def run_smoke_tests(
    tools: list[Tool],
    *,
    auth: AuthConfig | None = None,
    include_mutations: bool = False,
    dry_run: bool = False,
) -> SmokeTestReport:
    """Run smoke tests against discovered tools.

    Args:
        tools: Tools to test.
        auth: Auth config for protected APIs.
        include_mutations: If True, also execute POST/PUT/PATCH/DELETE.
            Default False (mutations are skipped).
        dry_run: If True, don't execute any requests, just build args
            and report what would be tested.

    Returns:
        SmokeTestReport with per-tool results.
    """
    from api_to_tools.core import execute

    report = SmokeTestReport(total=len(tools))

    for tool in tools:
        is_safe = tool.method.upper() in _SAFE_METHODS

        # Skip mutations unless explicitly included
        if not is_safe and not include_mutations:
            result = SmokeTestResult(
                tool_name=tool.name,
                method=tool.method,
                endpoint=tool.endpoint,
                skipped=True,
                skip_reason=f"Mutation ({tool.method}) skipped — use include_mutations=True",
            )
            report.skipped += 1
            report.results.append(result)
            continue

        args = _build_sample_args(tool)

        if dry_run:
            result = SmokeTestResult(
                tool_name=tool.name,
                method=tool.method,
                endpoint=tool.endpoint,
                skipped=True,
                skip_reason=f"Dry run — would call with args: {json.dumps(args, default=str)}",
            )
            report.skipped += 1
            report.results.append(result)
            continue

        # Execute
        try:
            exec_result: ExecutionResult = execute(tool, args, auth=auth)
            is_success = 200 <= exec_result.status < 400

            preview = None
            if exec_result.raw:
                preview = exec_result.raw[:200]

            result = SmokeTestResult(
                tool_name=tool.name,
                method=tool.method,
                endpoint=tool.endpoint,
                status=exec_result.status,
                success=is_success,
                response_preview=preview,
                error=str(exec_result.data) if not is_success else None,
            )

            if is_success:
                report.passed += 1
                log.info("PASS %s %s → %d", tool.method, tool.name, exec_result.status)
            else:
                report.failed += 1
                log.warning("FAIL %s %s → %d", tool.method, tool.name, exec_result.status)

        except Exception as e:
            result = SmokeTestResult(
                tool_name=tool.name,
                method=tool.method,
                endpoint=tool.endpoint,
                success=False,
                error=str(e),
            )
            report.failed += 1
            log.error("ERROR %s %s: %s", tool.method, tool.name, e)

        report.results.append(result)

    return report


def generate_test_code(
    tools: list[Tool],
    *,
    auth_var: str = "auth",
    framework: str = "pytest",
) -> str:
    """Generate Python test code for the given tools.

    Args:
        tools: Tools to generate tests for.
        auth_var: Variable name for AuthConfig in generated code.
        framework: Test framework ('pytest' or 'unittest').

    Returns:
        Python source code string.
    """
    lines = [
        '"""Auto-generated smoke tests for discovered API tools."""',
        "",
        "from api_to_tools import execute, AuthConfig",
        "",
        f"# Configure auth (fill in your credentials)",
        f"{auth_var} = None  # e.g. AuthConfig(type='bearer', token='...')",
        "",
    ]

    for tool in tools:
        is_safe = tool.method.upper() in _SAFE_METHODS
        args = _build_sample_args(tool)
        args_str = json.dumps(args, indent=4, default=str, ensure_ascii=False)

        func_name = f"test_{tool.name}"
        # Ensure valid Python function name
        func_name = "".join(c if c.isalnum() or c == "_" else "_" for c in func_name)

        lines.append("")
        if not is_safe:
            lines.append(f"# @pytest.mark.skip(reason='Mutation: {tool.method}')")

        lines.append(f"def {func_name}():")
        lines.append(f'    """{tool.method} {tool.endpoint}"""')

        # Build tool reference
        lines.append(f"    from api_to_tools.types import Tool, ToolParameter")
        lines.append(f"    tool = Tool(")
        lines.append(f'        name="{tool.name}",')
        lines.append(f'        description="""{tool.description}""",')
        lines.append(f"        parameters=[],  # simplified")
        lines.append(f'        endpoint="{tool.endpoint}",')
        lines.append(f'        method="{tool.method}",')
        lines.append(f'        protocol="{tool.protocol}",')
        lines.append(f"    )")

        lines.append(f"    args = {args_str}")
        lines.append(f"    result = execute(tool, args, auth={auth_var})")

        if is_safe:
            lines.append(f"    assert 200 <= result.status < 400, f'{{result.status}}: {{result.data}}'")
        else:
            lines.append(f"    # Mutation — verify status but be cautious")
            lines.append(f"    assert result.status < 500, f'Server error: {{result.status}}: {{result.data}}'")

        lines.append("")

    return "\n".join(lines)
