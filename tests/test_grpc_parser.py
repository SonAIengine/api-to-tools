"""Tests for gRPC parser — _parse_proto_regex (pure function, no protoc needed)."""

from api_to_tools.parsers.grpc import _parse_proto_regex


SAMPLE_PROTO = """
syntax = "proto3";

package example.greeter;

message HelloRequest {
    string name = 1;
    int32 age = 2;
}

message HelloReply {
    string message = 1;
    bool success = 2;
}

service Greeter {
    rpc SayHello (HelloRequest) returns (HelloReply);
    rpc SayHelloStream (HelloRequest) returns (stream HelloReply);
}
"""


def test_parse_proto_finds_service():
    tools = _parse_proto_regex(SAMPLE_PROTO)
    assert len(tools) == 2
    names = {t.name for t in tools}
    assert "Greeter_SayHello" in names
    assert "Greeter_SayHelloStream" in names


def test_parse_proto_extracts_params():
    tools = _parse_proto_regex(SAMPLE_PROTO)
    hello = next(t for t in tools if t.name == "Greeter_SayHello")
    param_names = {p.name for p in hello.parameters}
    assert param_names == {"name", "age"}
    name_param = next(p for p in hello.parameters if p.name == "name")
    assert name_param.type == "string"
    age_param = next(p for p in hello.parameters if p.name == "age")
    assert age_param.type == "integer"


def test_parse_proto_metadata():
    tools = _parse_proto_regex(SAMPLE_PROTO)
    hello = next(t for t in tools if t.name == "Greeter_SayHello")
    assert hello.metadata["service"] == "Greeter"
    assert hello.metadata["request_type"] == "HelloRequest"
    assert hello.metadata["response_type"] == "HelloReply"
    assert hello.metadata["client_streaming"] is False
    assert hello.metadata["server_streaming"] is False


def test_parse_proto_streaming():
    tools = _parse_proto_regex(SAMPLE_PROTO)
    stream = next(t for t in tools if t.name == "Greeter_SayHelloStream")
    assert stream.metadata["server_streaming"] is True
    assert stream.metadata["client_streaming"] is False


def test_parse_proto_protocol():
    tools = _parse_proto_regex(SAMPLE_PROTO)
    for t in tools:
        assert t.protocol == "grpc"
        assert t.response_format == "protobuf"


def test_parse_proto_package():
    tools = _parse_proto_regex(SAMPLE_PROTO)
    hello = next(t for t in tools if t.name == "Greeter_SayHello")
    assert hello.endpoint == "example.greeter.Greeter.SayHello"


def test_parse_proto_tags():
    tools = _parse_proto_regex(SAMPLE_PROTO)
    for t in tools:
        assert t.tags == ["Greeter"]


def test_parse_proto_no_package():
    proto = """
    message Req { string id = 1; }
    message Resp { string data = 1; }
    service MyService {
        rpc GetData (Req) returns (Resp);
    }
    """
    tools = _parse_proto_regex(proto)
    assert len(tools) == 1
    assert tools[0].endpoint == "MyService.GetData"


def test_parse_proto_empty():
    tools = _parse_proto_regex("")
    assert tools == []


def test_parse_proto_multiple_services():
    proto = """
    package test;
    message Empty {}
    message Data { string value = 1; }
    service ServiceA {
        rpc MethodA (Empty) returns (Data);
    }
    service ServiceB {
        rpc MethodB (Data) returns (Empty);
    }
    """
    tools = _parse_proto_regex(proto)
    assert len(tools) == 2
    names = {t.name for t in tools}
    assert names == {"ServiceA_MethodA", "ServiceB_MethodB"}


def test_parse_proto_bool_field():
    proto = """
    message Req { bool active = 1; }
    message Resp {}
    service Svc { rpc Check (Req) returns (Resp); }
    """
    tools = _parse_proto_regex(proto)
    param = tools[0].parameters[0]
    assert param.name == "active"
    assert param.type == "boolean"
