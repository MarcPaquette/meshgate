"""Node filtering for allowlist/denylist enforcement."""

import logging

logger = logging.getLogger(__name__)


class NodeFilter:
    """Filters nodes based on allowlist and denylist.

    Filtering logic:
    1. Denylist always blocks (checked first)
    2. If require_allowlist=True, node must be in allowlist
    3. Otherwise allow

    Empty allowlist with require_allowlist=False means allow all (except denylisted).
    """

    def __init__(
        self,
        allowlist: list[str] | None = None,
        denylist: list[str] | None = None,
        require_allowlist: bool = False,
    ) -> None:
        """Initialize the node filter.

        Args:
            allowlist: List of allowed node IDs (empty = allow all if not required)
            denylist: List of denied node IDs (always blocks these)
            require_allowlist: If True, only allowlisted nodes can connect
        """
        self._allowlist: set[str] = set(allowlist) if allowlist else set()
        self._denylist: set[str] = set(denylist) if denylist else set()
        self._require_allowlist = require_allowlist

    def is_allowed(self, node_id: str) -> bool:
        """Check if a node is allowed to connect.

        Args:
            node_id: The Meshtastic node ID to check

        Returns:
            True if the node is allowed, False otherwise
        """
        # Denylist always blocks
        if node_id in self._denylist:
            logger.warning(f"Node {node_id} rejected: in denylist")
            return False

        # If allowlist required, must be in allowlist
        if self._require_allowlist:
            if node_id not in self._allowlist:
                logger.warning(f"Node {node_id} rejected: not in allowlist")
                return False

        return True

    @property
    def allowlist(self) -> set[str]:
        """Get the current allowlist."""
        return self._allowlist.copy()

    @property
    def denylist(self) -> set[str]:
        """Get the current denylist."""
        return self._denylist.copy()

    @property
    def require_allowlist(self) -> bool:
        """Check if allowlist is required."""
        return self._require_allowlist
