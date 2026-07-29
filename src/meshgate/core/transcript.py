"""In-memory per-node chat transcripts.

Message text is otherwise logged at DEBUG and discarded, so there is no way to
review what a node has been doing. This retains a bounded, recent window per
node in memory only - nothing is written to disk.

Disabled by default: enabling it records the message content of every node that
talks to the gateway.
"""

import threading
from collections import OrderedDict
from dataclasses import dataclass
from datetime import datetime
from enum import Enum


class Direction(str, Enum):
    """Which way a message travelled."""

    INBOUND = "inbound"
    OUTBOUND = "outbound"


@dataclass(frozen=True)
class TranscriptEntry:
    """A single recorded message.

    Attributes:
        timestamp: When the message was recorded
        direction: Whether the message came from or went to the node
        text: The message text
    """

    timestamp: datetime
    direction: Direction
    text: str


class TranscriptRecorder:
    """Retains a bounded window of recent messages per node.

    Both the number of messages kept per node and the number of nodes tracked
    are capped, so memory cannot grow without bound even if a flood of spoofed
    node IDs arrives. When the node cap is reached the least recently active
    node's transcript is dropped.

    When disabled, every record call is a no-op and no text is retained.
    """

    def __init__(
        self,
        enabled: bool = False,
        max_messages: int = 50,
        max_nodes: int = 200,
    ) -> None:
        """Initialize the recorder.

        Args:
            enabled: Whether to record at all
            max_messages: Messages retained per node
            max_nodes: Number of nodes tracked before evicting the oldest

        Raises:
            ValueError: If either limit is not positive
        """
        if max_messages <= 0:
            raise ValueError(f"max_messages must be positive, got {max_messages}")
        if max_nodes <= 0:
            raise ValueError(f"max_nodes must be positive, got {max_nodes}")

        self._enabled = enabled
        self._max_messages = max_messages
        self._max_nodes = max_nodes
        # Ordered so the least recently active node is first, making eviction
        # O(1) rather than a scan.
        self._transcripts: OrderedDict[str, list[TranscriptEntry]] = OrderedDict()
        self._lock = threading.Lock()

    @property
    def enabled(self) -> bool:
        """Whether recording is active."""
        return self._enabled

    @property
    def max_messages(self) -> int:
        """Messages retained per node."""
        return self._max_messages

    @property
    def tracked_node_count(self) -> int:
        """Number of nodes with a retained transcript."""
        with self._lock:
            return len(self._transcripts)

    def record(self, node_id: str, direction: Direction, text: str) -> None:
        """Record a message, if recording is enabled.

        Args:
            node_id: The node the message came from or went to
            direction: Which way the message travelled
            text: The message text
        """
        if not self._enabled or not text:
            return

        entry = TranscriptEntry(timestamp=datetime.now(), direction=direction, text=text)

        with self._lock:
            messages = self._transcripts.get(node_id)
            if messages is None:
                while len(self._transcripts) >= self._max_nodes:
                    self._transcripts.popitem(last=False)
                messages = []
                self._transcripts[node_id] = messages

            messages.append(entry)
            if len(messages) > self._max_messages:
                del messages[: len(messages) - self._max_messages]

            # Most recently active node moves to the end.
            self._transcripts.move_to_end(node_id)

    def record_inbound(self, node_id: str, text: str) -> None:
        """Record a message received from a node."""
        self.record(node_id, Direction.INBOUND, text)

    def record_outbound(self, node_id: str, text: str) -> None:
        """Record a message sent to a node."""
        self.record(node_id, Direction.OUTBOUND, text)

    def get(self, node_id: str) -> list[TranscriptEntry]:
        """Get a node's retained transcript.

        Args:
            node_id: The node to look up

        Returns:
            Entries oldest first, or an empty list if nothing is retained
        """
        with self._lock:
            return list(self._transcripts.get(node_id, ()))

    def node_ids(self) -> list[str]:
        """Get the nodes with retained transcripts, least recently active first."""
        with self._lock:
            return list(self._transcripts)

    def discard(self, node_id: str) -> bool:
        """Drop a node's transcript.

        Args:
            node_id: The node to drop

        Returns:
            True if a transcript was dropped
        """
        with self._lock:
            return self._transcripts.pop(node_id, None) is not None

    def retain_only(self, node_ids: set[str]) -> int:
        """Drop transcripts for nodes outside the given set.

        Used to prune transcripts for nodes whose sessions have expired, so
        the recorder does not accumulate node IDs indefinitely.

        Args:
            node_ids: Nodes to keep

        Returns:
            Number of transcripts dropped
        """
        with self._lock:
            stale = [n for n in self._transcripts if n not in node_ids]
            for node_id in stale:
                del self._transcripts[node_id]
            return len(stale)

    def clear(self) -> None:
        """Drop all retained transcripts."""
        with self._lock:
            self._transcripts.clear()
