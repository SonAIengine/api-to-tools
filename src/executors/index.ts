import type { Protocol, ToolExecutor } from '../types.js';
import { restExecutor } from './rest.js';
import { soapExecutor } from './soap.js';
import { graphqlExecutor } from './graphql.js';

const executors: Record<Protocol, ToolExecutor | null> = {
  rest: restExecutor,
  soap: soapExecutor,
  graphql: graphqlExecutor,
  grpc: null,     // TODO
  jsonrpc: null,  // TODO
  async: null,    // TODO
};

export function getExecutor(protocol: Protocol): ToolExecutor {
  const executor = executors[protocol];
  if (!executor) throw new Error(`Executor for "${protocol}" is not yet implemented`);
  return executor;
}

export { restExecutor, soapExecutor, graphqlExecutor };
