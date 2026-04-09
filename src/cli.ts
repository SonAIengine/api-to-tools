#!/usr/bin/env node
import { discover } from './index.js';
import { createMcpServer } from './adapters/mcp.js';
import { summarize, searchTools, groupByTag } from './utils.js';
import { toFunctionCalling, toAnthropicTools } from './index.js';

const args = process.argv.slice(2);
const command = args[0];

function printUsage() {
  console.error(`api-to-tools - Convert any API into LLM-callable tools

Usage:
  api-to-tools serve  <url> [--name <name>]       Start MCP server (stdio)
  api-to-tools list   <url> [--tag <tag>] [--method <method>]
  api-to-tools info   <url>                        Show API summary
  api-to-tools export <url> --format <format>      Export tool definitions
                                                   Formats: openai, anthropic, json

Options:
  --name <name>       MCP server name (default: api-to-tools)
  --tag <tag>         Filter by tag
  --method <method>   Filter by HTTP method (GET, POST, etc.)
  --format <format>   Export format
  --search <query>    Search tools by name/description

Examples:
  api-to-tools serve https://date.nager.at --name nager
  api-to-tools list https://petstore.swagger.io --tag pet
  api-to-tools info https://httpbin.org
  api-to-tools export https://date.nager.at/openapi/v3.json --format anthropic

  # Use as MCP server in Claude Code settings:
  # "command": "npx", "args": ["api-to-tools", "serve", "<url>"]`);
}

function parseFlags(args: string[]): Record<string, string> {
  const flags: Record<string, string> = {};
  for (let i = 0; i < args.length; i++) {
    if (args[i].startsWith('--') && i + 1 < args.length) {
      flags[args[i].slice(2)] = args[i + 1];
      i++;
    }
  }
  return flags;
}

function getUrl(args: string[]): string | undefined {
  return args.find(a => !a.startsWith('--') && a !== command);
}

async function cmdServe(url: string, flags: Record<string, string>) {
  const name = flags.name ?? 'api-to-tools';
  console.error(`Discovering API at ${url}...`);
  const tools = await discover(url);
  console.error(`Found ${tools.length} tools. Starting MCP server "${name}"...`);
  for (const t of tools) {
    console.error(`  - ${t.name}`);
  }
  const { start } = createMcpServer(tools, { name });
  await start();
}

async function cmdList(url: string, flags: Record<string, string>) {
  let tools = await discover(url);

  if (flags.tag) {
    tools = tools.filter(t => t.tags?.some(tag => tag.toLowerCase().includes(flags.tag.toLowerCase())));
  }
  if (flags.method) {
    tools = tools.filter(t => t.method.toUpperCase() === flags.method.toUpperCase());
  }
  if (flags.search) {
    tools = searchTools(tools, flags.search);
  }

  for (const t of tools) {
    const params = t.parameters.map(p => `${p.name}${p.required ? '!' : '?'}:${p.type}`).join(', ');
    console.log(`[${t.method.padEnd(8)}] ${t.name}`);
    if (t.description) console.log(`           ${t.description.slice(0, 80)}`);
    if (params) console.log(`           (${params})`);
  }
  console.error(`\nTotal: ${tools.length} tools`);
}

async function cmdInfo(url: string) {
  console.error(`Discovering API at ${url}...`);
  const tools = await discover(url);
  const summary = summarize(tools);

  console.log(`Total tools: ${summary.total}\n`);

  console.log('By Protocol:');
  for (const [k, v] of Object.entries(summary.byProtocol)) {
    console.log(`  ${k}: ${v}`);
  }

  console.log('\nBy Method:');
  for (const [k, v] of Object.entries(summary.byMethod).sort((a, b) => b[1] - a[1])) {
    console.log(`  ${k}: ${v}`);
  }

  console.log('\nBy Tag:');
  const tagEntries = Object.entries(summary.byTag).sort((a, b) => b[1] - a[1]);
  for (const [k, v] of tagEntries.slice(0, 20)) {
    console.log(`  ${k}: ${v}`);
  }
  if (tagEntries.length > 20) console.log(`  ... and ${tagEntries.length - 20} more tags`);
}

async function cmdExport(url: string, flags: Record<string, string>) {
  const format = flags.format ?? 'json';
  let tools = await discover(url);

  if (flags.tag) {
    tools = tools.filter(t => t.tags?.some(tag => tag.toLowerCase().includes(flags.tag.toLowerCase())));
  }
  if (flags.search) {
    tools = searchTools(tools, flags.search);
  }

  let output: unknown;
  switch (format) {
    case 'openai':
      output = toFunctionCalling(tools);
      break;
    case 'anthropic':
      output = toAnthropicTools(tools);
      break;
    case 'json':
    default:
      output = tools;
      break;
  }

  console.log(JSON.stringify(output, null, 2));
}

async function main() {
  if (!command || command === '--help' || command === '-h') {
    printUsage();
    process.exit(0);
  }

  const url = getUrl(args.slice(1));
  if (!url) {
    console.error('Error: URL is required');
    printUsage();
    process.exit(1);
  }

  const flags = parseFlags(args);

  switch (command) {
    case 'serve':
      await cmdServe(url, flags);
      break;
    case 'list':
      await cmdList(url, flags);
      break;
    case 'info':
      await cmdInfo(url);
      break;
    case 'export':
      await cmdExport(url, flags);
      break;
    default:
      // Backward compat: treat first arg as URL for serve
      await cmdServe(command, { name: args[1] ?? 'api-to-tools' });
  }
}

main().catch(e => {
  console.error('Fatal:', e.message);
  process.exit(1);
});
