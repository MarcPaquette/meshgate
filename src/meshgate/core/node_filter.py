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
        self._allowlist = frozenset(self._normalize(n) for n in allowlist or ())
        self._denylist = frozenset(self._normalize(n) for n in denylist or ())
        self._require_allowlist = require_allowlist

    @staticmethod
    def _normalize(node_id: str) -> str:
        """Normalize a node ID for comparison.

        Meshtastic IDs are lowercase hex, so a config entry written as
        "!A4F2C1D0" would otherwise never match and silently allow the node
        it was meant to block.
        """
        return node_id.strip().lower()

    def is_allowed(self, node_id: str) -> bool:
        """Check if a node is allowed to connect.

        Args:
            node_id: The Meshtastic node ID to check

        Returns:
            True if the node is allowed, False otherwise
        """
        normalized = self._normalize(node_id)

        # Denylist always blocks. Logged at debug: rejection is an expected
        # steady state, and this runs on the packet-dispatch thread.
        if normalized in self._denylist:
            logger.debug(f"Node {node_id} rejected: in denylist")
            return False

        # If allowlist required, must be in allowlist
        if self._require_allowlist:
            if normalized not in self._allowlist:
                logger.debug(f"Node {node_id} rejected: not in allowlist")
                return False

        return True

    @property
    def allowlist(self) -> frozenset[str]:
        """Get the current allowlist."""
        return self._allowlist

    @property
    def denylist(self) -> frozenset[str]:
        """Get the current denylist."""
        return self._denylist

    @property
    def require_allowlist(self) -> bool:
        """Check if allowlist is required."""
        return self._require_allowlist
