import { discover } from '../src/index.js';

async function main() {
  console.log('=== Large Spec Test ===\n');

  // httpbin (52 paths)
  console.log('1. httpbin (medium)');
  const httpbin = await discover('https://httpbin.org/spec.json');
  console.log(`   ${httpbin.length} tools`);

  // Group by tag
  const byTag = new Map<string, number>();
  for (const t of httpbin) {
    for (const tag of t.tags ?? ['untagged']) {
      byTag.set(tag, (byTag.get(tag) ?? 0) + 1);
    }
  }
  console.log('   Tags:', Object.fromEntries(byTag));

  // Filter example: only GET methods
  const getOnly = httpbin.filter(t => t.method === 'GET');
  console.log(`   GET only: ${getOnly.length} tools`);

  // Discourse (79 paths)
  console.log('\n2. Discourse');
  try {
    const discourse = await discover('https://docs.discourse.org/openapi.json');
    console.log(`   ${discourse.length} tools`);

    const dTags = new Map<string, number>();
    for (const t of discourse) {
      for (const tag of t.tags ?? ['untagged']) {
        dTags.set(tag, (dTags.get(tag) ?? 0) + 1);
      }
    }
    console.log('   Tags:', Object.fromEntries([...dTags.entries()].sort((a, b) => b[1] - a[1]).slice(0, 10)));
  } catch (e) {
    console.log('   Error:', (e as Error).message.slice(0, 100));
  }

  // Jira (421 paths - test with tag filtering)
  console.log('\n3. Jira Cloud (large)');
  try {
    const start = Date.now();
    const jira = await discover('https://developer.atlassian.com/cloud/jira/platform/swagger-v3.v3.json');
    const elapsed = Date.now() - start;
    console.log(`   ${jira.length} tools (${elapsed}ms)`);

    const jTags = new Map<string, number>();
    for (const t of jira) {
      for (const tag of t.tags ?? ['untagged']) {
        jTags.set(tag, (jTags.get(tag) ?? 0) + 1);
      }
    }
    console.log('   Top 10 tags:', Object.fromEntries([...jTags.entries()].sort((a, b) => b[1] - a[1]).slice(0, 10)));

    // Filter: only "Issues" tag
    const issueTools = jira.filter(t => t.tags?.includes('Issues'));
    console.log(`   "Issues" tag: ${issueTools.length} tools`);
    for (const t of issueTools.slice(0, 5)) {
      console.log(`     - ${t.name}: ${t.description.slice(0, 50)}`);
    }
  } catch (e) {
    console.log('   Error:', (e as Error).message.slice(0, 100));
  }
}

main().catch(console.error);
