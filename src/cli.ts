#!/usr/bin/env node
import { discover } from './index.js';
import { createMcpServer } from './adapters/mcp.js';

const url = process.argv[2];
const name = process.argv[3] ?? 'api-to-tools';

if (!url) {
  console.error('Usage: api-to-tools <spec-url> [server-name]');
  console.error('');
  console.error('Examples:');
  console.error('  api-to-tools https://petstore.swagger.io');
  console.error('  api-to-tools https://date.nager.at/openapi/v3.json nager-date');
  console.error('  api-to-tools https://countries.trevorblades.com/graphql countries');
  console.error('  api-to-tools "http://www.dneonline.com/calculator.asmx?WSDL" calculator');
  process.exit(1);
}

async function main() {
  console.error(`Discovering API at ${url}...`);
  const tools = await discover(url);
  console.error(`Found ${tools.length} tools. Starting MCP server "${name}"...`);

  for (const t of tools) {
    console.error(`  - ${t.name}: ${t.description.slice(0, 60)}`);
  }

  const { start } = createMcpServer(tools, { name });
  await start();
}

main().catch(e => {
  console.error('Fatal:', e.message);
  process.exit(1);
});
