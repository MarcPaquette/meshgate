"""Session manager for multi-node session management."""

from datetime import datetime, timedelta

from meshgate.core.session import Session


class SessionManager:
    """Manages sessions for all connected nodes.

    - Creates new session when unknown node sends first message
    - Retrieves existing session by node_id
    - Each node has completely independent state
    - Expired sessions cleaned up after configurable timeout

    Example with multiple nodes:
        Node !abc → sends "2" → enters LLM plugin
        Node !xyz → sends "3" → enters Weather plugin
        Node !abc → sends "hello" → handled by LLM (still in LLM)
        Node !xyz → sends "!exit" → returns to menu (abc unaffected)
    """

    def __init__(self, session_timeout_minutes: int = 60) -> None:
        """Initialize the session manager.

        Args:
            session_timeout_minutes: Time in minutes before inactive sessions are cleaned up
        """
        self._sessions: dict[str, Session] = {}
        self._timeout = timedelta(minutes=session_timeout_minutes)

    def get_session(self, node_id: str) -> Session:
        """Get or create a session for a node.

        Args:
            node_id: The Meshtastic node ID

        Returns:
            The session for the node (creates new if doesn't exist)
        """
        if node_id not in self._sessions:
            self._sessions[node_id] = Session(node_id=node_id)
        session = self._sessions[node_id]
        session.update_activity()
        return session

    def get_existing_session(self, node_id: str) -> Session | None:
        """Get an existing session without creating a new one.

        Args:
            node_id: The Meshtastic node ID

        Returns:
            The session if it exists, None otherwise
        """
        return self._sessions.get(node_id)

    def remove_session(self, node_id: str) -> bool:
        """Remove a session.

        Args:
            node_id: The Meshtastic node ID

        Returns:
            True if session was removed, False if it didn't exist
        """
        if node_id in self._sessions:
            del self._sessions[node_id]
            return True
        return False

    def cleanup_expired_sessions(self) -> int:
        """Remove sessions that have been inactive longer than the timeout.

        Returns:
            Number of sessions removed
        """
        now = datetime.now()
        expired_nodes = [
            node_id
            for node_id, session in self._sessions.items()
            if now - session.last_activity > self._timeout
        ]
        for node_id in expired_nodes:
            del self._sessions[node_id]
        return len(expired_nodes)

    @property
    def active_session_count(self) -> int:
        """Get the number of active sessions."""
        return len(self._sessions)

    def list_sessions(self) -> list[Session]:
        """Get a list of all active sessions.

        Returns:
            List of all Session objects
        """
        return list(self._sessions.values())
