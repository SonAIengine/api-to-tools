import { discover } from '../src/index.js';
import { createMcpServer } from '../src/adapters/mcp.js';

async function main() {
  console.log('=== MCP Server Test ===\n');

  // Discover Nager.Date API
  const tools = await discover('https://date.nager.at/openapi/v3.json');
  console.log(`Discovered ${tools.length} tools`);

  // Create MCP server (don't start stdio, just verify it builds)
  const { server } = createMcpServer(tools, { name: 'nager-date', version: '1.0.0' });
  console.log('MCP server created successfully');
  console.log(`Server name: nager-date`);
  console.log(`Tools registered: ${tools.length}`);

  // Show how to configure in Claude Code
  console.log('\n--- Claude Code MCP config ---');
  console.log(JSON.stringify({
    "mcpServers": {
      "nager-date": {
        "command": "npx",
        "args": ["tsx", `${process.cwd()}/src/cli.ts`, "https://date.nager.at/openapi/v3.json", "nager-date"]
      }
    }
  }, null, 2));

  console.log('\nDone!');
}

main().catch(console.error);
