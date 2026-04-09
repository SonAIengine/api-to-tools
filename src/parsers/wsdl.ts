import soap from 'soap';
import type { SpecParser, Tool, ToolParameter } from '../types.js';

type WsdlDescription = Record<string, Record<string, Record<string, WsdlOperation>>>;

type WsdlOperation = {
  input: Record<string, string>;
  output: Record<string, string>;
};

function wsdlTypeToJsonType(wsdlType: string): string {
  const typeMap: Record<string, string> = {
    'xs:string': 'string', 'xsd:string': 'string', string: 'string',
    'xs:int': 'integer', 'xsd:int': 'integer', int: 'integer',
    'xs:integer': 'integer', 'xsd:integer': 'integer', integer: 'integer',
    'xs:long': 'integer', 'xsd:long': 'integer', long: 'integer',
    'xs:float': 'number', 'xsd:float': 'number', float: 'number',
    'xs:double': 'number', 'xsd:double': 'number', double: 'number',
    'xs:decimal': 'number', 'xsd:decimal': 'number', decimal: 'number',
    'xs:boolean': 'boolean', 'xsd:boolean': 'boolean', boolean: 'boolean',
    'xs:date': 'string', 'xsd:date': 'string', date: 'string',
    'xs:dateTime': 'string', 'xsd:dateTime': 'string', dateTime: 'string',
  };
  return typeMap[wsdlType] ?? 'string';
}

function extractParams(input: Record<string, string>): ToolParameter[] {
  return Object.entries(input).map(([name, type]) => ({
    name,
    type: wsdlTypeToJsonType(type),
    required: true,
    in: 'body' as const,
  }));
}

export const wsdlParser: SpecParser = {
  type: 'wsdl',

  async parse(input: string | object): Promise<Tool[]> {
    const url = typeof input === 'string' ? input : (input as { url: string }).url;
    const client = await soap.createClientAsync(url);
    const description = client.describe() as WsdlDescription;
    const tools: Tool[] = [];

    for (const [serviceName, ports] of Object.entries(description)) {
      for (const [portName, operations] of Object.entries(ports)) {
        for (const [operationName, operation] of Object.entries(operations)) {
          tools.push({
            name: operationName,
            description: `${serviceName}.${portName}.${operationName}`,
            parameters: extractParams(operation.input),
            endpoint: url,
            method: operationName,
            protocol: 'soap',
            responseFormat: 'xml',
            tags: [serviceName, portName],
            metadata: { serviceName, portName },
          });
        }
      }
    }

    return tools;
  },
};
