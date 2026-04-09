"""Nexacro SSV (Semi-colon Separated Values) format parser.

SSV is Nexacro's proprietary serialization format used by Korean legacy
enterprise systems (롯데이몰, 대형 유통/금융 시스템 등).

Format overview:
    SSV:UTF-8                       # header
    ErrorCode:int=0                 # scalar variable
    ErrorMsg:string=SUCCESS         # scalar variable
    ErrorType:string=NoException
    Dataset:ds_out                  # dataset begins
    _RowType_:string(8),COL1:string(50),COL2:int,COL3:string(100)
    N,value1,123,some text          # rows (N=normal, I=insert, U=update, D=delete)
    N,value2,456,another
    Dataset:ds_another              # another dataset
    ...

The format uses comma (,) as field separator, but values with commas
are escaped. Line endings use \\x1e (record separator) in older versions.
"""

from __future__ import annotations

import re
from typing import Any


# Row types in Nexacro datasets
ROW_TYPES = {"N", "I", "U", "D", "n", "i", "u", "d"}


def _parse_scalar_value(type_str: str, value: str) -> Any:
    """Convert a string value to Python type based on Nexacro type hint."""
    if value in (None, ""):
        return None
    t = type_str.lower().split("(")[0]  # strip size: "string(50)" → "string"
    try:
        if t in ("int", "integer", "long", "short"):
            return int(value)
        if t in ("float", "double", "decimal", "number"):
            return float(value)
        if t in ("bool", "boolean"):
            return value.lower() in ("true", "1", "y", "yes")
        return value
    except (ValueError, TypeError):
        return value


def _parse_column_def(col_def: str) -> tuple[str, str]:
    """Parse a single column definition like 'COL1:string(50)' or 'COL2:int'."""
    if ":" in col_def:
        name, type_str = col_def.split(":", 1)
        return name.strip(), type_str.strip()
    return col_def.strip(), "string"


def _parse_columns(header_line: str) -> list[tuple[str, str]]:
    """Parse a dataset column header line."""
    return [_parse_column_def(col) for col in header_line.split(",")]


def _parse_row(row_line: str, columns: list[tuple[str, str]]) -> dict | None:
    """Parse a single data row into a dict."""
    values = row_line.split(",")
    if not values:
        return None

    # First value is row type (N/I/U/D)
    row_type = values[0].strip()
    if row_type not in ROW_TYPES:
        return None

    # Remaining values map to columns (skipping _RowType_)
    data_cols = [c for c in columns if c[0] != "_RowType_"]
    result = {}
    for i, (col_name, col_type) in enumerate(data_cols):
        if i + 1 < len(values):
            result[col_name] = _parse_scalar_value(col_type, values[i + 1])
        else:
            result[col_name] = None

    return result


def parse_ssv(content: str) -> dict[str, Any]:
    """Parse SSV-formatted content into a Python dict.

    Returns a dict with:
        - Scalar variables as top-level keys
        - Datasets as lists of row dicts

    Example:
        >>> parse_ssv("SSV:UTF-8\\nErrorCode:int=0\\nErrorMsg:string=SUCCESS")
        {"ErrorCode": 0, "ErrorMsg": "SUCCESS"}
    """
    if not content:
        return {}

    # Normalize line endings: Nexacro may use \x1e (record separator) or \n
    content = content.replace("\x1e", "\n").replace("\r\n", "\n").replace("\r", "\n")
    lines = content.split("\n")

    result: dict[str, Any] = {}
    current_dataset: str | None = None
    current_columns: list[tuple[str, str]] = []
    current_rows: list[dict] = []
    expecting_columns = False

    for raw_line in lines:
        line = raw_line.strip()
        if not line:
            continue

        # Header
        if line.startswith("SSV:"):
            continue

        # Dataset marker
        if line.startswith("Dataset:"):
            # Save previous dataset
            if current_dataset:
                result[current_dataset] = current_rows
            current_dataset = line.split(":", 1)[1].strip()
            current_columns = []
            current_rows = []
            expecting_columns = True
            continue

        # Inside a dataset
        if current_dataset:
            if expecting_columns:
                current_columns = _parse_columns(line)
                expecting_columns = False
                continue
            # Data row
            row = _parse_row(line, current_columns)
            if row is not None:
                current_rows.append(row)
            continue

        # Scalar variable: NAME:TYPE=VALUE
        m = re.match(r'^([^:]+):([^=]+)=(.*)$', line)
        if m:
            name = m.group(1).strip()
            type_str = m.group(2).strip()
            value = m.group(3)
            result[name] = _parse_scalar_value(type_str, value)

    # Flush last dataset
    if current_dataset:
        result[current_dataset] = current_rows

    return result


def extract_ssv_schema(content: str) -> dict[str, Any]:
    """Extract the schema structure from an SSV response.

    Returns a dict describing the shape:
        {
          "scalars": {"ErrorCode": "int", "ErrorMsg": "string"},
          "datasets": {
            "ds_out": {"GRP_CD": "string", "CD": "string", ...}
          }
        }
    """
    if not content:
        return {}

    content = content.replace("\x1e", "\n").replace("\r\n", "\n").replace("\r", "\n")
    lines = content.split("\n")

    schema = {"scalars": {}, "datasets": {}}
    current_dataset: str | None = None
    expecting_columns = False

    for raw_line in lines:
        line = raw_line.strip()
        if not line or line.startswith("SSV:"):
            continue

        if line.startswith("Dataset:"):
            current_dataset = line.split(":", 1)[1].strip()
            schema["datasets"][current_dataset] = {}
            expecting_columns = True
            continue

        if current_dataset and expecting_columns:
            for col_def in line.split(","):
                name, type_str = _parse_column_def(col_def)
                if name != "_RowType_":
                    schema["datasets"][current_dataset][name] = type_str.split("(")[0]
            expecting_columns = False
            continue

        # Scalar
        m = re.match(r'^([^:]+):([^=]+)=', line)
        if m and not current_dataset:
            name = m.group(1).strip()
            type_str = m.group(2).strip().split("(")[0]
            schema["scalars"][name] = type_str

    return schema


def is_ssv_content(content: str) -> bool:
    """Detect if content is SSV format."""
    if not content:
        return False
    # Must start with SSV: marker or have scalar/dataset structure
    stripped = content.strip()
    if stripped.startswith("SSV:"):
        return True
    # Secondary heuristic: presence of both NAME:type=value and Dataset: patterns
    if "Dataset:" in content and re.search(r'^\w+:\w+=', content, re.MULTILINE):
        return True
    return False


def build_request_ssv(params: dict[str, Any]) -> str:
    """Build an SSV-formatted request body from a dict of parameters.

    For scalar values only. For datasets, caller must build the dataset
    section manually since schema definition is required.
    """
    lines = ["SSV:UTF-8"]
    for name, value in params.items():
        if value is None:
            continue
        if isinstance(value, bool):
            t, v = "boolean", "true" if value else "false"
        elif isinstance(value, int):
            t, v = "int", str(value)
        elif isinstance(value, float):
            t, v = "float", str(value)
        else:
            t, v = f"string({len(str(value))})", str(value)
        lines.append(f"{name}:{t}={v}")
    return "\n".join(lines)
