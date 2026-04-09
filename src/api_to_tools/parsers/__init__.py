"""API spec parsers."""

from __future__ import annotations

from api_to_tools.types import SpecType, Tool
from api_to_tools.parsers.openapi import parse_openapi
from api_to_tools.parsers.wsdl import parse_wsdl
from api_to_tools.parsers.graphql import parse_graphql
from api_to_tools.parsers.grpc import parse_grpc
from api_to_tools.parsers.jsbundle import scan_js_bundles


def _lazy_crawler(*args, **kwargs):
    """Lazy import to avoid requiring playwright unless used."""
    from api_to_tools.parsers.crawler import crawl_site
    return crawl_site(*args, **kwargs)


PARSERS: dict[SpecType, callable] = {
    "openapi": parse_openapi,
    "wsdl": parse_wsdl,
    "graphql": parse_graphql,
    "grpc": parse_grpc,
    "jsbundle": scan_js_bundles,
    "crawler": _lazy_crawler,
}


def get_parser(spec_type: SpecType):
    parser = PARSERS.get(spec_type)
    if not parser:
        raise NotImplementedError(f"Parser for '{spec_type}' is not yet implemented")
    return parser
