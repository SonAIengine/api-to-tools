import type { DetectionResult, DiscoverOptions, SpecType } from '../types.js';

const WELL_KNOWN_PATHS: Record<SpecType, string[]> = {
  openapi: [
    '/openapi.json', '/openapi.yaml', '/openapi/v3.json',
    '/swagger.json', '/swagger.yaml',
    '/api-docs', '/v2/api-docs', '/v3/api-docs',
    '/.well-known/openapi',
    '/docs/openapi.json', '/docs/swagger.json',
    '/swagger/v1/swagger.json', '/swagger/v2/swagger.json',
    '/api/swagger.json', '/api/openapi.json',
    '/spec.json', '/api/spec.json',
    '/api-docs.json', '/api/api-docs',
  ],
  wsdl: ['?wsdl', '?WSDL', '/ws?wsdl', '/services?wsdl'],
  graphql: ['/graphql', '/.well-known/graphql'],
  grpc: [], // gRPC uses reflection, not HTTP paths
  asyncapi: ['/asyncapi.json', '/asyncapi.yaml'],
  jsonrpc: ['/rpc', '/jsonrpc'],
};

const GRAPHQL_INTROSPECTION_QUERY = `{"query":"{ __schema { types { name } } }"}`;

/** Detect spec type from response content */
function detectFromContent(content: string, contentType?: string): SpecType | null {
  // JSON-based detection
  if (contentType?.includes('json') || content.trimStart().startsWith('{')) {
    try {
      const json = JSON.parse(content);
      if (json.openapi || json.swagger) return 'openapi';
      if (json.asyncapi) return 'asyncapi';
      if (json.data?.__schema) return 'graphql';
      if (json.jsonrpc || json.method) return 'jsonrpc';
    } catch { /* not valid JSON */ }
  }

  // XML-based detection
  if (contentType?.includes('xml') || content.trimStart().startsWith('<')) {
    if (content.includes('<definitions') || content.includes('<wsdl:definitions')) return 'wsdl';
    if (content.includes('<description') && content.includes('wsdl')) return 'wsdl';
    if (content.includes('<application') && content.includes('wadl')) return 'openapi'; // treat WADL as REST
  }

  // YAML-based detection
  if (content.includes('openapi:') || content.includes('swagger:')) return 'openapi';
  if (content.includes('#%RAML')) return 'openapi'; // RAML -> normalize later
  if (content.includes('asyncapi:')) return 'asyncapi';

  return null;
}

