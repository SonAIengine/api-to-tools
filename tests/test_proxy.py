"""Tests for TrafficRecorder — no actual proxying, test internal helpers."""

from api_to_tools.proxy import TrafficRecorder, _ProxyHandler


def test_recorder_get_har_empty():
    recorder = TrafficRecorder(port=0)
    har = recorder.get_har()
    assert har["log"]["version"] == "1.2"
    assert har["log"]["entries"] == []


def test_recorder_to_tools_empty():
    recorder = TrafficRecorder(port=0)
    tools = recorder.to_tools()
    assert tools == []


def test_build_har_entry():
    handler = _ProxyHandler.__new__(_ProxyHandler)
    entry = handler._build_har_entry(
        method="GET",
        url="https://api.example.com/users?page=1",
        request_headers={"Accept": "application/json"},
        request_body=b"",
        request_content_type="",
        response_status=200,
        response_headers={"content-type": "application/json"},
        response_body='[{"id": 1}]',
        response_content_type="application/json",
        elapsed_ms=42.0,
    )
    assert entry["request"]["method"] == "GET"
    assert entry["request"]["url"] == "https://api.example.com/users?page=1"
    assert entry["response"]["status"] == 200
    assert entry["response"]["content"]["text"] == '[{"id": 1}]'
    assert len(entry["request"]["queryString"]) == 1
    assert entry["request"]["queryString"][0]["name"] == "page"


def test_build_har_entry_with_body():
    handler = _ProxyHandler.__new__(_ProxyHandler)
    entry = handler._build_har_entry(
        method="POST",
        url="https://api.example.com/users",
        request_headers={"Content-Type": "application/json"},
        request_body=b'{"name": "Alice"}',
        request_content_type="application/json",
        response_status=201,
        response_headers={},
        response_body='{"id": 1}',
        response_content_type="application/json",
        elapsed_ms=100.0,
    )
    assert entry["request"]["postData"]["text"] == '{"name": "Alice"}'
    assert entry["request"]["postData"]["mimeType"] == "application/json"


def test_recorder_har_roundtrip():
    """Manually add entries and verify to_tools works."""
    recorder = TrafficRecorder(port=0)
    recorder._entries.append({
        "request": {
            "method": "GET",
            "url": "https://api.example.com/api/v1/users",
            "headers": [],
            "queryString": [],
        },
        "response": {
            "status": 200,
            "content": {
                "mimeType": "application/json",
                "text": '[{"id": 1, "name": "Alice"}]',
            },
        },
    })
    tools = recorder.to_tools()
    assert len(tools) == 1
    assert tools[0].method == "GET"


def test_async_executor_registered():
    from api_to_tools.executors import EXECUTORS
    assert "async" in EXECUTORS
