# Core API

## `discover(url, *, auth=None, cache_ttl=None, **kwargs)`

Discover and parse API spec from a URL into tools.

**Parameters:**

- `url` — API spec URL, website URL, or `.har` file path
- `auth` — `AuthConfig` for protected APIs
- `cache_ttl` — Cache results for N seconds (None = no cache)
- `timeout`, `probe_paths`, `scan_js`, `crawl`, `cdp` — detector options
- `tags`, `methods`, `path_filter`, `base_url` — result filters

**Returns:** `list[Tool]`

## `discover_all(sources, *, auth=None, cache_ttl=None, **kwargs)`

Discover from multiple sources and merge.

**Parameters:**

- `sources` — List of URLs/file paths
- Other args same as `discover()`

**Returns:** `list[Tool]` (deduplicated)

## `execute(tool, args, *, auth=None)`

Execute a tool with given arguments.

**Parameters:**

- `tool` — `Tool` object from `discover()`
- `args` — `dict` of parameter values
- `auth` — `AuthConfig` (optional, falls back to tool.metadata)

**Returns:** `ExecutionResult`

## `to_tools(detection, *, auth=None, **kwargs)`

Parse a `DetectionResult` into tools (low-level).

**Returns:** `list[Tool]`