/** Extract spec URL from Swagger UI / Redoc HTML pages */
async function extractSpecUrlFromHtml(html: string, baseUrl: string, timeout: number): Promise<string | null> {
  // Swagger UI: url: "..." or configUrl
  const swaggerUrlMatch = html.match(/url:\s*["']([^"']+)["']/);
  if (swaggerUrlMatch) return new URL(swaggerUrlMatch[1], baseUrl).href;

  // Redoc: spec-url="..."
  const redocMatch = html.match(/spec-url=["']([^"']+)["']/);
  if (redocMatch) return new URL(redocMatch[1], baseUrl).href;

  // Link tag: <link rel="api-definition" href="...">
  const linkMatch = html.match(/<link[^>]+rel=["']api-definition["'][^>]+href=["']([^"']+)["']/);
  if (linkMatch) return new URL(linkMatch[1], baseUrl).href;

  // Swagger UI initializer JS file: <script src="./swagger-initializer.js">
  // Only fetch small config/initializer scripts, not large bundles
  const scriptMatches = html.matchAll(/<script[^>]+src=["']([^"']*(?:initializer|config)[^"']*)["']/gi);
  for (const match of scriptMatches) {
    try {
      const jsUrl = new URL(match[1], baseUrl).href;
      const controller = new AbortController();
      const timer = setTimeout(() => controller.abort(), timeout);
      const jsRes = await fetch(jsUrl, { signal: controller.signal });
      clearTimeout(timer);
      if (jsRes.ok) {
        const jsContent = await jsRes.text();
        // Match url: "https://..." or url: "/api/..." but not url: "/"
        const urlInJs = jsContent.match(/url:\s*["'](https?:\/\/[^"']+|\/[^"'/][^"']*)["']/);
        if (urlInJs) return new URL(urlInJs[1], baseUrl).href;

        // Match variable assignments like: const defaultDefinitionUrl = "https://..."
        // or: var apiUrl = "https://..."
        const varUrlMatch = jsContent.match(/(?:const|let|var)\s+\w*(?:url|definition|spec|swagger|openapi)\w*\s*=\s*["'](https?:\/\/[^"']+\.json[^"']*)["']/i);
        if (varUrlMatch) return new URL(varUrlMatch[1], baseUrl).href;
      }
    } catch { /* continue */ }
  }

  return null;
}

/** Probe a single URL and return detection result if found */
async function probe(url: string, timeout: number): Promise<DetectionResult | null> {
  try {
    const controller = new AbortController();
    const timer = setTimeout(() => controller.abort(), timeout);
    const res = await fetch(url, {
      signal: controller.signal,
      headers: { Accept: 'application/json, application/xml, text/yaml, */*' },
      redirect: 'follow',
    });
    clearTimeout(timer);

    if (!res.ok) return null;

    const contentType = res.headers.get('content-type') ?? '';
    const content = await res.text();
    const type = detectFromContent(content, contentType);

    if (type) return { type, specUrl: url, rawContent: content, contentType };

    // If HTML, try to extract spec URL from Swagger UI / Redoc
    if (contentType.includes('html')) {
      const specUrl = await extractSpecUrlFromHtml(content, url, timeout);
      if (specUrl) return probe(specUrl, timeout);
    }

    return null;
  } catch {
    return null;
  }
}

/** Try GraphQL introspection */
async function probeGraphQL(baseUrl: string, timeout: number): Promise<DetectionResult | null> {
  // Try the base URL itself first, then well-known paths
  const urlsToTry = [baseUrl, ...WELL_KNOWN_PATHS.graphql.map(p => new URL(p, baseUrl).href)];
  const uniqueUrls = [...new Set(urlsToTry)];
  for (const url of uniqueUrls) {
    try {
      const controller = new AbortController();
      const timer = setTimeout(() => controller.abort(), timeout);
      const res = await fetch(url, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: GRAPHQL_INTROSPECTION_QUERY,
        signal: controller.signal,
      });
      clearTimeout(timer);

      if (res.ok) {
        const content = await res.text();
        if (content.includes('__schema')) {
          // Don't pass rawContent - parser needs to run full introspection
          return { type: 'graphql', specUrl: url };
        }
      }
    } catch { /* continue */ }
  }
  return null;
}

/**
 * Discover API spec from a URL.
 * Tries direct detection, then probes well-known paths.
 */
export async function detect(url: string, options: DiscoverOptions = {}): Promise<DetectionResult> {
  const timeout = options.timeout ?? 10_000;

  // 1. If URL looks like a GraphQL endpoint, try introspection first
  if (url.includes('graphql') || url.endsWith('/gql')) {
    const gql = await probeGraphQL(url.replace(/\/$/, ''), timeout);
    if (gql) return gql;
  }

  // 2. Try the URL directly (GET-based specs)
  const direct = await probe(url, timeout);
  if (direct) return direct;

  // 2. If it looks like it might have a query param already (?wsdl), skip probing
  const baseUrl = url.replace(/\/$/, '');

  // 3. Probe well-known paths (parallel by spec type)
  if (options.probePaths !== false) {
    const allPaths = Object.entries(WELL_KNOWN_PATHS).flatMap(([, paths]) =>
      paths.map(p => p.startsWith('?') ? `${baseUrl}${p}` : new URL(p, baseUrl).href)
    );

    // Batch probe in parallel (max 6 concurrent)
    const batchSize = 6;
    for (let i = 0; i < allPaths.length; i += batchSize) {
      const batch = allPaths.slice(i, i + batchSize);
      const results = await Promise.all(batch.map(p => probe(p, timeout)));
      const found = results.find(r => r !== null);
      if (found) return found;
    }

    // 4. Try GraphQL introspection (requires POST)
    const graphql = await probeGraphQL(baseUrl, timeout);
    if (graphql) return graphql;
  }

  throw new Error(`Could not detect API spec at ${url}. Try providing the direct spec URL.`);
}
