import type { SpecParser, SpecType } from '../types.js';
import { openapiParser } from './openapi.js';
import { wsdlParser } from './wsdl.js';
import { graphqlParser } from './graphql.js';
import { grpcParser } from './grpc.js';
import { asyncapiParser } from './asyncapi.js';

const parsers: Record<SpecType, SpecParser | null> = {
  openapi: openapiParser,
  wsdl: wsdlParser,
  graphql: graphqlParser,
  grpc: grpcParser,
  asyncapi: asyncapiParser,
  jsonrpc: null, // TODO: jsonrpc parser
};

export function getParser(type: SpecType): SpecParser {
  const parser = parsers[type];
  if (!parser) throw new Error(`Parser for "${type}" is not yet implemented`);
  return parser;
}

export { openapiParser, wsdlParser, graphqlParser, grpcParser, asyncapiParser };
