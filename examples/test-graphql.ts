import { discover, execute } from '../src/index.js';

async function main() {
  console.log('=== GraphQL Test ===\n');

  // 1. Countries API
  console.log('1. Countries API');
  try {
    const tools = await discover('https://countries.trevorblades.com/graphql');
    console.log(`   Found ${tools.length} tools:`);
    for (const t of tools) {
      console.log(`   - [${t.method}] ${t.name}(${t.parameters.map(p => `${p.name}: ${p.type}`).join(', ')})`);
    }

    // Execute country query
    const countryTool = tools.find(t => t.name === 'country');
    if (countryTool) {
      console.log('\n   Executing: country(code: "KR")');
      const result = await execute(countryTool, { code: 'KR' });
      console.log('   Result:', JSON.stringify(result.data, null, 2).slice(0, 300));
    }
  } catch (e) {
    console.log('   Error:', (e as Error).message);
  }

  // 2. Rick and Morty
  console.log('\n2. Rick and Morty API');
  try {
    const tools = await discover('https://rickandmortyapi.com/graphql');
    console.log(`   Found ${tools.length} tools:`);
    for (const t of tools) {
      console.log(`   - [${t.method}] ${t.name}(${t.parameters.map(p => `${p.name}: ${p.type}`).join(', ')})`);
    }

    // Execute characters query
    const charTool = tools.find(t => t.name === 'characters');
    if (charTool) {
      console.log('\n   Executing: characters(page: 1)');
      const result = await execute(charTool, { page: 1 });
      console.log('   Result:', JSON.stringify(result.data, null, 2).slice(0, 300));
    }
  } catch (e) {
    console.log('   Error:', (e as Error).message);
  }

  // 3. Pokemon
  console.log('\n3. Pokemon GraphQL API');
  try {
    const tools = await discover('https://graphql-pokeapi.graphcdn.app/');
    console.log(`   Found ${tools.length} tools:`);
    for (const t of tools) {
      console.log(`   - [${t.method}] ${t.name}(${t.parameters.map(p => `${p.name}: ${p.type}`).join(', ')})`);
    }
  } catch (e) {
    console.log('   Error:', (e as Error).message);
  }
}

main().catch(console.error);
