"""Tests for session management."""

from datetime import datetime

import pytest

from meshgate.core.session import Session
from meshgate.core.session_manager import SessionManager


class TestSession:
    """Tests for Session class."""

    def test_create_session(self) -> None:
        """Test creating a session."""
        session = Session(node_id="!test123")
        assert session.node_id == "!test123"
        assert session.active_plugin is None
        assert session.plugin_state == {}
        assert session.is_at_menu

    def test_empty_node_id_raises(self) -> None:
        """Test that empty node_id raises error."""
        with pytest.raises(ValueError, match="node_id cannot be empty"):
            Session(node_id="")

    def test_enter_plugin(self) -> None:
        """Test entering a plugin."""
        session = Session(node_id="!test123")
        session.enter_plugin("Test Plugin")

        assert session.active_plugin == "Test Plugin"
        assert session.plugin_state == {}
        assert not session.is_at_menu

    def test_exit_plugin(self) -> None:
        """Test exiting a plugin."""
        session = Session(node_id="!test123")
        session.enter_plugin("Test Plugin")
        session.update_plugin_state({"key": "value"})

        session.exit_plugin()

        assert session.active_plugin is None
        assert session.plugin_state == {}
        assert session.is_at_menu

    def test_update_plugin_state(self) -> None:
        """Test updating plugin state."""
        session = Session(node_id="!test123")
        session.update_plugin_state({"key1": "value1"})
        session.update_plugin_state({"key2": "value2"})

        assert session.plugin_state == {"key1": "value1", "key2": "value2"}

    def test_update_activity(self) -> None:
        """Test activity timestamp update."""
        session = Session(node_id="!test123")
        # Set last_activity to a known past time
        past = datetime(2020, 1, 1)
        session.last_activity = past

        session.update_activity()

        assert session.last_activity > past

    def test_enter_plugin_clears_state(self) -> None:
        """Test that entering a new plugin clears old state."""
        session = Session(node_id="!test123")
        session.enter_plugin("Plugin A")
        session.update_plugin_state({"key": "value"})

        session.enter_plugin("Plugin B")

        assert session.active_plugin == "Plugin B"
        assert session.plugin_state == {}

    def test_update_plugin_state_within_limit(self) -> None:
        """Test state update succeeds within size limit."""
        session = Session(node_id="!abc123")
        result = session.update_plugin_state({"key": "value"}, max_bytes=1024)
        assert result is True
        assert session.plugin_state == {"key": "value"}

    def test_update_plugin_state_exceeds_limit(self) -> None:
        """Test state update rejected when exceeding limit."""
        session = Session(node_id="!abc123")
        large_data = {"key": "x" * 10000}
        result = session.update_plugin_state(large_data, max_bytes=1024)
        assert result is False
        assert session.plugin_state == {}  # Unchanged

    def test_update_plugin_state_unlimited(self) -> None:
        """Test state update with no limit (max_bytes=0)."""
        session = Session(node_id="!abc123")
        large_data = {"key": "x" * 10000}
        result = session.update_plugin_state(large_data, max_bytes=0)
        assert result is True
        assert session.plugin_state == large_data

    def test_update_plugin_state_checks_merged_size(self) -> None:
        """Test that size check considers existing + new state."""
        session = Session(node_id="!abc123")
        # 500 + 1600 = 2100 bytes content, exceeding 2048 only when merged
        session.update_plugin_state({"existing": "x" * 500}, max_bytes=2048)
        result = session.update_plugin_state({"new": "y" * 1600}, max_bytes=2048)
        assert result is False
        assert "existing" in session.plugin_state
        assert "new" not in session.plugin_state


