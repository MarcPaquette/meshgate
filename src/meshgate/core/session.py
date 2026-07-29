"""Session dataclass for tracking per-node state."""

import json
import sys
import time
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any


def _state_size_bytes(state: dict[str, Any]) -> int:
    """Measure the serialized size of plugin state.

    sys.getsizeof is shallow - for {"history": [...]} it reports the dict plus
    the list's pointer array and ignores the contents entirely, under-reporting
    real payloads by orders of magnitude. Plugin state is JSON-shaped by
    construction, so serializing it is both accurate and cheap enough.
    """
    try:
        return len(json.dumps(state, default=str).encode("utf-8"))
    except (TypeError, ValueError, RecursionError):
        # Unmeasurable state (e.g. circular references) is reported as
        # oversized so it is rejected rather than silently let through.
        return sys.maxsize


@dataclass
class Session:
    """Session state for a single Meshtastic node.

    Each node gets its own independent session. Node A can be in the Weather plugin
    while Node B is browsing Gopher - they don't affect each other.

    Attributes:
        node_id: Unique Meshtastic node ID (e.g., "!abc12345")
        active_plugin: Name of the currently active plugin, or None if at main menu
        plugin_state: Plugin-specific state dictionary
        last_activity: Timestamp of last activity for session timeout/cleanup
    """

    node_id: str
    active_plugin: str | None = None
    plugin_state: dict[str, Any] = field(default_factory=dict)
    last_activity: datetime = field(default_factory=datetime.now)
    # Elapsed-time comparisons use a monotonic clock: wall-clock deltas go
    # negative across a DST fall-back or an NTP step, which would either keep
    # sessions alive forever or expire them all at once.
    last_activity_monotonic: float = field(default_factory=time.monotonic)

    def __post_init__(self) -> None:
        """Validate session."""
        if not self.node_id:
            raise ValueError("node_id cannot be empty")

    def update_activity(self) -> None:
        """Update the last activity timestamps."""
        self.last_activity = datetime.now()
        self.last_activity_monotonic = time.monotonic()

    def idle_seconds(self) -> float:
        """Seconds since this session was last active."""
        return time.monotonic() - self.last_activity_monotonic

    def enter_plugin(self, plugin_name: str) -> None:
        """Enter a plugin, clearing any previous plugin state.

        Args:
            plugin_name: Name of the plugin to enter
        """
        self.active_plugin = plugin_name
        self.plugin_state = {}
        self.update_activity()

    def exit_plugin(self) -> None:
        """Exit current plugin, returning to main menu."""
        self.active_plugin = None
        self.plugin_state = {}
        self.update_activity()

    def update_plugin_state(self, state: dict[str, Any], max_bytes: int = 0) -> bool:
        """Update the plugin-specific state.

        Args:
            state: State dictionary to merge with existing state
            max_bytes: Maximum allowed state size in bytes (0 = unlimited)

        Returns:
            True if update succeeded, False if state would exceed limit
        """
        if max_bytes > 0:
            merged = {**self.plugin_state, **state}
            if _state_size_bytes(merged) > max_bytes:
                return False
            # Reuse the merged dict rather than merging a second time.
            self.plugin_state = merged
        else:
            self.plugin_state.update(state)

        self.update_activity()
        return True

    @property
    def is_at_menu(self) -> bool:
        """Check if user is at the main menu (not in a plugin)."""
        return self.active_plugin is None
