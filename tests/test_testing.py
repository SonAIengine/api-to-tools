"""Tests for smoke test generation and execution (pure function tests)."""

from api_to_tools.testing import (
    _build_sample_args,
    generate_test_code,
    run_smoke_tests,
    SmokeTestReport,
)
from api_to_tools.types import Tool, ToolParameter


def _make_tool(name="getUsers", method="GET", endpoint="https://api.example.com/users",
               params=None, protocol="rest"):
    return Tool(
        name=name,
        description=f"Test: {name}",
        parameters=params or [],
        endpoint=endpoint,
        method=method,
        protocol=protocol,
    )


# ──────────────────────────────────────────────
# _build_sample_args
# ──────────────────────────────────────────────

def test_build_sample_args_defaults():
    params = [
        ToolParameter(name="page", type="integer", required=True),
        ToolParameter(name="q", type="string", required=True),
        ToolParameter(name="active", type="boolean", required=True),
    ]
    tool = _make_tool(params=params)
    args = _build_sample_args(tool)
    assert args == {"page": 1, "q": "test", "active": True}


def test_build_sample_args_with_default():
    params = [
        ToolParameter(name="size", type="integer", required=True, default=20),
    ]
    tool = _make_tool(params=params)
    args = _build_sample_args(tool)
    assert args["size"] == 20


def test_build_sample_args_with_enum():
    params = [
        ToolParameter(name="status", type="string", required=True, enum=["active", "inactive"]),
    ]
    tool = _make_tool(params=params)
    args = _build_sample_args(tool)
    assert args["status"] == "active"


def test_build_sample_args_with_example_in_description():
    params = [
        ToolParameter(name="country", type="string", required=True, description="example: KR"),
    ]
    tool = _make_tool(params=params)
    args = _build_sample_args(tool)
    assert args["country"] == "KR"


def test_build_sample_args_skips_optional():
    params = [
        ToolParameter(name="required_field", type="string", required=True),
        ToolParameter(name="optional_field", type="string", required=False),
    ]
    tool = _make_tool(params=params)
    args = _build_sample_args(tool)
    assert "required_field" in args
    assert "optional_field" not in args


def test_build_sample_args_array_type():
    params = [
        ToolParameter(name="ids", type="array[integer]", required=True),
    ]
    tool = _make_tool(params=params)
    args = _build_sample_args(tool)
    assert args["ids"] == []


# ──────────────────────────────────────────────
# run_smoke_tests — dry_run mode
# ──────────────────────────────────────────────

def test_dry_run_all_skipped():
    tools = [_make_tool(), _make_tool(name="createUser", method="POST")]
    report = run_smoke_tests(tools, dry_run=True, include_mutations=True)
    assert report.total == 2
    assert report.skipped == 2
    assert report.passed == 0
    assert all(r.skipped for r in report.results)


def test_mutations_skipped_by_default():
    tools = [
        _make_tool(method="GET"),
        _make_tool(name="createUser", method="POST"),
        _make_tool(name="deleteUser", method="DELETE"),
    ]
    report = run_smoke_tests(tools, dry_run=True)
    assert report.total == 3
    # GET is dry-run skipped, POST/DELETE are mutation-skipped
    get_result = next(r for r in report.results if r.method == "GET")
    assert "Dry run" in get_result.skip_reason

    post_result = next(r for r in report.results if r.method == "POST")
    assert "Mutation" in post_result.skip_reason


def test_report_summary():
    report = SmokeTestReport(total=10, passed=7, failed=2, skipped=1)
    assert "7 passed" in report.summary
    assert "2 failed" in report.summary
    assert "10 total" in report.summary


# ──────────────────────────────────────────────
# generate_test_code
# ──────────────────────────────────────────────

def test_generate_test_code_basic():
    params = [ToolParameter(name="id", type="integer", required=True)]
    tools = [_make_tool(params=params)]
    code = generate_test_code(tools)
    assert "def test_getUsers():" in code
    assert "execute(tool, args" in code
    assert '"id": 1' in code
    assert "assert 200" in code


def test_generate_test_code_mutation_comment():
    tools = [_make_tool(name="createUser", method="POST")]
    code = generate_test_code(tools)
    assert "skip" in code.lower() or "Mutation" in code


def test_generate_test_code_imports():
    code = generate_test_code([_make_tool()])
    assert "from api_to_tools import execute" in code
    assert "AuthConfig" in code


def test_generate_test_code_multiple_tools():
    tools = [_make_tool(name="a"), _make_tool(name="b")]
    code = generate_test_code(tools)
    assert "def test_a():" in code
    assert "def test_b():" in code


def test_generate_test_code_empty():
    code = generate_test_code([])
    assert "def test_" not in code
    assert "Auto-generated" in code
