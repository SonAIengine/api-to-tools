import { readFileSync } from 'fs';
import { resolve } from 'path';
import { grpcParser } from '../src/parsers/grpc.js';
import { asyncapiParser } from '../src/parsers/asyncapi.js';

async function main() {
  console.log('=== gRPC Parser Test ===\n');

  const protoPath = resolve(import.meta.dirname, 'fixtures/greeter.proto');
  const grpcTools = await grpcParser.parse(protoPath);
  console.log(`Found ${grpcTools.length} gRPC tools:`);
  for (const t of grpcTools) {
    console.log(`  - ${t.name}: ${t.description}`);
    console.log(`    params: ${t.parameters.map(p => `${p.name}(${p.type})`).join(', ') || 'none'}`);
    const meta = t.metadata as Record<string, unknown>;
    if (meta.responseStream) console.log('    (server streaming)');
  }

  console.log('\n=== AsyncAPI Parser Test ===\n');

  const asyncContent = readFileSync(resolve(import.meta.dirname, 'fixtures/chat.asyncapi.yaml'), 'utf-8');
  const asyncTools = await asyncapiParser.parse(asyncContent);
  console.log(`Found ${asyncTools.length} AsyncAPI tools:`);
  for (const t of asyncTools) {
    console.log(`  - ${t.name} [${t.method}]: ${t.description}`);
    console.log(`    params: ${t.parameters.map(p => `${p.name}(${p.type}${p.required ? '!' : ''})`).join(', ') || 'none'}`);
  }
}

main().catch(console.error);
