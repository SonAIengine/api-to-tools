"""SOAP executor using zeep with authentication support."""

from __future__ import annotations

import json
from threading import Lock

from api_to_tools._logging import get_logger
from api_to_tools.types import AuthConfig, ExecutionResult, Tool

log = get_logger("soap")

# Cache: (wsdl_url, auth_cache_key) -> ZeepClient
_clients: dict[tuple[str, str], object] = {}
_clients_lock = Lock()


def _auth_key(auth: AuthConfig | None) -> str:
    """Build a stable cache key from auth config (values, not id)."""
    if auth is None:
        return ""
    parts = (
        auth.type, auth.username, auth.password, auth.token,
        auth.key, auth.value,
        tuple(sorted((auth.cookies or {}).items())),
        tuple(sorted((auth.headers or {}).items())),
        auth.verify_ssl,
    )
    return str(hash(parts))


def _build_transport(auth: AuthConfig | None):
    """Build a zeep Transport with auth/session applied.

    zeep uses requests.Session under the hood — we configure it based on auth.
    """
    import requests
    from zeep.transports import Transport

    session = requests.Session()

    if auth is None:
        return Transport(session=session)

    # TLS verification
    session.verify = auth.verify_ssl

    # Resolve auth (cookie login, OAuth2 token exchange, etc.)
    from api_to_tools.auth import build_auth_cookies, build_auth_headers, resolve_auth

    resolved = resolve_auth(auth)

    # Basic auth → requests-native
    if resolved.type == "basic" and resolved.username:
        session.auth = (resolved.username, resolved.password or "")
    else:
        # Bearer, API key, custom headers — just merge into session headers
        session.headers.update(build_auth_headers(resolved))

    # Cookies (from cookie auth type or post-login)
    for k, v in build_auth_cookies(resolved).items():
        session.cookies.set(k, v)

    return Transport(session=session)


def _get_client(wsdl_url: str, auth: AuthConfig | None):
    """Get or create a cached zeep Client for (wsdl_url, auth)."""
    from zeep import Client as ZeepClient

    key = (wsdl_url, _auth_key(auth))
    with _clients_lock:
        if key in _clients:
            return _clients[key]
        transport = _build_transport(auth)
        client = ZeepClient(wsdl_url, transport=transport)
        _clients[key] = client
        return client


def execute_soap(tool: Tool, args: dict, *, auth: AuthConfig | None = None) -> ExecutionResult:
    """Execute a SOAP call with optional authentication.

    Auth types supported:
    - basic → HTTP Basic via requests Session
    - bearer, api_key, custom → header injection into Session
    - cookie → post-login cookies from form flow
    - oauth2_client → token exchange, then bearer
    """
    try:
        client = _get_client(tool.endpoint, auth)
        service = client.service
        method = getattr(service, tool.method, None)
        if method is None:
            return ExecutionResult(
                status=404,
                data={"error": f"SOAP method '{tool.method}' not found on service"},
            )

        result = method(**args)
        data = json.loads(json.dumps(result, default=str)) if result is not None else None

        return ExecutionResult(
            status=200,
            data=data,
            raw=str(result),
        )
    except Exception as e:
        log.error("SOAP call failed: %s", e)
        return ExecutionResult(
            status=500,
            data={"error": str(e), "type": type(e).__name__},
        )
