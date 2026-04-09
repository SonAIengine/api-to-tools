import soapLib from 'soap';
import type { Tool, ToolExecutor, ToolExecutionResult } from '../types.js';

// Cache SOAP clients by endpoint
const clientCache = new Map<string, Awaited<ReturnType<typeof soapLib.createClientAsync>>>();

async function getClient(wsdlUrl: string) {
  if (!clientCache.has(wsdlUrl)) {
    clientCache.set(wsdlUrl, await soapLib.createClientAsync(wsdlUrl));
  }
  return clientCache.get(wsdlUrl)!;
}

export const soapExecutor: ToolExecutor = {
  protocol: 'soap',

  async execute(tool: Tool, args: Record<string, unknown>): Promise<ToolExecutionResult> {
    const client = await getClient(tool.endpoint);
    const methodName = tool.method;

    // soap library exposes methods as client[methodName]Async
    const asyncMethod = `${methodName}Async`;
    if (typeof client[asyncMethod] !== 'function') {
      throw new Error(`SOAP method "${methodName}" not found on client`);
    }

    const [result, rawResponse, , rawRequest] = await (client[asyncMethod] as Function)(args);

    return {
      status: 200,
      data: result,
      raw: rawResponse,
      headers: { 'x-soap-request': rawRequest },
    };
  },
};
