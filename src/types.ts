/** Supported API specification formats */
export type SpecType = 'openapi' | 'wsdl' | 'graphql' | 'grpc' | 'asyncapi' | 'jsonrpc';

/** Supported communication protocols */
export type Protocol = 'rest' | 'soap' | 'graphql' | 'grpc' | 'jsonrpc' | 'async';

/** Response format of the API */
export type ResponseFormat = 'json' | 'xml' | 'protobuf' | 'binary';

/** Parameter location in HTTP request */
export type ParameterIn = 'path' | 'query' | 'header' | 'body' | 'cookie';

/** A single parameter of a tool */
export interface ToolParameter {
  name: string;
  type: string;
  required: boolean;
  in?: ParameterIn;
  description?: string;
  enum?: string[];
  default?: unknown;
  schema?: Record<string, unknown>;
}

/** Unified tool definition - the core output of this library */
export interface Tool {
  name: string;
  description: string;
  parameters: ToolParameter[];
  endpoint: string;
  method: string;
  protocol: Protocol;
  responseFormat: ResponseFormat;
  tags?: string[];
  metadata?: Record<string, unknown>;
}

/** Result of spec detection */
export interface DetectionResult {
  type: SpecType;
  specUrl: string;
  rawContent?: string;
  contentType?: string;
}

/** Parser interface - each format implements this */
export interface SpecParser {
  type: SpecType;
  parse(input: string | object, sourceUrl?: string): Promise<Tool[]>;
}

/** Executor interface - handles actual API calls */
export interface ToolExecutor {
  protocol: Protocol;
  execute(tool: Tool, args: Record<string, unknown>): Promise<ToolExecutionResult>;
}

/** Result of executing a tool */
export interface ToolExecutionResult {
  status: number;
  data: unknown;
  headers?: Record<string, string>;
  raw?: string;
}

/** Options for the discover function */
export interface DiscoverOptions {
  timeout?: number;
  probePaths?: boolean;
  followRedirects?: boolean;
}

/** Options for the toTools function */
export interface ToToolsOptions {
  /** Filter tools by tag */
  tags?: string[];
  /** Filter tools by HTTP method */
  methods?: string[];
  /** Include only paths matching this pattern */
  pathFilter?: RegExp;
  /** Base URL override (for specs without servers) */
  baseUrl?: string;
}
