import SwaggerParser from '@apidevtools/swagger-parser';
import type { SpecParser, Tool, ToolParameter, ResponseFormat } from '../types.js';

type OpenAPISpec = {
  openapi?: string;
  swagger?: string;
  info?: { title?: string; version?: string };
  servers?: { url: string }[];
  host?: string;
  basePath?: string;
  schemes?: string[];
  paths?: Record<string, Record<string, OperationObject>>;
};

type OperationObject = {
  operationId?: string;
  summary?: string;
  description?: string;
  tags?: string[];
  parameters?: ParameterObject[];
  requestBody?: RequestBodyObject;
  responses?: Record<string, ResponseObject>;
};

type ParameterObject = {
  name: string;
  in: string;
  required?: boolean;
  description?: string;
  schema?: SchemaObject;
  type?: string; // Swagger 2.0
  enum?: string[];
};

type RequestBodyObject = {
  required?: boolean;
  content?: Record<string, { schema?: SchemaObject }>;
};

type ResponseObject = {
  description?: string;
  content?: Record<string, unknown>;
};

type SchemaObject = {
  type?: string;
  properties?: Record<string, SchemaObject>;
  required?: string[];
  enum?: string[];
  items?: SchemaObject;
  description?: string;
  default?: unknown;
};

function getBaseUrl(spec: OpenAPISpec, sourceUrl?: string): string {
  // OpenAPI 3.x
  if (spec.servers?.length) {
    const serverUrl = spec.servers[0].url;
    // Handle relative server URLs
    if (serverUrl.startsWith('/') && sourceUrl) {
      const origin = new URL(sourceUrl).origin;
      return `${origin}${serverUrl}`;
    }
    if (serverUrl.startsWith('http')) return serverUrl;
  }
  // Swagger 2.0
  if (spec.host) {
    const scheme = spec.schemes?.[0] ?? 'https';
    return `${scheme}://${spec.host}${spec.basePath ?? ''}`;
  }
  // Fallback: derive from source URL
  if (sourceUrl) return new URL(sourceUrl).origin;
  return '';
}

function detectResponseFormat(responses?: Record<string, ResponseObject>): ResponseFormat {
  if (!responses) return 'json';
  const successResponse = responses['200'] ?? responses['201'] ?? Object.values(responses)[0];
  if (!successResponse?.content) return 'json';
  const contentTypes = Object.keys(successResponse.content);
  if (contentTypes.some(ct => ct.includes('xml'))) return 'xml';
  return 'json';
}

function schemaToParams(schema: SchemaObject, requiredFields?: string[]): ToolParameter[] {
  if (!schema.properties) return [];
  return Object.entries(schema.properties).map(([name, prop]) => ({
    name,
    type: prop.type ?? 'string',
    required: requiredFields?.includes(name) ?? false,
    in: 'body' as const,
    description: prop.description,
    enum: prop.enum,
    default: prop.default,
    ...(prop.type === 'object' && prop.properties ? { schema: prop as Record<string, unknown> } : {}),
  }));
}

function extractParameters(operation: OperationObject): ToolParameter[] {
  const params: ToolParameter[] = [];

  // Path/query/header parameters
  if (operation.parameters) {
    for (const p of operation.parameters) {
      params.push({
        name: p.name,
        type: p.schema?.type ?? p.type ?? 'string',
        required: p.required ?? p.in === 'path',
        in: p.in as ToolParameter['in'],
        description: p.description,
        enum: p.schema?.enum ?? p.enum,
      });
    }
  }

  // Request body (OpenAPI 3.x)
  if (operation.requestBody?.content) {
    const content = operation.requestBody.content;
    const mediaType = content['application/json'] ?? content['application/xml'] ?? Object.values(content)[0];
    if (mediaType?.schema) {
      const bodyParams = schemaToParams(mediaType.schema, mediaType.schema.required);
      if (bodyParams.length > 0) {
        params.push(...bodyParams);
      } else if (mediaType.schema.type) {
        params.push({
          name: 'body',
          type: mediaType.schema.type,
          required: operation.requestBody.required ?? false,
          in: 'body',
          schema: mediaType.schema as Record<string, unknown>,
        });
      }
    }
  }

  return params;
}

function sanitizeName(method: string, path: string): string {
  return `${method}${path}`
    .replace(/[{}]/g, '')
    .replace(/[^a-zA-Z0-9]/g, '_')
    .replace(/_+/g, '_')
    .replace(/^_|_$/g, '');
}

export const openapiParser: SpecParser = {
  type: 'openapi',

  async parse(input: string | object, sourceUrl?: string): Promise<Tool[]> {
    let rawInput: string | object;
    if (typeof input === 'string') {
      // If it looks like a URL, pass directly; otherwise parse as JSON/YAML content
      if (input.startsWith('http://') || input.startsWith('https://')) {
        rawInput = input;
      } else {
        try { rawInput = JSON.parse(input); } catch { rawInput = input; }
      }
    } else {
      rawInput = input;
    }

    const spec = (await SwaggerParser.dereference(rawInput as never)) as OpenAPISpec;

    const baseUrl = getBaseUrl(spec, sourceUrl ?? (typeof rawInput === 'string' && rawInput.startsWith('http') ? rawInput : undefined));
    const tools: Tool[] = [];

    if (!spec.paths) return tools;

    for (const [path, methods] of Object.entries(spec.paths)) {
      for (const [method, operation] of Object.entries(methods)) {
        if (['get', 'post', 'put', 'patch', 'delete', 'head', 'options'].indexOf(method) === -1) continue;

        const op = operation as OperationObject;
        const name = op.operationId ?? sanitizeName(method, path);

        tools.push({
          name,
          description: op.summary ?? op.description ?? `${method.toUpperCase()} ${path}`,
          parameters: extractParameters(op),
          endpoint: `${baseUrl}${path}`,
          method: method.toUpperCase(),
          protocol: 'rest',
          responseFormat: detectResponseFormat(op.responses),
          tags: op.tags,
        });
      }
    }

    return tools;
  },
};
