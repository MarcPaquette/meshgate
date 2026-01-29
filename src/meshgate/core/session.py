"""Session dataclass for tracking per-node state."""

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any


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

    def __post_init__(self) -> None:
        """Validate session."""
        if not self.node_id:
            raise ValueError("node_id cannot be empty")

    def update_activity(self) -> None:
        """Update the last activity timestamp."""
        self.last_activity = datetime.now()

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

    def update_plugin_state(self, state: dict[str, Any]) -> None:
        """Update the plugin-specific state.

        Args:
            state: State dictionary to merge with existing state
        """
        self.plugin_state.update(state)
        self.update_activity()

    @property
    def is_at_menu(self) -> bool:
        """Check if user is at the main menu (not in a plugin)."""
        return self.active_plugin is None
