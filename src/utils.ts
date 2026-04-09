import type { Tool } from './types.js';

/** Group tools by their tags */
export function groupByTag(tools: Tool[]): Map<string, Tool[]> {
  const groups = new Map<string, Tool[]>();
  for (const tool of tools) {
    const tags = tool.tags?.length ? tool.tags : ['untagged'];
    for (const tag of tags) {
      const group = groups.get(tag) ?? [];
      group.push(tool);
      groups.set(tag, group);
    }
  }
  return groups;
}

/** Group tools by HTTP method */
export function groupByMethod(tools: Tool[]): Map<string, Tool[]> {
  const groups = new Map<string, Tool[]>();
  for (const tool of tools) {
    const group = groups.get(tool.method) ?? [];
    group.push(tool);
    groups.set(tool.method, group);
  }
  return groups;
}

/** Group tools by protocol */
export function groupByProtocol(tools: Tool[]): Map<string, Tool[]> {
  const groups = new Map<string, Tool[]>();
  for (const tool of tools) {
    const group = groups.get(tool.protocol) ?? [];
    group.push(tool);
    groups.set(tool.protocol, group);
  }
  return groups;
}

/** Get a summary of discovered tools */
export function summarize(tools: Tool[]): {
  total: number;
  byTag: Record<string, number>;
  byMethod: Record<string, number>;
  byProtocol: Record<string, number>;
} {
  const byTag: Record<string, number> = {};
  const byMethod: Record<string, number> = {};
  const byProtocol: Record<string, number> = {};

  for (const tool of tools) {
    const tags = tool.tags?.length ? tool.tags : ['untagged'];
    for (const tag of tags) byTag[tag] = (byTag[tag] ?? 0) + 1;
    byMethod[tool.method] = (byMethod[tool.method] ?? 0) + 1;
    byProtocol[tool.protocol] = (byProtocol[tool.protocol] ?? 0) + 1;
  }

  return { total: tools.length, byTag, byMethod, byProtocol };
}

/** Search tools by name or description (case-insensitive) */
export function searchTools(tools: Tool[], query: string): Tool[] {
  const q = query.toLowerCase();
  return tools.filter(t =>
    t.name.toLowerCase().includes(q) ||
    t.description.toLowerCase().includes(q)
  );
}
