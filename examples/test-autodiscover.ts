import { discover } from '../src/index.js';

async function main() {
  console.log('=== Auto-discover Test ===');

  const targets = [
    { name: 'Petstore Swagger UI', url: 'https://petstore.swagger.io' },
    { name: 'date.nager.at (root)', url: 'https://date.nager.at' },
    { name: 'FakeRESTApi', url: 'https://fakerestapi.azurewebsites.net' },
    { name: 'httpbin', url: 'https://httpbin.org' },
  ];

  for (const { name, url } of targets) {
    console.log(`\n${name} (${url})`);
    try {
      const tools = await discover(url);
      console.log(`  → Found ${tools.length} tools`);
      for (const t of tools.slice(0, 3)) {
        console.log(`    - ${t.name}: ${t.description.slice(0, 60)}`);
      }
      if (tools.length > 3) console.log(`    ... and ${tools.length - 3} more`);
    } catch (e) {
      console.log(`  → Error: ${(e as Error).message.slice(0, 100)}`);
    }
  }
}

main().catch(console.error);
