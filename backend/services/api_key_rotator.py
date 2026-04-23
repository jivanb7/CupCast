"""
backend/services/api_key_rotator.py
=====================================
Thread-safe API-Football key manager with rate limiting.

Pro plan: 7,500 requests/day, 300 requests/minute.
We enforce a 295 r/m safety cap to stay under the limit.

Usage:
    from services.api_key_rotator import get_api_football_key, mark_key_exhausted

    key = get_api_football_key()
    # ... make API call with key ...
    # if response.status_code == 429:
    #     mark_key_exhausted(key)

The rotator must be initialized once at startup via init_rotator(keys).
That call lives in main.py lifespan. Callers never touch the rotator directly.
"""

import logging
import threading
import time
from collections import deque
from datetime import datetime, timezone

# Hard cap: never exceed this many requests per 60-second window
MAX_REQUESTS_PER_MINUTE = 295

logger = logging.getLogger(__name__)


class ApiKeyRotator:
    """Round-robin API key rotation with per-key exhaustion tracking.

    Resets exhaustion counters at UTC midnight.
    Thread-safe for concurrent access from background threads.
    """

    def __init__(self, keys: list[str]):
        if not keys:
            raise ValueError("ApiKeyRotator requires at least one key")

        self._keys = [k.strip() for k in keys if k.strip()]
        if not self._keys:
            raise ValueError("ApiKeyRotator requires at least one non-empty key")

        self._index = 0                      # next key to hand out (round-robin)
        self._exhausted: set[str] = set()    # keys that returned 429 today
        self._lock = threading.Lock()
        self._last_reset_date = datetime.now(timezone.utc).date()

        # Sliding-window rate limiter: timestamps of requests in the last 60s
        self._request_timestamps: deque[float] = deque()

        logger.info("ApiKeyRotator: initialized with %d keys (rate limit: %d r/m)",
                     len(self._keys), MAX_REQUESTS_PER_MINUTE)

    def get_key(self) -> str:
        """Get the next available key, respecting the per-minute rate limit.

        Blocks (sleeps) if we've hit 295 requests in the current 60-second
        window. This keeps us safely under the Pro plan's 300 r/m cap.

        If ALL keys are exhausted, logs a critical warning and returns the
        next key anyway — better to attempt a call than to silently drop data.
        """
        with self._lock:
            self._check_reset()
            self._enforce_rate_limit()

            available = [k for k in self._keys if k not in self._exhausted]

            if not available:
                logger.critical(
                    "ApiKeyRotator: ALL %d keys exhausted for today — returning next key anyway",
                    len(self._keys),
                )
                # Fall back to plain round-robin so callers don't break
                key = self._keys[self._index % len(self._keys)]
                self._index = (self._index + 1) % len(self._keys)
                return key

            # Advance index until we land on an available key
            for _ in range(len(self._keys)):
                candidate = self._keys[self._index % len(self._keys)]
                self._index = (self._index + 1) % len(self._keys)
                if candidate in available:
                    return candidate

            # Should never reach here, but guard anyway
            return available[0]

    def mark_exhausted(self, key: str) -> None:
        """Mark a key as exhausted (got 429 response). Will reset at midnight UTC."""
        with self._lock:
            self._exhausted.add(key)
            remaining = len(self._keys) - len(self._exhausted)
            logger.warning(
                "ApiKeyRotator: key ...%s marked exhausted. %d/%d keys remaining today.",
                key[-8:], remaining, len(self._keys),
            )

    def _enforce_rate_limit(self) -> None:
        """Block until we're under the per-minute rate cap.

        Uses a sliding window of request timestamps. Must be called while
        holding self._lock — releases the lock while sleeping so other
        threads aren't blocked unnecessarily. The release/acquire dance is
        wrapped in try/finally so an exception raised while sleeping (e.g.
        SystemExit on SIGTERM) cannot leave the lock in a mismatched state
        for the enclosing `with self._lock:` context manager.
        """
        window = 60.0

        while True:
            now = time.monotonic()
            # Purge timestamps older than 60s
            while self._request_timestamps and self._request_timestamps[0] <= now - window:
                self._request_timestamps.popleft()

            if len(self._request_timestamps) < MAX_REQUESTS_PER_MINUTE:
                break

            oldest = self._request_timestamps[0]
            sleep_for = oldest - (now - window) + 0.05  # small buffer
            if sleep_for <= 0:
                break

            logger.warning(
                "Rate limit: %d requests in last 60s — sleeping %.1fs",
                len(self._request_timestamps), sleep_for,
            )
            self._lock.release()
            try:
                time.sleep(sleep_for)
            finally:
                # Guarantee the lock is re-acquired even if sleep was
                # interrupted — the caller's `with` block must be able to
                # release it cleanly on the way out.
                self._lock.acquire()
            # Loop to re-check the window (another thread may have filled it)

        # Record this request
        self._request_timestamps.append(time.monotonic())

    def _check_reset(self) -> None:
        """Reset all exhaustion flags if we've crossed midnight UTC.

        Must be called while holding self._lock.
        """
        today = datetime.now(timezone.utc).date()
        if today != self._last_reset_date:
            self._exhausted.clear()
            self._last_reset_date = today
            logger.info("ApiKeyRotator: daily reset — all %d keys available", len(self._keys))


# ---------------------------------------------------------------------------
# Module-level singleton
# ---------------------------------------------------------------------------

_rotator: ApiKeyRotator | None = None


def init_rotator(keys: list[str]) -> None:
    """Initialize the global rotator. Called once from main.py lifespan.

    Filters out empty strings so callers don't need to pre-clean.
    If no valid keys remain after filtering, logs a warning and skips init.
    """
    global _rotator
    clean_keys = [k.strip() for k in keys if k.strip()]
    if not clean_keys:
        logger.warning(
            "ApiKeyRotator: no valid API-Football keys provided — rotator not initialized"
        )
        return

    _rotator = ApiKeyRotator(clean_keys)
    logger.info("API key rotator initialized with %d keys", len(clean_keys))


def get_api_football_key() -> str:
    """Get an API-Football key. Thread-safe, round-robin.

    Raises RuntimeError if init_rotator() was never called.
    """
    if _rotator is None:
        raise RuntimeError(
            "API key rotator not initialized. Call init_rotator() first."
        )
    return _rotator.get_key()


def mark_key_exhausted(key: str) -> None:
    """Mark a key as exhausted after a 429 response.

    Safe to call even if the rotator was never initialized (no-op in that case).
    """
    if _rotator is not None:
        _rotator.mark_exhausted(key)
