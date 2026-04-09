import {
  buildClientSchema,
  getIntrospectionQuery,
  isObjectType,
  isListType,
  isNonNullType,
  isScalarType,
  isEnumType,
  type GraphQLField,
  type GraphQLArgument,
  type GraphQLType,
  type GraphQLSchema,
  type GraphQLObjectType,
  type IntrospectionQuery,
} from 'graphql';
import type { SpecParser, Tool, ToolParameter } from '../types.js';

function unwrapType(type: GraphQLType): { typeName: string; required: boolean; namedType: GraphQLType } {
  let current = type;
  const required = isNonNullType(current);
  if (isNonNullType(current)) current = current.ofType;
  if (isListType(current)) current = current.ofType;
  if (isNonNullType(current)) current = current.ofType;
  return { typeName: type.toString().replace(/[[\]!]/g, ''), required, namedType: current };
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

/** Build a selection set string for a GraphQL type (depth-limited) */
function buildSelectionSet(type: GraphQLType, depth = 0, maxDepth = 2): string | null {
  let current = type;
  if (isNonNullType(current)) current = current.ofType;
  if (isListType(current)) current = current.ofType;
  if (isNonNullType(current)) current = current.ofType;

  if (isScalarType(current) || isEnumType(current)) return null;

  if (!isObjectType(current) || depth >= maxDepth) return null;

  const objType = current as GraphQLObjectType;
  const fields = objType.getFields();
  const selections: string[] = [];

  for (const [name, field] of Object.entries(fields)) {
    // Skip fields that require arguments
    if (field.args.length > 0) continue;

    const sub = buildSelectionSet(field.type, depth + 1, maxDepth);
    if (sub) {
      selections.push(`${name} ${sub}`);
    } else {
      // Only include scalar/enum fields
      let ft = field.type;
      if (isNonNullType(ft)) ft = ft.ofType;
      if (isListType(ft)) ft = ft.ofType;
      if (isNonNullType(ft)) ft = ft.ofType;
      if (isScalarType(ft) || isEnumType(ft)) {
        selections.push(name);
      }
    }
  }

  if (selections.length === 0) return null;
  return `{ ${selections.join(' ')} }`;
}

function fieldToTool(
  field: GraphQLField<unknown, unknown>,
  kind: 'query' | 'mutation',
  endpoint: string,
): Tool {
  const selectionSet = buildSelectionSet(field.type);

  return {
    name: field.name,
    description: field.description ?? `${kind}: ${field.name}`,
    parameters: field.args.map(argToParam),
    endpoint,
    method: kind,
    protocol: 'graphql',
    responseFormat: 'json',
    tags: [kind],
    metadata: {
      returnType: field.type.toString(),
      ...(selectionSet ? { selectionSet } : {}),
    },
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
      if (input.startsWith('http')) {
        schema = await fetchSchema(input);
        endpoint = input;
      } else {
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
