"""CLI entry point."""

from __future__ import annotations

import argparse
import json
import sys

from api_to_tools.core import discover
from api_to_tools.types import AuthConfig
from api_to_tools.adapters.formats import to_function_calling, to_anthropic_tools
from api_to_tools.utils import summarize, search_tools


def _discover_kwargs(args) -> dict:
    """Extract discovery kwargs from CLI args."""
    kw = {}
    if getattr(args, "scan_js", False):
        kw["scan_js"] = True
    if getattr(args, "crawl", False):
        kw["crawl"] = True
        kw["max_pages"] = getattr(args, "max_pages", 50)
        kw["headless"] = not getattr(args, "headed", False)
        kw["backend"] = getattr(args, "backend", "auto")
        kw["safe_mode"] = not getattr(args, "no_safe_mode", False)
    return kw


def _build_auth(args) -> AuthConfig | None:
    """Build AuthConfig from CLI arguments."""
    if hasattr(args, "bearer") and args.bearer:
        return AuthConfig(type="bearer", token=args.bearer)
    if hasattr(args, "basic") and args.basic:
        parts = args.basic.split(":", 1)
        return AuthConfig(type="basic", username=parts[0], password=parts[1] if len(parts) > 1 else "")
    if hasattr(args, "api_key") and args.api_key:
        parts = args.api_key.split("=", 1)
        return AuthConfig(type="api_key", key=parts[0], value=parts[1] if len(parts) > 1 else "")
    if hasattr(args, "cookie") and args.cookie:
        cookies = {}
        for c in args.cookie:
            k, _, v = c.partition("=")
            cookies[k] = v
        return AuthConfig(type="cookie", cookies=cookies)
    if hasattr(args, "login") and args.login:
        return AuthConfig(
            type="cookie",
            login_url=args.login,
            username=args.login_user or "",
            password=args.login_pass or "",
        )
    if hasattr(args, "header") and args.header:
        headers = {}
        for h in args.header:
            k, _, v = h.partition(":")
            headers[k.strip()] = v.strip()
        return AuthConfig(type="custom", headers=headers)
    return None


def _add_auth_args(parser: argparse.ArgumentParser):
    """Add common auth and discovery arguments to a subparser."""
    parser.add_argument("--scan-js", action="store_true",
                        help="Scan JS bundles to discover APIs (for sites without OpenAPI spec)")
    parser.add_argument("--crawl", action="store_true",
                        help="Use headless browser to crawl site and capture all API calls (recommended for SPAs)")
    parser.add_argument("--max-pages", type=int, default=50,
                        help="Max pages to crawl (default: 50)")
    parser.add_argument("--headed", action="store_true",
                        help="Show browser window (non-headless) for debugging")
    parser.add_argument("--backend", choices=["auto", "system", "playwright", "lightpanda"],
                        default="auto",
                        help="Browser backend: auto (system Chrome first), system, playwright, lightpanda")
    parser.add_argument("--no-safe-mode", action="store_true",
                        help="DISABLE safe mode (allows destructive requests to reach the server). "
                             "Only use on non-production or read-only accounts!")
    auth = parser.add_argument_group("authentication")
    auth.add_argument("--bearer", metavar="TOKEN", help="Bearer token")
    auth.add_argument("--basic", metavar="USER:PASS", help="Basic auth credentials")
    auth.add_argument("--api-key", metavar="KEY=VALUE", help="API key (header by default)")
    auth.add_argument("--cookie", metavar="KEY=VALUE", action="append", help="Cookie (repeatable)")
    auth.add_argument("--header", metavar="KEY:VALUE", action="append", help="Custom header (repeatable)")
    auth.add_argument("--login", metavar="URL", help="Login form URL (cookie auth)")
    auth.add_argument("--login-user", metavar="USER", help="Login username")
    auth.add_argument("--login-pass", metavar="PASS", help="Login password")


