"""Session manager for multi-node session management."""

import logging
from collections import OrderedDict

from meshgate.core.session import Session

logger = logging.getLogger(__name__)


class SessionManager:
    """Manages sessions for all connected nodes.

    - Creates new session when unknown node sends first message
    - Retrieves existing session by node_id
    - Each node has completely independent state
    - Expired sessions cleaned up after configurable timeout
    - Optionally enforces max session limit with LRU eviction

    Example with multiple nodes:
        Node !abc → sends "2" → enters LLM plugin
        Node !xyz → sends "3" → enters Weather plugin
        Node !abc → sends "hello" → handled by LLM (still in LLM)
        Node !xyz → sends "!exit" → returns to menu (abc unaffected)
    """

    def __init__(self, session_timeout_minutes: int = 60, max_sessions: int = 0) -> None:
        """Initialize the session manager.

        Args:
            session_timeout_minutes: Time in minutes before inactive sessions are cleaned up
            max_sessions: Maximum number of concurrent sessions (0 = unlimited)
        """
        # Ordered so the least recently active session is always first,
        # making eviction O(1) instead of a min() scan per new node.
        self._sessions: OrderedDict[str, Session] = OrderedDict()
        self._timeout_seconds = session_timeout_minutes * 60
        self._max_sessions = max_sessions

    def get_session(self, node_id: str) -> Session:
        """Get or create a session for a node.

        If max_sessions is set and creating a new session would exceed the limit,
        the oldest (least recently active) session is evicted first.

        Args:
            node_id: The Meshtastic node ID

        Returns:
            The session for the node (creates new if doesn't exist)
        """
        if node_id not in self._sessions:
            # Enforce max sessions limit before creating new session
            if self._max_sessions > 0:
                while len(self._sessions) >= self._max_sessions:
                    if self._evict_oldest_session() is None:
                        break
            self._sessions[node_id] = Session(node_id=node_id)

        session = self._sessions[node_id]
        session.update_activity()
        # Most recently active moves to the end.
        self._sessions.move_to_end(node_id)
        return session

    def _evict_oldest_session(self) -> str | None:
        """Evict the oldest (least recently active) session.

        Returns:
            The node_id of the evicted session, or None if no sessions to evict
        """
        if not self._sessions:
            return None

        oldest_node_id, _ = self._sessions.popitem(last=False)
        logger.info(f"Evicted oldest session for node {oldest_node_id} (max sessions reached)")
        return oldest_node_id

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
        expired_nodes = [
            node_id
            for node_id, session in self._sessions.items()
            if session.idle_seconds() > self._timeout_seconds
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
