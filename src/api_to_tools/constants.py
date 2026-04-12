"""Central configuration constants used across the library."""

from __future__ import annotations

# ──────────────────────────────────────────────
# Timeouts (seconds)
# ──────────────────────────────────────────────

DEFAULT_HTTP_TIMEOUT = 10.0
DEFAULT_SPEC_FETCH_TIMEOUT = 30.0
DEFAULT_CRAWL_TIMEOUT = 30.0
DEFAULT_BROWSER_WAIT = 2.5
DEFAULT_NETWORK_IDLE_TIMEOUT = 10.0
DEFAULT_AUTH_TIMEOUT = 15.0
DEFAULT_PROBE_TIMEOUT = 4.0
DEFAULT_EXECUTOR_TIMEOUT = 30.0
DEFAULT_JS_FETCH_TIMEOUT = 8.0

# ──────────────────────────────────────────────
# Rate limiting
# ──────────────────────────────────────────────

# Max requests per second for discovery probing (swagger_discovery, detector)
DEFAULT_PROBE_RPS = 20.0
# Max requests per second for API execution
DEFAULT_EXECUTOR_RPS = 10.0

# ──────────────────────────────────────────────
# HTTP methods
# ──────────────────────────────────────────────

SAFE_HTTP_METHODS = frozenset({"GET", "HEAD", "OPTIONS"})
ALL_HTTP_METHODS = frozenset({"GET", "POST", "PUT", "PATCH", "DELETE", "HEAD", "OPTIONS"})

# ──────────────────────────────────────────────
# URL classification
# ──────────────────────────────────────────────

STATIC_FILE_EXTENSIONS = frozenset({
    ".js", ".css", ".png", ".jpg", ".jpeg", ".gif", ".svg",
    ".ico", ".woff", ".woff2", ".ttf", ".map", ".html",
    ".mp4", ".webp", ".avif",
})

# Path segments commonly used as prefixes (excluded from tag extraction)
COMMON_PATH_PREFIXES = frozenset({
    "api", "bo", "v1", "v2", "v3", "v4", "rest", "admin", "app", "public",
})

# URL path markers that hint the request is an API call
API_PATH_MARKERS = ("/api/", "/v1/", "/v2/", "/v3/", "/rest/", "/graphql", "/rpc/")

# ──────────────────────────────────────────────
# Authentication / mutation keywords
# ──────────────────────────────────────────────

AUTH_KEYWORDS = frozenset({
    "login", "signin", "sign-in", "auth", "token", "refresh", "logout", "signout",
})

# Last-segment keywords that indicate a read-only operation (safe even if POST)
READ_KEYWORDS = frozenset({
    "get", "find", "list", "search", "query", "check", "has", "is", "fetch",
    "load", "retrieve", "view", "show", "count", "exist", "lookup", "select",
    "read", "info", "detail", "status",
})

# Keywords that strongly indicate a destructive / mutating operation
MUTATION_KEYWORDS = frozenset({
    "delete", "remove", "destroy", "drop", "erase",
    "create", "add", "insert", "regist", "new",
    "update", "modify", "edit", "change", "set", "put",
    "save", "upsert", "upload", "import",
    "send", "publish", "submit", "issue", "execute", "run",
    "approve", "reject", "cancel",
})

# ──────────────────────────────────────────────
# Nexacro platform signatures
# ──────────────────────────────────────────────

NEXACRO_URL_PATTERNS = ("/nexa/", "/nexacro/", "/nex/", ".lotte", ".do")

NEXACRO_HTML_SIGNATURES = (
    "nexacro", "nexaparametermap", "nexacromodel",
    "nexacro.js", "nexacro14", "nexacro17", "nexacro.css",
    "nexa/common", "/nexa/", ".lotte",
)

# ──────────────────────────────────────────────
# Well-known spec paths (by type)
# ──────────────────────────────────────────────

WELL_KNOWN_PATHS = {
    "openapi": [
        "/openapi.json", "/openapi.yaml", "/openapi/v3.json",
        "/swagger.json", "/swagger.yaml",
        "/api-docs", "/v2/api-docs", "/v3/api-docs",
        "/.well-known/openapi",
        "/docs/openapi.json", "/docs/swagger.json",
        "/swagger/v1/swagger.json", "/swagger/v2/swagger.json",
        "/api/swagger.json", "/api/openapi.json",
        "/spec.json", "/api/spec.json",
        "/api-docs.json", "/api/api-docs",
    ],
    "wsdl": ["?wsdl", "?WSDL", "/ws?wsdl", "/services?wsdl"],
    "graphql": ["/graphql", "/.well-known/graphql"],
    "grpc": [],
    "asyncapi": ["/asyncapi.json", "/asyncapi.yaml"],
    "jsonrpc": ["/rpc", "/jsonrpc"],
}

# Swagger/OpenAPI path suffixes to probe after a prefix
SWAGGER_PATH_SUFFIXES = (
    "/api-docs",
    "/api-docs/swagger-config",
    "/v3/api-docs",
    "/v2/api-docs",
    "/swagger.json",
    "/openapi.json",
    "/swagger-resources",
    "/swagger-ui/index.html",
    "/doc.html",
)