def cmd_serve(args):
    from api_to_tools.adapters.mcp_adapter import create_mcp_server

    auth = _build_auth(args)
    print(f"Discovering API at {args.url}...", file=sys.stderr)
    tools = discover(args.url, auth=auth, **_discover_kwargs(args))
    print(f"Found {len(tools)} tools. Starting MCP server '{args.name}'...", file=sys.stderr)
    for t in tools:
        print(f"  - {t.name}", file=sys.stderr)

    mcp = create_mcp_server(tools, name=args.name)
    mcp.run(transport="stdio")


def cmd_list(args):
    auth = _build_auth(args)
    tools = discover(args.url, auth=auth, **_discover_kwargs(args))

    if args.tag:
        tools = [t for t in tools if any(args.tag.lower() in tag.lower() for tag in t.tags)]
    if args.method:
        tools = [t for t in tools if t.method.upper() == args.method.upper()]
    if args.search:
        tools = search_tools(tools, args.search)

    for t in tools:
        params = ", ".join(f"{p.name}{'!' if p.required else '?'}:{p.type}" for p in t.parameters)
        print(f"[{t.method:<8}] {t.name}")
        if t.description:
            print(f"           {t.description[:80]}")
        if params:
            print(f"           ({params})")

    print(f"\nTotal: {len(tools)} tools", file=sys.stderr)


def cmd_info(args):
    auth = _build_auth(args)
    print(f"Discovering API at {args.url}...", file=sys.stderr)
    tools = discover(args.url, auth=auth, **_discover_kwargs(args))
    summary = summarize(tools)

    print(f"Total tools: {summary['total']}\n")

    print("By Protocol:")
    for k, v in summary["by_protocol"].items():
        print(f"  {k}: {v}")

    print("\nBy Method:")
    for k, v in summary["by_method"].items():
        print(f"  {k}: {v}")

    print("\nBy Tag:")
    tags = list(summary["by_tag"].items())
    for k, v in tags[:20]:
        print(f"  {k}: {v}")
    if len(tags) > 20:
        print(f"  ... and {len(tags) - 20} more tags")


def cmd_export(args):
    auth = _build_auth(args)
    tools = discover(args.url, auth=auth, **_discover_kwargs(args))

    if args.tag:
        tools = [t for t in tools if any(args.tag.lower() in tag.lower() for tag in t.tags)]
    if args.search:
        tools = search_tools(tools, args.search)

    if args.format == "openai":
        output = to_function_calling(tools)
    elif args.format == "anthropic":
        output = to_anthropic_tools(tools)
    else:
        from dataclasses import asdict
        output = [asdict(t) for t in tools]

    print(json.dumps(output, indent=2, ensure_ascii=False))


def main():
    parser = argparse.ArgumentParser(
        prog="api-to-tools",
        description="Convert any API into LLM-callable tools",
    )
    sub = parser.add_subparsers(dest="command")

    # serve
    p_serve = sub.add_parser("serve", help="Start MCP server (stdio)")
    p_serve.add_argument("url", help="API spec URL or website URL")
    p_serve.add_argument("--name", default="api-to-tools", help="MCP server name")
    _add_auth_args(p_serve)

    # list
    p_list = sub.add_parser("list", help="List discovered tools")
    p_list.add_argument("url")
    p_list.add_argument("--tag", help="Filter by tag")
    p_list.add_argument("--method", help="Filter by HTTP method")
    p_list.add_argument("--search", help="Search by name/description")
    _add_auth_args(p_list)

    # info
    p_info = sub.add_parser("info", help="Show API summary")
    p_info.add_argument("url")
    _add_auth_args(p_info)

    # export
    p_export = sub.add_parser("export", help="Export tool definitions")
    p_export.add_argument("url")
    p_export.add_argument("--format", choices=["openai", "anthropic", "json"], default="json")
    p_export.add_argument("--tag", help="Filter by tag")
    p_export.add_argument("--search", help="Search filter")
    _add_auth_args(p_export)

    args = parser.parse_args()

    if not args.command:
        parser.print_help()
        sys.exit(1)

    cmd_map = {"serve": cmd_serve, "list": cmd_list, "info": cmd_info, "export": cmd_export}
    cmd_map[args.command](args)


if __name__ == "__main__":
    main()
