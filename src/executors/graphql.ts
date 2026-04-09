import type { Tool, ToolExecutor, ToolExecutionResult } from '../types.js';

function buildQuery(tool: Tool, args: Record<string, unknown>): string {
  const kind = tool.method; // 'query' or 'mutation'
  const params = tool.parameters;

  if (params.length === 0) {
    return `${kind} { ${tool.name} }`;
  }

  // Build variable definitions and arguments
  const varDefs = params.map(p => `$${p.name}: ${p.type}${p.required ? '!' : ''}`).join(', ');
  const fieldArgs = params
    .filter(p => args[p.name] !== undefined)
    .map(p => `${p.name}: $${p.name}`)
    .join(', ');

  return `${kind}(${varDefs}) { ${tool.name}(${fieldArgs}) }`;
}

export const graphqlExecutor: ToolExecutor = {
  protocol: 'graphql',

  async execute(tool: Tool, args: Record<string, unknown>): Promise<ToolExecutionResult> {
    const query = buildQuery(tool, args);
    const variables: Record<string, unknown> = {};
    for (const param of tool.parameters) {
      if (args[param.name] !== undefined) {
        variables[param.name] = args[param.name];
      }
    }

    const res = await fetch(tool.endpoint, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ query, variables }),
    });

    const raw = await res.text();
    let data: unknown;
    try { data = JSON.parse(raw); } catch { data = raw; }

    const headers: Record<string, string> = {};
    res.headers.forEach((value, key) => { headers[key] = value; });

    return { status: res.status, data, headers, raw };
  },
};
