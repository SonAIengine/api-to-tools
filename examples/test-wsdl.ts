import { discover, execute } from '../src/index.js';

async function main() {
  console.log('=== WSDL/SOAP Test ===\n');

  // 1. Calculator
  console.log('1. DNEOnline Calculator');
  try {
    const tools = await discover('http://www.dneonline.com/calculator.asmx?WSDL');
    console.log(`   Found ${tools.length} tools:`);
    for (const t of tools) {
      console.log(`   - ${t.name}: ${t.description}`);
      console.log(`     params: ${t.parameters.map(p => `${p.name}(${p.type})`).join(', ')}`);
    }

    // Execute Add(5, 3)
    const addTool = tools.find(t => t.name === 'Add');
    if (addTool) {
      console.log('\n   Executing: Add(5, 3)');
      const result = await execute(addTool, { intA: 5, intB: 3 });
      console.log('   Result:', JSON.stringify(result.data));
    }
  } catch (e) {
    console.log('   Error:', (e as Error).message);
  }

  // 2. CountryInfo
  console.log('\n2. Oorsprong CountryInfo');
  try {
    const tools = await discover('http://webservices.oorsprong.org/websamples.countryinfo/CountryInfoService.wso?WSDL');
    console.log(`   Found ${tools.length} tools:`);
    for (const t of tools.slice(0, 5)) {
      console.log(`   - ${t.name}: ${t.description}`);
    }
    if (tools.length > 5) console.log(`   ... and ${tools.length - 5} more`);

    // Execute CapitalCity("KR")
    const capitalTool = tools.find(t => t.name === 'CapitalCity');
    if (capitalTool) {
      console.log('\n   Executing: CapitalCity("KR")');
      const result = await execute(capitalTool, { sCountryISOCode: 'KR' });
      console.log('   Result:', JSON.stringify(result.data));
    }
  } catch (e) {
    console.log('   Error:', (e as Error).message);
  }

  // 3. NumberConversion
  console.log('\n3. DataAccess NumberConversion');
  try {
    const tools = await discover('https://www.dataaccess.com/webservicesserver/NumberConversion.wso?WSDL');
    console.log(`   Found ${tools.length} tools:`);
    for (const t of tools) {
      console.log(`   - ${t.name}: ${t.description}`);
      console.log(`     params: ${t.parameters.map(p => `${p.name}(${p.type})`).join(', ')}`);
    }

    // Execute NumberToWords(42)
    const numTool = tools.find(t => t.name === 'NumberToWords');
    if (numTool) {
      console.log('\n   Executing: NumberToWords(42)');
      const result = await execute(numTool, { ubiNum: 42 });
      console.log('   Result:', JSON.stringify(result.data));
    }
  } catch (e) {
    console.log('   Error:', (e as Error).message);
  }
}

main().catch(console.error);
