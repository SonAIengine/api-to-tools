"""Thread-safe token bucket rate limiter."""

from __future__ import annotations

import threading
import time


class TokenBucketLimiter:
    """Token bucket rate limiter.

    Allows up to `rate` requests per second with a burst capacity of `burst`.
    Thread-safe — can be shared across ThreadPoolExecutor workers.

    Usage:
        limiter = TokenBucketLimiter(rate=20.0)
        limiter.acquire()   # blocks if over rate
        do_request()

        # Or as context manager:
        with limiter:
            do_request()
    """

    def __init__(self, rate: float, burst: int | None = None):
        """
        Args:
            rate: Maximum requests per second.
            burst: Maximum burst size. Defaults to max(1, int(rate)).
        """
        self.rate = rate
        self.burst = burst if burst is not None else max(1, int(rate))
        self._tokens = float(self.burst)
        self._last_refill = time.monotonic()
        self._lock = threading.Lock()

    def _refill(self) -> None:
        """Add tokens based on elapsed time since last refill."""
        now = time.monotonic()
        elapsed = now - self._last_refill
        self._tokens = min(self.burst, self._tokens + elapsed * self.rate)
        self._last_refill = now

    def acquire(self, timeout: float | None = None) -> bool:
        """Block until a token is available.

        Args:
            timeout: Max seconds to wait. None = wait forever.

        Returns:
            True if token acquired, False if timed out.
        """
        deadline = (time.monotonic() + timeout) if timeout is not None else None

        while True:
            with self._lock:
                self._refill()
                if self._tokens >= 1.0:
                    self._tokens -= 1.0
                    return True
                # Calculate wait time for next token
                wait = (1.0 - self._tokens) / self.rate

            if deadline is not None:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    return False
                wait = min(wait, remaining)

            time.sleep(wait)

    def __enter__(self):
        self.acquire()
        return self

    def __exit__(self, *exc):
        pass


# ──────────────────────────────────────────────
# Shared limiter instances (per-domain)
# ──────────────────────────────────────────────

_domain_limiters: dict[str, TokenBucketLimiter] = {}
_global_lock = threading.Lock()


def get_domain_limiter(domain: str, rate: float) -> TokenBucketLimiter:
    """Get or create a rate limiter for a specific domain.

    Limiters are cached so the same domain always shares one bucket.
    """
    with _global_lock:
        if domain not in _domain_limiters:
            _domain_limiters[domain] = TokenBucketLimiter(rate=rate)
        return _domain_limiters[domain]


# Convenience: no-op limiter for when rate limiting is disabled
class _NoOpLimiter:
    """Limiter that never blocks."""

    def acquire(self, timeout: float | None = None) -> bool:
        return True

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        pass


NOOP_LIMITER = _NoOpLimiter()
