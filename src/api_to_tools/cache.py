"""TTL-based in-memory cache for discover() results."""

from __future__ import annotations

import threading
import time
from typing import Any


class TTLCache:
    """Thread-safe in-memory cache with per-entry TTL.

    Usage:
        cache = TTLCache()
        cache.set("key", value, ttl=300)
        hit = cache.get("key")          # returns value or None
        cache.invalidate("key")         # manual removal
        cache.clear()                   # remove all
    """

    def __init__(self):
        self._store: dict[str, tuple[Any, float]] = {}
        self._lock = threading.Lock()

    def get(self, key: str) -> Any | None:
        """Get a cached value, returning None if missing or expired."""
        with self._lock:
            entry = self._store.get(key)
            if entry is None:
                return None
            value, expires_at = entry
            if time.monotonic() > expires_at:
                del self._store[key]
                return None
            return value

    def set(self, key: str, value: Any, ttl: float) -> None:
        """Store a value with a TTL in seconds."""
        with self._lock:
            self._store[key] = (value, time.monotonic() + ttl)

    def invalidate(self, key: str) -> bool:
        """Remove a specific entry. Returns True if it existed."""
        with self._lock:
            return self._store.pop(key, None) is not None

    def clear(self) -> None:
        """Remove all entries."""
        with self._lock:
            self._store.clear()

    @property
    def size(self) -> int:
        """Number of entries (including possibly expired ones)."""
        return len(self._store)


# Module-level singleton for discover() caching
_discover_cache = TTLCache()


def get_discover_cache() -> TTLCache:
    """Get the shared discover() result cache."""
    return _discover_cache
