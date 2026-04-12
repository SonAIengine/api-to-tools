# Smoke Testing

Automatically test discovered API endpoints.

## Run Smoke Tests

```python
from api_to_tools import discover, run_smoke_tests

tools = discover("https://api.example.com/docs")
report = run_smoke_tests(tools)
print(report.summary)  # "15 passed, 2 failed, 8 skipped / 25 total"
```

### Options

```python
# Include mutations (POST/PUT/DELETE) — skipped by default
report = run_smoke_tests(tools, include_mutations=True)

# Dry run — validate without network calls
report = run_smoke_tests(tools, dry_run=True)

# With authentication
report = run_smoke_tests(tools, auth=auth)
```

### Report Details

```python
for result in report.results:
    print(f"{result.method} {result.tool_name}: "
          f"{'PASS' if result.success else 'FAIL' if not result.skipped else 'SKIP'}")
    if result.error:
        print(f"  Error: {result.error}")
```

## Generate Test File

Generate a pytest-compatible test file:

```python
from api_to_tools import generate_test_code

code = generate_test_code(tools)
with open("test_api_smoke.py", "w") as f:
    f.write(code)
```

Then run: `pytest test_api_smoke.py`

### Smart Argument Generation

Sample arguments are automatically built from:

1. Parameter `default` values
2. First `enum` value
3. `example:` in description
4. Type-based fallback (`string` → `"test"`, `integer` → `1`)
