import {
  buildClientSchema,
  getIntrospectionQuery,
  type GraphQLField,
  type GraphQLArgument,
  type GraphQLType,
  type GraphQLSchema,
  type IntrospectionQuery,
} from 'graphql';
import type { SpecParser, Tool, ToolParameter } from '../types.js';

function unwrapType(type: GraphQLType): { typeName: string; required: boolean } {
  const str = type.toString();
  const required = str.endsWith('!');
  const typeName = str.replace(/[[\]!]/g, '');
  return { typeName, required };
}

function argToParam(arg: GraphQLArgument): ToolParameter {
  const { typeName, required } = unwrapType(arg.type);
  return {
    name: arg.name,
    type: typeName,
    required,
    description: arg.description ?? undefined,
    ...(arg.defaultValue !== undefined ? { default: arg.defaultValue } : {}),
  };
}

function fieldToTool(field: GraphQLField<unknown, unknown>, kind: 'query' | 'mutation', endpoint: string): Tool {
  return {
    name: field.name,
    description: field.description ?? `${kind}: ${field.name}`,
    parameters: field.args.map(argToParam),
    endpoint,
    method: kind,
    protocol: 'graphql',
    responseFormat: 'json',
    tags: [kind],
  };
}

async function fetchSchema(url: string): Promise<GraphQLSchema> {
  const res = await fetch(url, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ query: getIntrospectionQuery() }),
  });
  const json = (await res.json()) as { data: IntrospectionQuery };
  return buildClientSchema(json.data);
}

export const graphqlParser: SpecParser = {
  type: 'graphql',

  async parse(input: string | object): Promise<Tool[]> {
    let schema: GraphQLSchema;
    let endpoint: string;

    if (typeof input === 'string') {
      // If it's a URL, fetch introspection
      if (input.startsWith('http')) {
        schema = await fetchSchema(input);
        endpoint = input;
      } else {
        // Assume it's already an introspection result
        const data = JSON.parse(input) as { data: IntrospectionQuery };
        schema = buildClientSchema(data.data);
        endpoint = '';
      }
    } else {
      const data = input as { data: IntrospectionQuery };
      schema = buildClientSchema(data.data);
      endpoint = '';
    }

    const tools: Tool[] = [];

    const queryType = schema.getQueryType();
    if (queryType) {
      for (const field of Object.values(queryType.getFields())) {
        tools.push(fieldToTool(field, 'query', endpoint));
      }
    }

    const mutationType = schema.getMutationType();
    if (mutationType) {
      for (const field of Object.values(mutationType.getFields())) {
        tools.push(fieldToTool(field, 'mutation', endpoint));
      }
    }

    return tools;
  },
};
