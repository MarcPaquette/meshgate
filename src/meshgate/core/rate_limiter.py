"""Rate limiting for per-node message throttling."""

import logging
import time
from collections import deque
from typing import NamedTuple

logger = logging.getLogger(__name__)


class RateLimitResult(NamedTuple):
    """Result of a rate limit check."""

    allowed: bool
    retry_after_seconds: float | None = None


class RateLimiter:
    """Per-node rate limiter using sliding window algorithm.

    Each node gets a deque of timestamps. When a message arrives:
    1. Remove timestamps older than window_seconds
    2. If count < max_messages, allow and add timestamp
    3. Otherwise reject and report retry_after time
    """

    def __init__(
        self,
        max_messages: int = 10,
        window_seconds: int = 60,
        enabled: bool = True,
    ) -> None:
        """Initialize the rate limiter.

        Args:
            max_messages: Maximum messages allowed per window
            window_seconds: Size of the sliding window in seconds
            enabled: Whether rate limiting is active
        """
        self._max_messages = max_messages
        self._window_seconds = window_seconds
        self._enabled = enabled
        self._node_timestamps: dict[str, deque[float]] = {}

    def check(self, node_id: str) -> RateLimitResult:
        """Check if a message from a node is allowed and record it.

        Args:
            node_id: The node sending the message

        Returns:
            RateLimitResult with allowed status and optional retry_after
        """
        if not self._enabled:
            return RateLimitResult(allowed=True)

        now = time.monotonic()
        cutoff = now - self._window_seconds

        # Get or create timestamp deque for this node
        if node_id not in self._node_timestamps:
            self._node_timestamps[node_id] = deque()

        timestamps = self._node_timestamps[node_id]

        # Remove expired timestamps
        while timestamps and timestamps[0] < cutoff:
            timestamps.popleft()

        # Check if under limit
        if len(timestamps) < self._max_messages:
            timestamps.append(now)
            return RateLimitResult(allowed=True)

        # Over limit - calculate retry_after from oldest timestamp
        oldest = timestamps[0]
        retry_after = (oldest + self._window_seconds) - now

        logger.warning(
            f"Rate limit exceeded for node {node_id}: "
            f"{len(timestamps)}/{self._max_messages} in {self._window_seconds}s"
        )

        return RateLimitResult(allowed=False, retry_after_seconds=max(0, retry_after))

    def cleanup_inactive(self, inactive_seconds: int = 300) -> int:
        """Remove tracking data for nodes that haven't sent messages recently.

        Args:
            inactive_seconds: Seconds of inactivity before cleanup

        Returns:
            Number of nodes cleaned up
        """
        now = time.monotonic()
        cutoff = now - inactive_seconds

        inactive_nodes = [
            node_id
            for node_id, timestamps in self._node_timestamps.items()
            if not timestamps or timestamps[-1] < cutoff
        ]

        for node_id in inactive_nodes:
            del self._node_timestamps[node_id]

        if inactive_nodes:
            logger.debug(f"Cleaned up rate limit data for {len(inactive_nodes)} inactive nodes")

        return len(inactive_nodes)

    @property
    def enabled(self) -> bool:
        """Check if rate limiting is enabled."""
        return self._enabled

    @property
    def max_messages(self) -> int:
        """Get the max messages per window."""
        return self._max_messages

    @property
    def window_seconds(self) -> int:
        """Get the window size in seconds."""
        return self._window_seconds

    @property
    def tracked_node_count(self) -> int:
        """Get the number of nodes being tracked."""
        return len(self._node_timestamps)
