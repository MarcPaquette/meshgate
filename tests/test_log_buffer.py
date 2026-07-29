"""Tests for the in-memory log ring buffer."""

import logging
import threading

import pytest

from meshgate.core.log_buffer import (
    RingBufferHandler,
    get_active_buffer,
    set_active_buffer,
)


@pytest.fixture
def handler() -> RingBufferHandler:
    """A small buffer, easy to overflow in tests."""
    return RingBufferHandler(capacity=5)


def emit(handler: RingBufferHandler, message: str, level: int = logging.INFO) -> None:
    """Push a record through the handler without touching global logging."""
    handler.emit(
        logging.LogRecord(
            name="test.logger",
            level=level,
            pathname=__file__,
            lineno=1,
            msg=message,
            args=(),
            exc_info=None,
        )
    )


class TestCapture:
    """Records are captured with the fields a dashboard needs."""

    def test_captures_message_fields(self, handler: RingBufferHandler) -> None:
        emit(handler, "hello", level=logging.WARNING)

        entry = handler.entries()[0]

        assert entry.message == "hello"
        assert entry.level == "WARNING"
        assert entry.logger_name == "test.logger"
        assert entry.seq == 1
        assert entry.timestamp is not None

    def test_formats_args(self, handler: RingBufferHandler) -> None:
        handler.emit(
            logging.LogRecord(
                name="t",
                level=logging.INFO,
                pathname=__file__,
                lineno=1,
                msg="count=%d",
                args=(7,),
                exc_info=None,
            )
        )

        assert handler.entries()[0].message == "count=7"

    def test_sequence_numbers_increase(self, handler: RingBufferHandler) -> None:
        for i in range(3):
            emit(handler, f"m{i}")

        assert [e.seq for e in handler.entries()] == [1, 2, 3]

    def test_bad_format_does_not_raise(self, handler: RingBufferHandler) -> None:
        """A broken format string must not break the code that logged it."""
        handler.emit(
            logging.LogRecord(
                name="t",
                level=logging.INFO,
                pathname=__file__,
                lineno=1,
                msg="missing %d %d",
                args=(1,),
                exc_info=None,
            )
        )

        # Nothing captured, but no exception escaped.
        assert handler.entries() == []


class TestEviction:
    """The buffer is bounded."""

    def test_oldest_records_are_dropped(self, handler: RingBufferHandler) -> None:
        for i in range(8):
            emit(handler, f"m{i}")

        entries = handler.entries()

        assert len(entries) == 5
        assert [e.message for e in entries] == ["m3", "m4", "m5", "m6", "m7"]

    def test_capacity_is_reported(self, handler: RingBufferHandler) -> None:
        assert handler.capacity == 5

    def test_rejects_non_positive_capacity(self) -> None:
        with pytest.raises(ValueError, match="capacity must be positive"):
            RingBufferHandler(capacity=0)


class TestCursor:
    """`since` lets a poller fetch only what it hasn't seen."""

    def test_since_returns_only_newer(self, handler: RingBufferHandler) -> None:
        for i in range(4):
            emit(handler, f"m{i}")

        newer = handler.entries(since=2)

        assert [e.message for e in newer] == ["m2", "m3"]

    def test_since_at_latest_returns_nothing(self, handler: RingBufferHandler) -> None:
        emit(handler, "only")

        assert handler.entries(since=handler.latest_seq) == []

    def test_since_survives_eviction(self, handler: RingBufferHandler) -> None:
        """A cursor older than everything retained returns what's left."""
        for i in range(10):
            emit(handler, f"m{i}")

        assert len(handler.entries(since=1)) == 5

    def test_latest_seq_empty_buffer(self, handler: RingBufferHandler) -> None:
        assert handler.latest_seq == 0

    def test_limit_keeps_most_recent(self, handler: RingBufferHandler) -> None:
        for i in range(5):
            emit(handler, f"m{i}")

        assert [e.message for e in handler.entries(limit=2)] == ["m3", "m4"]

    def test_clear_keeps_sequence_counter(self, handler: RingBufferHandler) -> None:
        emit(handler, "before")
        handler.clear()
        emit(handler, "after")

        # Sequence must not restart, or a poller's cursor would skip records.
        assert handler.entries()[0].seq == 2


class TestThreadSafety:
    """Records arrive from the event loop and from meshtastic's pubsub thread."""

    def test_concurrent_emit_loses_nothing(self) -> None:
        handler = RingBufferHandler(capacity=1000)
        per_thread = 100

        def worker() -> None:
            for i in range(per_thread):
                emit(handler, f"m{i}")

        threads = [threading.Thread(target=worker) for _ in range(8)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=10)

        entries = handler.entries()
        assert len(entries) == 8 * per_thread
        # Sequence numbers must be unique - a racing counter would collide.
        assert len({e.seq for e in entries}) == len(entries)


class TestRootLoggerIntegration:
    """Attaching to the root logger captures real application logs."""

    def test_captures_via_logger(self) -> None:
        handler = RingBufferHandler(capacity=10)
        log = logging.getLogger("meshgate.test.integration")
        log.addHandler(handler)
        log.setLevel(logging.INFO)
        try:
            log.info("through the logger")
            log.debug("filtered out")
        finally:
            log.removeHandler(handler)

        messages = [e.message for e in handler.entries()]
        assert "through the logger" in messages
        assert "filtered out" not in messages


class TestActiveBuffer:
    """The module-level accessor is how consumers reach the buffer."""

    def test_set_and_get(self) -> None:
        original = get_active_buffer()
        handler = RingBufferHandler(capacity=3)
        try:
            set_active_buffer(handler)
            assert get_active_buffer() is handler
        finally:
            set_active_buffer(original)

    def test_defaults_to_none(self) -> None:
        original = get_active_buffer()
        try:
            set_active_buffer(None)
            assert get_active_buffer() is None
        finally:
            set_active_buffer(original)