class TestSessionManager:
    """Tests for SessionManager class."""

    def test_get_session_creates_new(self) -> None:
        """Test that get_session creates new session."""
        manager = SessionManager()
        session = manager.get_session("!test123")

        assert session.node_id == "!test123"
        assert manager.active_session_count == 1

    def test_get_session_returns_existing(self) -> None:
        """Test that get_session returns existing session."""
        manager = SessionManager()
        session1 = manager.get_session("!test123")
        session1.enter_plugin("Test Plugin")

        session2 = manager.get_session("!test123")

        assert session1 is session2
        assert session2.active_plugin == "Test Plugin"

    def test_get_existing_session(self) -> None:
        """Test get_existing_session for existing session."""
        manager = SessionManager()
        manager.get_session("!test123")

        existing = manager.get_existing_session("!test123")
        assert existing is not None

    def test_get_existing_session_not_found(self) -> None:
        """Test get_existing_session for non-existent session."""
        manager = SessionManager()
        existing = manager.get_existing_session("!nonexistent")
        assert existing is None

    def test_remove_session(self) -> None:
        """Test removing a session."""
        manager = SessionManager()
        manager.get_session("!test123")

        result = manager.remove_session("!test123")

        assert result is True
        assert manager.active_session_count == 0

    def test_remove_nonexistent_session(self) -> None:
        """Test removing non-existent session returns False."""
        manager = SessionManager()
        result = manager.remove_session("!nonexistent")
        assert result is False

    def test_multiple_sessions_independent(self) -> None:
        """Test that multiple sessions are independent."""
        manager = SessionManager()
        session_a = manager.get_session("!nodeA")
        session_b = manager.get_session("!nodeB")

        session_a.enter_plugin("Plugin A")
        session_b.enter_plugin("Plugin B")

        assert session_a.active_plugin == "Plugin A"
        assert session_b.active_plugin == "Plugin B"
        assert manager.active_session_count == 2

    def test_cleanup_expired_sessions(self) -> None:
        """Test cleanup of expired sessions."""
        manager = SessionManager(session_timeout_minutes=1)
        session = manager.get_session("!test123")

        # Expiry runs off the monotonic clock, so wind that back rather than
        # the wall-clock timestamp.
        session.last_activity_monotonic -= 120

        removed = manager.cleanup_expired_sessions()

        assert removed == 1
        assert manager.active_session_count == 0

    def test_cleanup_keeps_active_sessions(self) -> None:
        """Test cleanup keeps active sessions."""
        manager = SessionManager(session_timeout_minutes=60)
        manager.get_session("!test123")

        removed = manager.cleanup_expired_sessions()

        assert removed == 0
        assert manager.active_session_count == 1

    def test_list_sessions(self) -> None:
        """Test listing all sessions."""
        manager = SessionManager()
        manager.get_session("!node1")
        manager.get_session("!node2")

        sessions = manager.list_sessions()

        assert len(sessions) == 2
        node_ids = {s.node_id for s in sessions}
        assert node_ids == {"!node1", "!node2"}

    def test_max_sessions_enforced(self) -> None:
        """Test that max_sessions limit is enforced."""
        manager = SessionManager(max_sessions=2)
        manager.get_session("!node1")
        manager.get_session("!node2")

        assert manager.active_session_count == 2

        # Creating a third session should evict the oldest
        manager.get_session("!node3")

        assert manager.active_session_count == 2
        # node1 was oldest (created first), should be evicted
        assert manager.get_existing_session("!node1") is None
        assert manager.get_existing_session("!node2") is not None
        assert manager.get_existing_session("!node3") is not None

    def test_max_sessions_evicts_oldest_by_activity(self) -> None:
        """Test that eviction is based on last_activity, not creation time."""
        manager = SessionManager(max_sessions=2)

        manager.get_session("!node1")
        manager.get_session("!node2")

        # Touching node1 again makes it the more recently active of the two.
        manager.get_session("!node1")

        # Creating a third session should evict node2 (oldest activity)
        manager.get_session("!node3")

        assert manager.active_session_count == 2
        assert manager.get_existing_session("!node1") is not None
        assert manager.get_existing_session("!node2") is None
        assert manager.get_existing_session("!node3") is not None

    def test_max_sessions_zero_means_unlimited(self) -> None:
        """Test that max_sessions=0 means unlimited sessions."""
        manager = SessionManager(max_sessions=0)

        # Create many sessions
        for i in range(100):
            manager.get_session(f"!node{i}")

        assert manager.active_session_count == 100

    def test_get_existing_session_does_not_evict(self) -> None:
        """Test that get_existing_session doesn't trigger eviction."""
        manager = SessionManager(max_sessions=2)
        manager.get_session("!node1")
        manager.get_session("!node2")

        # get_existing_session for a new node should return None, not evict
        result = manager.get_existing_session("!node3")

        assert result is None
        assert manager.active_session_count == 2


class TestPluginStateSizeLimit:
    """The byte cap must reflect actual payload size.

    sys.getsizeof is shallow: for {"history": [...]} it reports the dict plus
    the list's pointer array and ignores every message, so the cap used to be
    off by orders of magnitude and effectively never fired.
    """

    def test_large_history_is_rejected(self) -> None:
        session = Session(node_id="!node")
        history = [{"role": "user", "content": "x" * 400} for _ in range(8)]

        # ~3.2 KB of real content; the old shallow measure reported ~304 bytes.
        assert session.update_plugin_state({"history": history}, max_bytes=1024) is False
        assert session.plugin_state == {}

    def test_small_state_is_accepted(self) -> None:
        session = Session(node_id="!node")

        assert session.update_plugin_state({"k": "v"}, max_bytes=1024) is True
        assert session.plugin_state == {"k": "v"}

    def test_limit_accounts_for_existing_state(self) -> None:
        """The check applies to the merged result, not just the new keys."""
        session = Session(node_id="!node")
        session.update_plugin_state({"a": "x" * 500})

        assert session.update_plugin_state({"b": "y" * 500}, max_bytes=800) is False
        assert "b" not in session.plugin_state

    def test_zero_means_unlimited(self) -> None:
        session = Session(node_id="!node")
        history = [{"role": "user", "content": "x" * 5000} for _ in range(20)]

        assert session.update_plugin_state({"history": history}, max_bytes=0) is True

    def test_unmeasurable_state_is_rejected(self) -> None:
        """Circular state can't be sized, so it must not slip past the cap."""
        session = Session(node_id="!node")
        circular: dict = {}
        circular["self"] = circular

        assert session.update_plugin_state(circular, max_bytes=1024) is False
