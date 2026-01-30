"""Tests for rate limiting."""

import time

from meshgate.core.rate_limiter import RateLimiter, RateLimitResult


class TestRateLimiter:
    """Tests for RateLimiter class."""

    def test_allows_under_limit(self) -> None:
        """Test that messages under the limit are allowed."""
        limiter = RateLimiter(max_messages=5, window_seconds=60)

        for i in range(5):
            result = limiter.check("!node1")
            assert result.allowed, f"Message {i+1} should be allowed"
            assert result.retry_after_seconds is None

    def test_blocks_over_limit(self) -> None:
        """Test that messages over the limit are blocked."""
        limiter = RateLimiter(max_messages=3, window_seconds=60)

        # First 3 should be allowed
        for _ in range(3):
            result = limiter.check("!node1")
            assert result.allowed

        # 4th should be blocked
        result = limiter.check("!node1")
        assert not result.allowed
        assert result.retry_after_seconds is not None
        assert result.retry_after_seconds > 0

    def test_disabled_allows_all(self) -> None:
        """Test that disabled limiter allows all messages."""
        limiter = RateLimiter(max_messages=1, window_seconds=60, enabled=False)

        for _ in range(100):
            result = limiter.check("!node1")
            assert result.allowed

    def test_per_node_limits(self) -> None:
        """Test that each node has independent limits."""
        limiter = RateLimiter(max_messages=2, window_seconds=60)

        # Node 1 uses both slots
        limiter.check("!node1")
        limiter.check("!node1")
        result = limiter.check("!node1")
        assert not result.allowed

        # Node 2 should still have slots
        result = limiter.check("!node2")
        assert result.allowed

    def test_sliding_window_expiry(self) -> None:
        """Test that old messages expire from the window."""
        limiter = RateLimiter(max_messages=2, window_seconds=1)

        # Use both slots
        limiter.check("!node1")
        limiter.check("!node1")
        result = limiter.check("!node1")
        assert not result.allowed

        # Wait for window to expire
        time.sleep(1.1)

        # Should be allowed again
        result = limiter.check("!node1")
        assert result.allowed

    def test_retry_after_calculation(self) -> None:
        """Test that retry_after is calculated correctly."""
        limiter = RateLimiter(max_messages=1, window_seconds=10)

        # Use the slot
        limiter.check("!node1")

        # Check immediately - should have ~10s retry
        result = limiter.check("!node1")
        assert not result.allowed
        assert result.retry_after_seconds is not None
        # Should be close to 10 seconds (allowing for test execution time)
        assert 9 < result.retry_after_seconds <= 10

    def test_cleanup_inactive_removes_old_nodes(self) -> None:
        """Test that cleanup removes inactive nodes."""
        limiter = RateLimiter(max_messages=10, window_seconds=60)

        # Add some nodes
        limiter.check("!node1")
        limiter.check("!node2")
        limiter.check("!node3")

        assert limiter.tracked_node_count == 3

        # Cleanup with very short inactive time (everything is recent)
        removed = limiter.cleanup_inactive(inactive_seconds=3600)
        assert removed == 0
        assert limiter.tracked_node_count == 3

        # Wait a moment and clean up with very short inactive time
        time.sleep(0.1)
        removed = limiter.cleanup_inactive(inactive_seconds=0)  # 0 seconds = immediate cleanup
        assert removed == 3
        assert limiter.tracked_node_count == 0

    def test_properties(self) -> None:
        """Test limiter properties."""
        limiter = RateLimiter(max_messages=5, window_seconds=30, enabled=True)

        assert limiter.max_messages == 5
        assert limiter.window_seconds == 30
        assert limiter.enabled is True
        assert limiter.tracked_node_count == 0


class TestRateLimitResult:
    """Tests for RateLimitResult namedtuple."""

    def test_allowed_result(self) -> None:
        """Test creating an allowed result."""
        result = RateLimitResult(allowed=True)
        assert result.allowed is True
        assert result.retry_after_seconds is None

    def test_blocked_result(self) -> None:
        """Test creating a blocked result."""
        result = RateLimitResult(allowed=False, retry_after_seconds=30.5)
        assert result.allowed is False
        assert result.retry_after_seconds == 30.5


class TestRateLimiterIntegration:
    """Integration tests for rate limiting scenarios."""

    def test_burst_followed_by_trickle(self) -> None:
        """Test burst of messages followed by slow trickle."""
        limiter = RateLimiter(max_messages=3, window_seconds=1)

        # Burst - uses all slots
        for _ in range(3):
            assert limiter.check("!node1").allowed

        # Blocked
        assert not limiter.check("!node1").allowed

        # Wait and trickle
        time.sleep(1.1)
        assert limiter.check("!node1").allowed
        assert limiter.check("!node1").allowed
        assert limiter.check("!node1").allowed
        assert not limiter.check("!node1").allowed

    def test_multiple_nodes_concurrent(self) -> None:
        """Test multiple nodes hitting limits concurrently."""
        limiter = RateLimiter(max_messages=2, window_seconds=60)

        # Interleaved messages from multiple nodes
        for node in ["!node1", "!node2", "!node3"]:
            assert limiter.check(node).allowed
            assert limiter.check(node).allowed
            assert not limiter.check(node).allowed

        # All nodes are at limit
        for node in ["!node1", "!node2", "!node3"]:
            assert not limiter.check(node).allowed

    def test_realistic_rate_limit(self) -> None:
        """Test a realistic rate limit scenario."""
        # 10 messages per 60 seconds
        limiter = RateLimiter(max_messages=10, window_seconds=60)

        # Normal user sending a few messages
        for _ in range(5):
            assert limiter.check("!normal_user").allowed

        # Spammer trying to flood
        for _ in range(10):
            limiter.check("!spammer")

        # Normal user still has headroom
        for _ in range(5):
            assert limiter.check("!normal_user").allowed

        # Both should be at limit now
        assert not limiter.check("!normal_user").allowed
        assert not limiter.check("!spammer").allowed
