"""In-memory ring buffer for recent log records.

Logging otherwise goes only to stderr, so nothing is recoverable once it
scrolls past. This keeps the most recent records in memory so an operator
interface can display them.
"""

import logging
import threading
from collections import deque
from dataclasses import dataclass
from datetime import datetime


@dataclass(frozen=True)
class LogEntry:
    """A single captured log record.

    Attributes:
        seq: Monotonically increasing sequence number, used as a poll cursor
        timestamp: When the record was emitted
        level: Level name (e.g. "INFO")
        logger_name: Name of the emitting logger
        message: Formatted message text
    """

    seq: int
    timestamp: datetime
    level: str
    logger_name: str
    message: str


class RingBufferHandler(logging.Handler):
    """Logging handler that retains the most recent records in memory.

    Records are appended to a bounded deque, so memory is capped and the
    oldest entries are dropped once it is full. Each entry carries a
    monotonically increasing sequence number so a reader can ask for only
    what it has not already seen.

    Safe to attach alongside the normal stderr handler; it does not replace
    console output.
    """

    def __init__(self, capacity: int = 1000) -> None:
        """Initialize the handler.

        Args:
            capacity: Maximum number of records to retain

        Raises:
            ValueError: If capacity is not positive
        """
        if capacity <= 0:
            raise ValueError(f"capacity must be positive, got {capacity}")

        super().__init__()
        self._entries: deque[LogEntry] = deque(maxlen=capacity)
        # Guards _next_seq. Records arrive from the event loop and from
        # meshtastic's publishing thread, and read-modify-write of a counter
        # is not atomic even under the GIL.
        self._lock = threading.Lock()
        self._next_seq = 1

    @property
    def capacity(self) -> int:
        """Maximum number of retained records."""
        return self._entries.maxlen or 0

    def emit(self, record: logging.LogRecord) -> None:
        """Capture a record. Called by the logging framework."""
        try:
            message = record.getMessage()
        except Exception:
            # A bad format string must not take down the emitting code path.
            self.handleError(record)
            return

        with self._lock:
            seq = self._next_seq
            self._next_seq += 1
            self._entries.append(
                LogEntry(
                    seq=seq,
                    timestamp=datetime.fromtimestamp(record.created),
                    level=record.levelname,
                    logger_name=record.name,
                    message=message,
                )
            )

    def entries(self, since: int = 0, limit: int | None = None) -> list[LogEntry]:
        """Get retained records newer than a cursor.

        Args:
            since: Return only entries with seq greater than this
            limit: Maximum entries to return (most recent kept if exceeded)

        Returns:
            Matching entries, oldest first
        """
        with self._lock:
            snapshot = list(self._entries)

        if since > 0:
            snapshot = [e for e in snapshot if e.seq > since]
        if limit is not None and limit >= 0 and len(snapshot) > limit:
            snapshot = snapshot[-limit:]
        return snapshot

    @property
    def latest_seq(self) -> int:
        """Sequence number of the most recent entry, or 0 when empty."""
        with self._lock:
            return self._entries[-1].seq if self._entries else 0

    def clear(self) -> None:
        """Drop all retained records. Does not reset the sequence counter."""
        with self._lock:
            self._entries.clear()


# The attached buffer, if any. Module-level because logging configuration is
# itself process-global, and this is how a consumer (such as the web dashboard)
# reaches the buffer without threading it through every call site.
_active_buffer: RingBufferHandler | None = None


def set_active_buffer(buffer: RingBufferHandler | None) -> None:
    """Record the buffer attached to the root logger."""
    global _active_buffer
    _active_buffer = buffer


def get_active_buffer() -> RingBufferHandler | None:
    """Get the attached log buffer, or None if logs are not being retained."""
    return _active_buffer
