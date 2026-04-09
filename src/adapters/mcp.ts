import { z } from 'zod';
import { McpServer } from '@modelcontextprotocol/sdk/server/mcp.js';
import { StdioServerTransport } from '@modelcontextprotocol/sdk/server/stdio.js';
import type { Tool } from '../types.js';
import { getExecutor } from '../executors/index.js';

/** Convert a tool parameter type string to a Zod schema */
function paramTypeToZod(param: { type: string; enum?: string[]; description?: string }) {
  let schema: z.ZodType;

  if (param.enum?.length) {
    schema = z.enum(param.enum as [string, ...string[]]);
  } else {
    switch (param.type) {
      case 'integer':
      case 'number':
        schema = z.number();
        break;
      case 'boolean':
        schema = z.boolean();
        break;
      case 'array':
        schema = z.array(z.unknown());
        break;
      case 'object':
        schema = z.record(z.unknown());
        break;
      default:
        schema = z.string();
    }
  }

  if (param.description) {
    schema = schema.describe(param.description);
  }

  return schema;
}

/** Build a Zod object schema from tool parameters */
function toolToZodSchema(tool: Tool): z.ZodObject<Record<string, z.ZodType>> {
  const shape: Record<string, z.ZodType> = {};

  for (const param of tool.parameters) {
    let schema = paramTypeToZod(param);
    if (!param.required) {
      schema = schema.optional();
    }
    shape[param.name] = schema;
  }

  return z.object(shape);
}

export interface McpServerOptions {
  name?: string;
  version?: string;
}

/**
 * Create an MCP Server from a list of tools.
 *
 * @example
 * ```ts
 * const tools = await discover('https://date.nager.at/openapi/v3.json');
 * const { start } = createMcpServer(tools, { name: 'nager-date' });
 * await start();
 * ```
 */
export function createMcpServer(tools: Tool[], options: McpServerOptions = {}): {
  server: McpServer;
  start: () => Promise<void>;
} {
  const name = options.name ?? 'api-to-tools';
  const version = options.version ?? '0.1.0';

  const server = new McpServer({ name, version });

  for (const tool of tools) {
    const zodSchema = toolToZodSchema(tool);

    server.tool(
      tool.name,
      tool.description,
      zodSchema.shape,
      async (args: Record<string, unknown>) => {
        try {
          const executor = getExecutor(tool.protocol);
          const result = await executor.execute(tool, args);

          const content = typeof result.data === 'string'
            ? result.data
            : JSON.stringify(result.data, null, 2);

          return {
            content: [{ type: 'text' as const, text: content }],
          };
        } catch (error) {
          return {
            content: [{ type: 'text' as const, text: `Error: ${(error as Error).message}` }],
            isError: true,
          };
        }
      },
    );
  }

  async function start() {
    const transport = new StdioServerTransport();
    await server.connect(transport);
  }

  return { server, start };
}
