import protobuf from 'protobufjs';
import type { SpecParser, Tool, ToolParameter } from '../types.js';

function protoTypeToJsonType(protoType: string): string {
  const typeMap: Record<string, string> = {
    double: 'number', float: 'number',
    int32: 'integer', int64: 'integer',
    uint32: 'integer', uint64: 'integer',
    sint32: 'integer', sint64: 'integer',
    fixed32: 'integer', fixed64: 'integer',
    sfixed32: 'integer', sfixed64: 'integer',
    bool: 'boolean',
    string: 'string',
    bytes: 'string',
  };
  return typeMap[protoType] ?? 'object';
}

function messageToParams(root: protobuf.Root, typeName: string): ToolParameter[] {
  try {
    const messageType = root.lookupType(typeName);
    return Object.entries(messageType.fields).map(([name, field]) => ({
      name,
      type: protoTypeToJsonType(field.type),
      required: field.required ?? false,
      description: field.comment ?? undefined,
      ...((field as unknown as { rule?: string }).rule === 'repeated' ? { type: 'array' } : {}),
    }));
  } catch {
    return [];
  }
}

export const grpcParser: SpecParser = {
  type: 'grpc',

  async parse(input: string | object): Promise<Tool[]> {
    let root: protobuf.Root;

    if (typeof input === 'string') {
      if (input.endsWith('.proto') || input.startsWith('/') || input.startsWith('.')) {
        // File path
        root = await protobuf.load(input);
      } else {
        // Raw proto content
        root = protobuf.parse(input).root;
      }
    } else {
      // Already parsed protobuf root or JSON descriptor
      root = protobuf.Root.fromJSON(input as protobuf.INamespace);
    }

    const tools: Tool[] = [];

    // Walk all namespaces to find services
    function walkNamespace(ns: protobuf.NamespaceBase, prefix = '') {
      for (const nested of ns.nestedArray) {
        if (nested instanceof protobuf.Service) {
          const service = nested as protobuf.Service;
          for (const method of service.methodsArray) {
            const fullName = prefix ? `${prefix}.${service.name}.${method.name}` : `${service.name}.${method.name}`;
            tools.push({
              name: `${service.name}_${method.name}`,
              description: method.comment ?? `gRPC: ${fullName}`,
              parameters: messageToParams(root, method.requestType),
              endpoint: fullName,
              method: method.name,
              protocol: 'grpc',
              responseFormat: 'protobuf',
              tags: [service.name],
              metadata: {
                serviceName: service.name,
                requestType: method.requestType,
                responseType: method.responseType,
                requestStream: method.requestStream ?? false,
                responseStream: method.responseStream ?? false,
              },
            });
          }
        } else if (nested instanceof protobuf.Namespace) {
          walkNamespace(nested, prefix ? `${prefix}.${nested.name}` : nested.name);
        }
      }
    }

    walkNamespace(root);
    return tools;
  },
};
