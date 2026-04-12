"""Integration tests against public APIs.

These tests make real network requests.
Run only integration tests:  pytest -m integration
Skip integration tests:      pytest -m "not integration"
"""

import pytest

from api_to_tools import discover, execute, to_function_calling, to_anthropic_tools, to_gemini_tools


pytestmark = pytest.mark.integration


class TestNagerDateAPI:
    """https://date.nager.at — public holiday API with OpenAPI spec."""

    URL = "https://date.nager.at/openapi/v3.json"

    def test_discover(self):
        tools = discover(self.URL)
        assert len(tools) > 5
        names = {t.name for t in tools}
        assert any("Holiday" in n or "holiday" in n.lower() for n in names)

    def test_discover_with_cache(self):
        tools1 = discover(self.URL, cache_ttl=60)
        tools2 = discover(self.URL, cache_ttl=60)
        assert len(tools1) == len(tools2)

    def test_execute_get(self):
        tools = discover(self.URL, cache_ttl=60)
        # Find a simple GET endpoint
        tool = next(
            (t for t in tools if t.method == "GET" and "country" in t.name.lower()),
            None,
        )
        if tool is None:
            pytest.skip("No suitable GET endpoint found")
        # Build minimal args
        args = {}
        for p in tool.parameters:
            if p.required and p.name.lower() in ("countrycode", "country_code"):
                args[p.name] = "KR"
        result = execute(tool, args)
        assert result.status == 200

    def test_to_openai_format(self):
        tools = discover(self.URL, cache_ttl=60)
        openai_tools = to_function_calling(tools)
        assert len(openai_tools) > 0
        assert openai_tools[0]["type"] == "function"
        assert "parameters" in openai_tools[0]["function"]

    def test_to_anthropic_format(self):
        tools = discover(self.URL, cache_ttl=60)
        anthropic_tools = to_anthropic_tools(tools)
        assert len(anthropic_tools) > 0
        assert "input_schema" in anthropic_tools[0]

    def test_to_gemini_format(self):
        tools = discover(self.URL, cache_ttl=60)
        gemini_tools = to_gemini_tools(tools)
        assert len(gemini_tools) == 1
        assert "function_declarations" in gemini_tools[0]


class TestPetstoreAPI:
    """https://petstore3.swagger.io — classic Swagger Petstore v3."""

    URL = "https://petstore3.swagger.io/api/v3/openapi.json"

    def test_discover(self):
        tools = discover(self.URL)
        assert len(tools) > 10
        methods = {t.method for t in tools}
        assert "GET" in methods
        assert "POST" in methods

    def test_discover_filters(self):
        tools = discover(self.URL, methods=["GET"])
        assert all(t.method == "GET" for t in tools)

    def test_discover_tag_filter(self):
        tools = discover(self.URL, tags=["pet"])
        assert len(tools) > 0
        assert all("pet" in t.tags for t in tools)


class TestHttpBin:
    """https://httpbin.org — HTTP testing service."""

    URL = "https://httpbin.org/spec.json"

    def test_discover(self):
        tools = discover(self.URL)
        assert len(tools) > 5

    def test_get_tools_exist(self):
        tools = discover(self.URL, cache_ttl=60)
        get_tools = [t for t in tools if t.method == "GET"]
        assert len(get_tools) > 0
