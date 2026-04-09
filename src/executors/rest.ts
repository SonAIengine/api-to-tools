import { XMLParser } from 'fast-xml-parser';
import type { Tool, ToolExecutor, ToolExecutionResult } from '../types.js';

const xmlParser = new XMLParser({ ignoreAttributes: false, attributeNamePrefix: '@_' });

function buildUrl(endpoint: string, tool: Tool, args: Record<string, unknown>): string {
  let url = endpoint;

  // Replace path parameters
  for (const param of tool.parameters) {
    if (param.in === 'path' && args[param.name] !== undefined) {
      url = url.replace(`{${param.name}}`, encodeURIComponent(String(args[param.name])));
    }
  }

  // Add query parameters
  const queryParams = tool.parameters.filter(p => p.in === 'query');
  const searchParams = new URLSearchParams();
  for (const param of queryParams) {
    if (args[param.name] !== undefined) {
      searchParams.set(param.name, String(args[param.name]));
    }
  }
  const qs = searchParams.toString();
  if (qs) url += `?${qs}`;

  return url;
}

function buildBody(tool: Tool, args: Record<string, unknown>): object | undefined {
  const bodyParams = tool.parameters.filter(p => p.in === 'body');
  if (bodyParams.length === 0) return undefined;

  // If there's a single "body" param, use it directly
  if (bodyParams.length === 1 && bodyParams[0].name === 'body') {
    return args.body as object;
  }

  // Otherwise, collect all body params into an object
  const body: Record<string, unknown> = {};
  for (const param of bodyParams) {
    if (args[param.name] !== undefined) {
      body[param.name] = args[param.name];
    }
  }
  return body;
}

function buildHeaders(tool: Tool, args: Record<string, unknown>): Record<string, string> {
  const headers: Record<string, string> = {};

  for (const param of tool.parameters) {
    if (param.in === 'header' && args[param.name] !== undefined) {
      headers[param.name] = String(args[param.name]);
    }
  }

  if (['POST', 'PUT', 'PATCH'].includes(tool.method)) {
    headers['Content-Type'] ??= 'application/json';
  }
  headers['Accept'] ??= 'application/json';

  return headers;
}

export const restExecutor: ToolExecutor = {
  protocol: 'rest',

  async execute(tool: Tool, args: Record<string, unknown>): Promise<ToolExecutionResult> {
    const url = buildUrl(tool.endpoint, tool, args);
    const body = buildBody(tool, args);
    const headers = buildHeaders(tool, args);

    const res = await fetch(url, {
      method: tool.method,
      headers,
      ...(body ? { body: JSON.stringify(body) } : {}),
    });

    const raw = await res.text();
    const responseHeaders: Record<string, string> = {};
    res.headers.forEach((value, key) => { responseHeaders[key] = value; });

    let data: unknown;
    const contentType = res.headers.get('content-type') ?? '';
    if (contentType.includes('xml')) {
      data = xmlParser.parse(raw);
    } else if (contentType.includes('json')) {
      try { data = JSON.parse(raw); } catch { data = raw; }
    } else {
      try { data = JSON.parse(raw); } catch { data = raw; }
    }

    return { status: res.status, data, headers: responseHeaders, raw };
  },
};
