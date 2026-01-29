"""Tests for session management."""

from datetime import datetime, timedelta

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
        old_time = session.last_activity

        session.update_activity()

        # Compare with tolerance - new time should be >= old time
        assert session.last_activity >= old_time

    def test_enter_plugin_clears_state(self) -> None:
        """Test that entering a new plugin clears old state."""
        session = Session(node_id="!test123")
        session.enter_plugin("Plugin A")
        session.update_plugin_state({"key": "value"})

        session.enter_plugin("Plugin B")

        assert session.active_plugin == "Plugin B"
        assert session.plugin_state == {}


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

        # Manually set last_activity to past
        session.last_activity = datetime.now() - timedelta(minutes=2)

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
