"""
Unit tests for core.dispatcher.RateLimiter.

Tests cover:
- Basic rate limiting (calls within limit pass immediately)
- Rate limit exceeded returns positive wait time
- Sliding window expiry (old timestamps expire)
- Thread safety (concurrent access)
- Edge cases (rate_limit=1)
"""

import time
import threading
from unittest.mock import patch

from core.dispatcher import RateLimiter


# ---------------------------------------------------------------------------
# Tests: Basic rate limiting
# ---------------------------------------------------------------------------

class TestBasicRateLimiting:
    def test_calls_within_limit_return_zero(self):
        """Calls within the rate limit should return 0 (no wait needed)."""
        limiter = RateLimiter(calls_per_minute=10)

        for _ in range(10):
            wait = limiter.acquire()
            assert wait == 0.0

    def test_first_call_always_passes(self):
        """The very first call should always succeed immediately."""
        limiter = RateLimiter(calls_per_minute=1)
        wait = limiter.acquire()
        assert wait == 0.0

    def test_multiple_calls_under_limit(self):
        """Multiple calls under the limit all pass immediately."""
        limiter = RateLimiter(calls_per_minute=100)

        for i in range(50):
            wait = limiter.acquire()
            assert wait == 0.0, f"Call {i+1} should pass but got wait={wait}"


# ---------------------------------------------------------------------------
# Tests: Rate limit exceeded
# ---------------------------------------------------------------------------

class TestRateLimitExceeded:
    def test_exceeding_limit_returns_positive_wait(self):
        """When rate limit is reached, acquire() returns positive wait time."""
        limiter = RateLimiter(calls_per_minute=5)

        # Fill up the window
        for _ in range(5):
            wait = limiter.acquire()
            assert wait == 0.0

        # Next call should require waiting
        wait = limiter.acquire()
        assert wait > 0.0
        assert wait <= 60.0  # Should not exceed window size

    def test_wait_time_is_reasonable(self):
        """Wait time should be close to the full window when just exceeded."""
        limiter = RateLimiter(calls_per_minute=3)

        # Fill up the window quickly
        for _ in range(3):
            limiter.acquire()

        # The wait time should be close to 60 seconds (oldest needs to expire)
        wait = limiter.acquire()
        assert 59.0 <= wait <= 60.0


# ---------------------------------------------------------------------------
# Tests: Sliding window expiry
# ---------------------------------------------------------------------------

class TestSlidingWindowExpiry:
    def test_old_timestamps_expire(self):
        """Timestamps older than 60 seconds are purged from the window."""
        limiter = RateLimiter(calls_per_minute=2)

        # Make 2 calls (fills the window)
        limiter.acquire()
        limiter.acquire()

        # Manually age the timestamps by setting them to 61 seconds ago
        with limiter._lock:
            old_time = time.monotonic() - 61.0
            limiter._timestamps = [old_time, old_time]

        # Now acquire should succeed because old timestamps expired
        wait = limiter.acquire()
        assert wait == 0.0

    def test_partial_expiry(self):
        """Only expired timestamps are purged; recent ones remain."""
        limiter = RateLimiter(calls_per_minute=3)

        # Manually set up: 1 old timestamp + 2 recent ones
        now = time.monotonic()
        with limiter._lock:
            limiter._timestamps = [
                now - 61.0,  # expired
                now - 1.0,   # recent
                now - 0.5,   # recent
            ]

        # After purging the expired one, we have 2/3 capacity → should pass
        wait = limiter.acquire()
        assert wait == 0.0

    def test_window_slides_correctly(self):
        """After waiting for expiry, new calls can proceed."""
        limiter = RateLimiter(calls_per_minute=2)

        # Fill the window
        limiter.acquire()
        limiter.acquire()

        # Simulate time passing: move timestamps to just barely expired
        with limiter._lock:
            expired_time = time.monotonic() - 60.1
            limiter._timestamps = [expired_time, expired_time]

        # Both expired, so 2 new calls should pass
        assert limiter.acquire() == 0.0
        assert limiter.acquire() == 0.0


