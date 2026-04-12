"""Tests for TokenBucketLimiter."""

import time
import threading

from api_to_tools.rate_limiter import TokenBucketLimiter, get_domain_limiter, NOOP_LIMITER


# ──────────────────────────────────────────────
# Basic acquire
# ──────────────────────────────────────────────

def test_acquire_returns_true():
    limiter = TokenBucketLimiter(rate=100.0)
    assert limiter.acquire() is True


def test_burst_allows_multiple_immediate():
    limiter = TokenBucketLimiter(rate=10.0, burst=5)
    results = [limiter.acquire(timeout=0.01) for _ in range(5)]
    assert all(results)


def test_acquire_blocks_after_burst():
    limiter = TokenBucketLimiter(rate=10.0, burst=2)
    # Consume burst
    limiter.acquire()
    limiter.acquire()
    # Third should timeout quickly
    result = limiter.acquire(timeout=0.01)
    assert result is False


def test_acquire_refills_over_time():
    limiter = TokenBucketLimiter(rate=100.0, burst=1)
    limiter.acquire()
    # After short wait, should have a new token
    time.sleep(0.02)
    assert limiter.acquire(timeout=0.01) is True


# ──────────────────────────────────────────────
# Rate enforcement
# ──────────────────────────────────────────────

def test_rate_limits_throughput():
    """20 RPS limiter should take ~0.5s for 10 requests beyond burst."""
    limiter = TokenBucketLimiter(rate=20.0, burst=1)
    start = time.monotonic()
    for _ in range(6):
        limiter.acquire()
    elapsed = time.monotonic() - start
    # 5 waits at 1/20s = 0.25s minimum
    assert elapsed >= 0.2


# ──────────────────────────────────────────────
# Thread safety
# ──────────────────────────────────────────────

def test_thread_safe():
    limiter = TokenBucketLimiter(rate=100.0, burst=10)
    results = []

    def worker():
        for _ in range(5):
            results.append(limiter.acquire(timeout=1.0))

    threads = [threading.Thread(target=worker) for _ in range(4)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=5.0)

    assert len(results) == 20
    assert all(results)


# ──────────────────────────────────────────────
# Context manager
# ──────────────────────────────────────────────

def test_context_manager():
    limiter = TokenBucketLimiter(rate=100.0)
    with limiter:
        pass  # should not raise


# ──────────────────────────────────────────────
# Domain limiter cache
# ──────────────────────────────────────────────

def test_get_domain_limiter_returns_same():
    a = get_domain_limiter("test-domain.com", 10.0)
    b = get_domain_limiter("test-domain.com", 10.0)
    assert a is b


def test_get_domain_limiter_different_domains():
    a = get_domain_limiter("a-unique.com", 10.0)
    b = get_domain_limiter("b-unique.com", 10.0)
    assert a is not b


# ──────────────────────────────────────────────
# No-op limiter
# ──────────────────────────────────────────────

def test_noop_limiter_never_blocks():
    for _ in range(100):
        assert NOOP_LIMITER.acquire() is True


def test_noop_context_manager():
    with NOOP_LIMITER:
        pass
