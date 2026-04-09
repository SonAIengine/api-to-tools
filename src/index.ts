import { detect } from './detector/index.js';
import { getParser } from './parsers/index.js';
import { getExecutor } from './executors/index.js';
import type {
  Tool, ToolExecutionResult, DetectionResult,
  DiscoverOptions, ToToolsOptions,
} from './types.js';

export type * from './types.js';
export { detect } from './detector/index.js';
export { getParser } from './parsers/index.js';
export { getExecutor } from './executors/index.js';
export { createMcpServer } from './adapters/index.js';
export type { McpServerOptions } from './adapters/index.js';
export { groupByTag, groupByMethod, groupByProtocol, summarize, searchTools } from './utils.js';

/**
 * Discover and parse API spec from a URL into tools.
 *
 * @example
 * ```ts
 * const tools = await discover('https://petstore3.swagger.io/api/v3/openapi.json')
 * const tools = await discover('https://date.nager.at') // auto-detects spec
 * ```
 */
export async function discover(
  url: string,
  options: DiscoverOptions & ToToolsOptions = {},
): Promise<Tool[]> {
  const detection = await detect(url, options);
  return toTools(detection, options);
}

/**
 * Parse a detected spec into tools.
 */
export async function toTools(
  detection: DetectionResult,
  options: ToToolsOptions = {},
): Promise<Tool[]> {
  const parser = getParser(detection.type);
  const input = detection.rawContent ?? detection.specUrl;
  let tools = await parser.parse(input, detection.specUrl);

  // Apply base URL override
  if (options.baseUrl) {
    tools = tools.map(t => ({
      ...t,
      endpoint: t.endpoint
        ? t.endpoint.replace(/^https?:\/\/[^/]+/, options.baseUrl!)
        : `${options.baseUrl}${t.endpoint}`,
    }));
  }

  // Apply filters
  if (options.tags?.length) {
    tools = tools.filter(t => t.tags?.some(tag => options.tags!.includes(tag)));
  }
  if (options.methods?.length) {
    const methods = options.methods.map(m => m.toUpperCase());
    tools = tools.filter(t => methods.includes(t.method.toUpperCase()));
  }
  if (options.pathFilter) {
    tools = tools.filter(t => options.pathFilter!.test(t.endpoint));
  }

  return tools;
}

/**
 * Execute a tool with given arguments.
 *
 * @example
 * ```ts
 * const tools = await discover('https://date.nager.at/openapi/v3.json')
 * const result = await execute(tools[0], { countryCode: 'KR', year: '2026' })
 * ```
 */
export async function execute(
  tool: Tool,
  args: Record<string, unknown>,
): Promise<ToolExecutionResult> {
  const executor = getExecutor(tool.protocol);
  return executor.execute(tool, args);
}

/**
 * Convert tools to OpenAI function calling format.
 */
export function toFunctionCalling(tools: Tool[]) {
  return tools.map(tool => ({
    type: 'function' as const,
    function: {
      name: tool.name,
      description: tool.description,
      parameters: {
        type: 'object',
        properties: Object.fromEntries(
          tool.parameters.map(p => [p.name, {
            type: p.type,
            description: p.description,
            ...(p.enum ? { enum: p.enum } : {}),
          }])
        ),
        required: tool.parameters.filter(p => p.required).map(p => p.name),
      },
    },
  }));
}

/**
 * Convert tools to Anthropic tool_use format.
 */
export function toAnthropicTools(tools: Tool[]) {
  return tools.map(tool => ({
    name: tool.name,
    description: tool.description,
    input_schema: {
      type: 'object',
      properties: Object.fromEntries(
        tool.parameters.map(p => [p.name, {
          type: p.type,
          description: p.description,
          ...(p.enum ? { enum: p.enum } : {}),
        }])
      ),
      required: tool.parameters.filter(p => p.required).map(p => p.name),
    },
  }));
}