# ---------------------------------------------------------------------------
# Tests: Thread safety
# ---------------------------------------------------------------------------

class TestThreadSafety:
    def test_concurrent_access_no_over_allocation(self):
        """Concurrent threads should not exceed the rate limit."""
        limiter = RateLimiter(calls_per_minute=10)
        results = []
        barrier = threading.Barrier(20)

        def worker():
            barrier.wait()  # Synchronize all threads to start together
            wait = limiter.acquire()
            results.append(wait)

        threads = [threading.Thread(target=worker) for _ in range(20)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        # Exactly 10 should have gotten through (wait == 0.0)
        passed = sum(1 for w in results if w == 0.0)
        blocked = sum(1 for w in results if w > 0.0)

        assert passed == 10
        assert blocked == 10

    def test_concurrent_wait_if_needed(self):
        """Multiple threads calling wait_if_needed should all eventually proceed."""
        limiter = RateLimiter(calls_per_minute=5)
        completed = []
        lock = threading.Lock()

        # Manually set timestamps so only 2 more calls fit
        now = time.monotonic()
        with limiter._lock:
            limiter._timestamps = [
                now - 0.5,
                now - 0.4,
                now - 0.3,
            ]

        def worker(worker_id):
            limiter.wait_if_needed()
            with lock:
                completed.append(worker_id)

        # Only 2 can pass immediately (3 already in window, limit is 5)
        threads = [threading.Thread(target=worker, args=(i,)) for i in range(2)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=5)

        assert len(completed) == 2


# ---------------------------------------------------------------------------
# Tests: Edge cases
# ---------------------------------------------------------------------------

class TestEdgeCases:
    def test_rate_limit_one(self):
        """Rate limit of 1 allows exactly one call per window."""
        limiter = RateLimiter(calls_per_minute=1)

        # First call passes
        wait = limiter.acquire()
        assert wait == 0.0

        # Second call must wait
        wait = limiter.acquire()
        assert wait > 0.0

    def test_rate_limit_zero_clamped_to_one(self):
        """Rate limit of 0 is clamped to 1 (minimum)."""
        limiter = RateLimiter(calls_per_minute=0)
        assert limiter._max_calls == 1

        # First call passes
        wait = limiter.acquire()
        assert wait == 0.0

    def test_negative_rate_limit_clamped_to_one(self):
        """Negative rate limit is clamped to 1."""
        limiter = RateLimiter(calls_per_minute=-5)
        assert limiter._max_calls == 1

    def test_wait_if_needed_returns_immediately_when_under_limit(self):
        """wait_if_needed returns immediately when under the rate limit."""
        limiter = RateLimiter(calls_per_minute=100)

        start = time.monotonic()
        limiter.wait_if_needed()
        elapsed = time.monotonic() - start

        # Should be nearly instant (< 10ms)
        assert elapsed < 0.01

    def test_wait_if_needed_blocks_when_at_limit(self):
        """wait_if_needed blocks until a slot becomes available."""
        limiter = RateLimiter(calls_per_minute=2)

        # Fill the window with timestamps that will expire in ~0.1 seconds
        now = time.monotonic()
        with limiter._lock:
            limiter._timestamps = [
                now - 59.9,  # Will expire in 0.1s
                now - 59.85,  # Will expire in 0.15s
            ]

        start = time.monotonic()
        limiter.wait_if_needed()
        elapsed = time.monotonic() - start

        # Should have waited approximately 0.1 seconds
        assert elapsed >= 0.05
        assert elapsed < 1.0  # But not too long

    def test_large_rate_limit(self):
        """Large rate limit allows many calls."""
        limiter = RateLimiter(calls_per_minute=10000)

        for _ in range(1000):
            wait = limiter.acquire()
            assert wait == 0.0
