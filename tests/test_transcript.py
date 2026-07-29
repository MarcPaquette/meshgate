"""Tests for the in-memory per-node chat transcript recorder."""

import threading

import pytest

from meshgate.core.transcript import Direction, TranscriptRecorder


@pytest.fixture
def recorder() -> TranscriptRecorder:
    """Enabled recorder with small limits, easy to overflow."""
    return TranscriptRecorder(enabled=True, max_messages=4, max_nodes=3)


class TestDisabledByDefault:
    """Recording is opt-in: it captures message content of every node."""

    def test_default_is_disabled(self) -> None:
        assert TranscriptRecorder().enabled is False

    def test_disabled_records_nothing(self) -> None:
        recorder = TranscriptRecorder(enabled=False)

        recorder.record_inbound("!node", "secret")

        assert recorder.get("!node") == []
        assert recorder.tracked_node_count == 0


class TestRecording:
    """Both directions are captured, in order."""

    def test_records_both_directions(self, recorder: TranscriptRecorder) -> None:
        recorder.record_inbound("!node", "hello")
        recorder.record_outbound("!node", "hi there")

        entries = recorder.get("!node")

        assert [e.direction for e in entries] == [
            Direction.INBOUND,
            Direction.OUTBOUND,
        ]
        assert [e.text for e in entries] == ["hello", "hi there"]

    def test_entries_carry_a_timestamp(self, recorder: TranscriptRecorder) -> None:
        recorder.record_inbound("!node", "hello")

        assert recorder.get("!node")[0].timestamp is not None

    def test_empty_text_is_not_recorded(self, recorder: TranscriptRecorder) -> None:
        recorder.record_inbound("!node", "")

        assert recorder.get("!node") == []

    def test_nodes_are_independent(self, recorder: TranscriptRecorder) -> None:
        recorder.record_inbound("!a", "from a")
        recorder.record_inbound("!b", "from b")

        assert [e.text for e in recorder.get("!a")] == ["from a"]
        assert [e.text for e in recorder.get("!b")] == ["from b"]

    def test_unknown_node_returns_empty(self, recorder: TranscriptRecorder) -> None:
        assert recorder.get("!nobody") == []

    def test_get_returns_a_copy(self, recorder: TranscriptRecorder) -> None:
        """Callers must not be able to mutate retained state."""
        recorder.record_inbound("!node", "hello")

        recorder.get("!node").clear()

        assert len(recorder.get("!node")) == 1


class TestMessageEviction:
    """Per-node history is bounded."""

    def test_oldest_messages_dropped(self, recorder: TranscriptRecorder) -> None:
        for i in range(6):
            recorder.record_inbound("!node", f"m{i}")

        entries = recorder.get("!node")

        assert len(entries) == 4
        assert [e.text for e in entries] == ["m2", "m3", "m4", "m5"]

    def test_rejects_non_positive_max_messages(self) -> None:
        with pytest.raises(ValueError, match="max_messages must be positive"):
            TranscriptRecorder(max_messages=0)


class TestNodeEviction:
    """The number of tracked nodes is bounded, so spoofed IDs can't exhaust RAM."""

    def test_least_recently_active_node_evicted(self, recorder: TranscriptRecorder) -> None:
        for node in ("!a", "!b", "!c"):
            recorder.record_inbound(node, "hi")

        recorder.record_inbound("!d", "hi")

        assert recorder.tracked_node_count == 3
        assert recorder.get("!a") == []
        assert recorder.get("!d") != []

    def test_activity_refreshes_position(self, recorder: TranscriptRecorder) -> None:
        for node in ("!a", "!b", "!c"):
            recorder.record_inbound(node, "hi")

        # Touch !a so !b becomes the least recently active.
        recorder.record_inbound("!a", "again")
        recorder.record_inbound("!d", "hi")

        assert recorder.get("!a") != []
        assert recorder.get("!b") == []

    def test_rejects_non_positive_max_nodes(self) -> None:
        with pytest.raises(ValueError, match="max_nodes must be positive"):
            TranscriptRecorder(max_nodes=0)


class TestPruning:
    """Transcripts for gone sessions are dropped so node IDs don't accumulate."""

    def test_retain_only_drops_others(self, recorder: TranscriptRecorder) -> None:
        for node in ("!a", "!b", "!c"):
            recorder.record_inbound(node, "hi")

        dropped = recorder.retain_only({"!b"})

        assert dropped == 2
        assert recorder.node_ids() == ["!b"]

    def test_retain_only_keeps_everything_when_all_live(self, recorder: TranscriptRecorder) -> None:
        recorder.record_inbound("!a", "hi")

        assert recorder.retain_only({"!a"}) == 0
        assert recorder.get("!a") != []

    def test_retain_empty_set_drops_all(self, recorder: TranscriptRecorder) -> None:
        recorder.record_inbound("!a", "hi")

        assert recorder.retain_only(set()) == 1
        assert recorder.tracked_node_count == 0

    def test_discard_single_node(self, recorder: TranscriptRecorder) -> None:
        recorder.record_inbound("!a", "hi")

        assert recorder.discard("!a") is True
        assert recorder.discard("!a") is False

    def test_clear(self, recorder: TranscriptRecorder) -> None:
        recorder.record_inbound("!a", "hi")
        recorder.record_inbound("!b", "hi")

        recorder.clear()

        assert recorder.tracked_node_count == 0


class TestThreadSafety:
    """Records may arrive from more than one thread."""

    def test_concurrent_record_does_not_corrupt(self) -> None:
        recorder = TranscriptRecorder(enabled=True, max_messages=1000, max_nodes=50)

        def worker(node: str) -> None:
            for i in range(100):
                recorder.record_inbound(node, f"m{i}")

        threads = [threading.Thread(target=worker, args=(f"!n{i}",)) for i in range(8)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=10)

        assert recorder.tracked_node_count == 8
        for i in range(8):
            assert len(recorder.get(f"!n{i}")) == 100
