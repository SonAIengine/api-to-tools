"""CLI entry point."""

from __future__ import annotations

import argparse
import json
import sys

from api_to_tools.core import discover
from api_to_tools.adapters.formats import to_function_calling, to_anthropic_tools
from api_to_tools.utils import summarize, search_tools


def cmd_serve(args):
    from api_to_tools.adapters.mcp_adapter import create_mcp_server

    print(f"Discovering API at {args.url}...", file=sys.stderr)
    tools = discover(args.url)
    print(f"Found {len(tools)} tools. Starting MCP server '{args.name}'...", file=sys.stderr)
    for t in tools:
        print(f"  - {t.name}", file=sys.stderr)

    mcp = create_mcp_server(tools, name=args.name)
    mcp.run(transport="stdio")


def cmd_list(args):
    tools = discover(args.url)

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
    print(f"Discovering API at {args.url}...", file=sys.stderr)
    tools = discover(args.url)
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
    tools = discover(args.url)

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

    # list
    p_list = sub.add_parser("list", help="List discovered tools")
    p_list.add_argument("url")
    p_list.add_argument("--tag", help="Filter by tag")
    p_list.add_argument("--method", help="Filter by HTTP method")
    p_list.add_argument("--search", help="Search by name/description")

    # info
    p_info = sub.add_parser("info", help="Show API summary")
    p_info.add_argument("url")

    # export
    p_export = sub.add_parser("export", help="Export tool definitions")
    p_export.add_argument("url")
    p_export.add_argument("--format", choices=["openai", "anthropic", "json"], default="json")
    p_export.add_argument("--tag", help="Filter by tag")
    p_export.add_argument("--search", help="Search filter")

    args = parser.parse_args()

    if not args.command:
        parser.print_help()
        sys.exit(1)

    cmd_map = {"serve": cmd_serve, "list": cmd_list, "info": cmd_info, "export": cmd_export}
    cmd_map[args.command](args)


if __name__ == "__main__":
    main()
