import { discover, execute, toFunctionCalling, toAnthropicTools } from '../src/index.js';

async function main() {
  console.log('=== api-to-tools demo ===\n');

  // 1. Discover from direct spec URL
  console.log('1. Nager.Date API (direct spec URL)');
  const nagerTools = await discover('https://date.nager.at/openapi/v3.json');
  console.log(`   Found ${nagerTools.length} tools:`);
  for (const t of nagerTools) {
    console.log(`   - ${t.name}: ${t.description} [${t.method}]`);
  }

  // 2. Execute a tool
  console.log('\n2. Executing: PublicHolidays for KR 2026');
  const holidayTool = nagerTools.find(t => t.name.includes('PublicHolidays'));
  if (holidayTool) {
    const result = await execute(holidayTool, { year: '2026', countryCode: 'KR' });
    const holidays = result.data as { name: string; date: string }[];
    console.log(`   Found ${holidays.length} holidays:`);
    for (const h of holidays.slice(0, 5)) {
      console.log(`   - ${h.date}: ${h.name}`);
    }
    console.log('   ...');
  }

  // 3. Convert to LLM formats
  console.log('\n3. OpenAI function calling format:');
  const fcTools = toFunctionCalling(nagerTools.slice(0, 2));
  console.log(JSON.stringify(fcTools[0], null, 2).slice(0, 300) + '...');

  console.log('\n4. Anthropic tool_use format:');
  const anthropicTools = toAnthropicTools(nagerTools.slice(0, 2));
  console.log(JSON.stringify(anthropicTools[0], null, 2).slice(0, 300) + '...');

  // 4. Auto-discover from website URL
  console.log('\n5. Auto-discover from Petstore website');
  const petTools = await discover('https://petstore3.swagger.io/api/v3/openapi.json');
  console.log(`   Found ${petTools.length} tools`);
  for (const t of petTools.slice(0, 5)) {
    console.log(`   - ${t.name}: ${t.description}`);
  }
}

main().catch(console.error);
