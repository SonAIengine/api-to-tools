"""Tests for TTLCache."""

import time
import threading

from api_to_tools.cache import TTLCache


# ──────────────────────────────────────────────
# Basic get/set
# ──────────────────────────────────────────────

def test_set_and_get():
    cache = TTLCache()
    cache.set("key", "value", ttl=60)
    assert cache.get("key") == "value"


def test_get_missing():
    cache = TTLCache()
    assert cache.get("nonexistent") is None


def test_overwrite():
    cache = TTLCache()
    cache.set("key", "old", ttl=60)
    cache.set("key", "new", ttl=60)
    assert cache.get("key") == "new"


# ──────────────────────────────────────────────
# TTL expiry
# ──────────────────────────────────────────────

def test_expired_returns_none():
    cache = TTLCache()
    cache.set("key", "value", ttl=0.01)
    time.sleep(0.02)
    assert cache.get("key") is None


def test_not_expired():
    cache = TTLCache()
    cache.set("key", "value", ttl=60)
    assert cache.get("key") == "value"


# ──────────────────────────────────────────────
# Invalidate / clear
# ──────────────────────────────────────────────

def test_invalidate_existing():
    cache = TTLCache()
    cache.set("key", "value", ttl=60)
    assert cache.invalidate("key") is True
    assert cache.get("key") is None


def test_invalidate_missing():
    cache = TTLCache()
    assert cache.invalidate("nonexistent") is False


def test_clear():
    cache = TTLCache()
    cache.set("a", 1, ttl=60)
    cache.set("b", 2, ttl=60)
    cache.clear()
    assert cache.get("a") is None
    assert cache.get("b") is None


# ──────────────────────────────────────────────
# Size
# ──────────────────────────────────────────────

def test_size():
    cache = TTLCache()
    assert cache.size == 0
    cache.set("a", 1, ttl=60)
    cache.set("b", 2, ttl=60)
    assert cache.size == 2


# ──────────────────────────────────────────────
# Complex values
# ──────────────────────────────────────────────

def test_cache_list():
    cache = TTLCache()
    data = [{"name": "tool1"}, {"name": "tool2"}]
    cache.set("tools", data, ttl=60)
    assert cache.get("tools") == data


# ──────────────────────────────────────────────
# Thread safety
# ──────────────────────────────────────────────

def test_concurrent_access():
    cache = TTLCache()
    errors = []

    def writer(i):
        try:
            for j in range(50):
                cache.set(f"key-{i}-{j}", j, ttl=60)
        except Exception as e:
            errors.append(e)

    def reader():
        try:
            for _ in range(100):
                cache.get("key-0-0")
        except Exception as e:
            errors.append(e)

    threads = [threading.Thread(target=writer, args=(i,)) for i in range(4)]
    threads += [threading.Thread(target=reader) for _ in range(4)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=5.0)
    assert errors == []
