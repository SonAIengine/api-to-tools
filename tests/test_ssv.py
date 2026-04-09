"""Tests for Nexacro SSV format parser."""

from api_to_tools.parsers.ssv import (
    build_request_ssv,
    extract_ssv_schema,
    is_ssv_content,
    parse_ssv,
)


SAMPLE_SSV = """SSV:UTF-8
ErrorCode:int=0
ErrorMsg:string=SUCCESS
ErrorType:string=NoException
ErrorKey:string=
Dataset:ds_out
_RowType_:string(8),GRP_CD:string(20),GRP_CD_NM:string(100),CD:string(20),CD_NM:string(100),SORT_RNK:int
N,GRP01,상품구분,01,일반,1
N,GRP01,상품구분,02,옵션,2
"""


def test_is_ssv_content_detects_header():
    assert is_ssv_content("SSV:UTF-8\nfoo:int=1")


def test_is_ssv_content_detects_structure():
    assert is_ssv_content("foo:int=1\nDataset:ds_x")


def test_is_ssv_content_rejects_json():
    assert not is_ssv_content('{"foo": 1}')


def test_is_ssv_content_rejects_empty():
    assert not is_ssv_content("")


def test_parse_ssv_scalars():
    result = parse_ssv("SSV:UTF-8\nErrorCode:int=0\nErrorMsg:string=OK")
    assert result["ErrorCode"] == 0
    assert result["ErrorMsg"] == "OK"


def test_parse_ssv_type_coercion():
    result = parse_ssv("SSV:UTF-8\nFlag:boolean=true\nPrice:double=19.99\nCount:int=42")
    assert result["Flag"] is True
    assert result["Price"] == 19.99
    assert result["Count"] == 42


def test_parse_ssv_dataset():
    result = parse_ssv(SAMPLE_SSV)
    assert result["ErrorCode"] == 0
    assert result["ErrorMsg"] == "SUCCESS"
    assert len(result["ds_out"]) == 2
    assert result["ds_out"][0]["GRP_CD"] == "GRP01"
    assert result["ds_out"][0]["CD_NM"] == "일반"
    assert result["ds_out"][0]["SORT_RNK"] == 1


def test_parse_ssv_skips_non_data_rows():
    # Row without N/I/U/D prefix should be skipped
    result = parse_ssv(
        "SSV:UTF-8\nDataset:ds\n_RowType_:string,A:string\nN,hello\nnonsense,world"
    )
    assert len(result["ds"]) == 1


def test_extract_ssv_schema():
    schema = extract_ssv_schema(SAMPLE_SSV)
    assert schema["scalars"]["ErrorCode"] == "int"
    assert schema["scalars"]["ErrorMsg"] == "string"
    assert "ds_out" in schema["datasets"]
    assert schema["datasets"]["ds_out"]["GRP_CD"] == "string"
    assert schema["datasets"]["ds_out"]["SORT_RNK"] == "int"


def test_build_request_ssv():
    body = build_request_ssv({"name": "Alice", "age": 30, "active": True})
    assert body.startswith("SSV:UTF-8")
    assert "name:string" in body
    assert "=Alice" in body
    assert "age:int=30" in body
    assert "active:boolean=true" in body


def test_build_request_ssv_skips_none():
    body = build_request_ssv({"a": "value", "b": None})
    assert "a:string" in body
    assert "b:" not in body


def test_parse_ssv_empty_returns_empty():
    assert parse_ssv("") == {}
    assert parse_ssv("SSV:UTF-8") == {}


def test_parse_ssv_handles_record_separator():
    """Nexacro may use \\x1e as record separator."""
    content = "SSV:UTF-8\x1eFoo:int=7\x1e"
    result = parse_ssv(content)
    assert result["Foo"] == 7
