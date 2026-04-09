import { Parser } from '@asyncapi/parser';
import type { SpecParser, Tool, ToolParameter } from '../types.js';

function schemaToParams(schema: Record<string, unknown> | undefined): ToolParameter[] {
  if (!schema) return [];
  const properties = (schema as { properties?: Record<string, Record<string, unknown>> }).properties;
  const required = (schema as { required?: string[] }).required ?? [];
  if (!properties) return [];

  return Object.entries(properties).map(([name, prop]) => ({
    name,
    type: (prop.type as string) ?? 'string',
    required: required.includes(name),
    description: prop.description as string | undefined,
    ...(prop.enum ? { enum: prop.enum as string[] } : {}),
  }));
}

export const asyncapiParser: SpecParser = {
  type: 'asyncapi',

  async parse(input: string | object): Promise<Tool[]> {
    const parser = new Parser();
    const content = typeof input === 'string' ? input : JSON.stringify(input);
    const { document, diagnostics } = await parser.parse(content);

    if (!document) {
      const errors = diagnostics?.filter(d => d.severity === 0) ?? [];
      throw new Error(`Failed to parse AsyncAPI: ${errors.map(e => e.message).join(', ')}`);
    }

    const tools: Tool[] = [];
    const channels = document.channels();

    for (const channel of channels.all()) {
      const channelId = channel.id();
      const operations = channel.operations();

      for (const op of operations.all()) {
        const action = op.action(); // 'send' | 'receive'
        const messages = op.messages();

        for (const msg of messages.all()) {
          const payload = msg.payload();
          const payloadJson = payload?.json() as Record<string, unknown> | undefined;

          tools.push({
            name: `${action}_${channelId}`.replace(/[^a-zA-Z0-9]/g, '_'),
            description: op.summary() ?? op.description() ?? `${action} on ${channelId}`,
            parameters: schemaToParams(payloadJson),
            endpoint: channelId,
            method: action,
            protocol: 'async',
            responseFormat: 'json',
            tags: op.tags()?.all().map(t => t.name()) ?? [],
            metadata: {
              channelId,
              action,
              messageId: msg.id(),
            },
          });
        }

        // If no messages, still register the operation
        if (messages.all().length === 0) {
          tools.push({
            name: `${action}_${channelId}`.replace(/[^a-zA-Z0-9]/g, '_'),
            description: op.summary() ?? op.description() ?? `${action} on ${channelId}`,
            parameters: [],
            endpoint: channelId,
            method: action,
            protocol: 'async',
            responseFormat: 'json',
            tags: op.tags()?.all().map(t => t.name()) ?? [],
          });
        }
      }
    }

    return tools;
  },
};
