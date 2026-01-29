"""Plugin interface - Abstract base class for all plugins."""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any

from meshgate.interfaces.node_context import NodeContext


@dataclass(frozen=True)
class PluginMetadata:
    """Metadata describing a plugin.

    Attributes:
        name: Human-readable plugin name (e.g., "LLM Assistant")
        description: Short description for menu display (e.g., "Ask AI questions")
        menu_number: Position in main menu (1, 2, 3...)
        commands: Plugin-specific commands (e.g., ("!refresh", "!clear"))
    """

    name: str
    description: str
    menu_number: int
    commands: tuple[str, ...] = field(default_factory=tuple)

    def __post_init__(self) -> None:
        """Validate metadata."""
        if not self.name:
            raise ValueError("Plugin name cannot be empty")
        if self.menu_number < 1:
            raise ValueError(f"Menu number must be >= 1, got {self.menu_number}")


@dataclass(frozen=True)
class PluginResponse:
    """Response from a plugin's handle method.

    Attributes:
        message: The response text to send back to the user
        plugin_state: Updated state to store for this node's session (optional)
        exit_plugin: If True, return user to main menu after this response
    """

    message: str
    plugin_state: dict[str, Any] | None = None
    exit_plugin: bool = False


class Plugin(ABC):
    """Abstract base class for all plugins.

    Plugins handle messages when a user has selected them from the main menu.
    Each plugin defines its own commands and maintains state per-node.

    Plugin Lifecycle:
        1. User selects plugin from menu (by number)
        2. get_welcome_message() is called and shown to user
        3. User messages are routed to handle() until they exit
        4. State persists between handle() calls via plugin_state dict
        5. User exits with !exit command, returning to main menu

    State Management:
        Plugins are stateless between calls. Use the plugin_state dict to
        persist data across messages. Return updated state in PluginResponse.

        Example:
            async def handle(self, message, context, plugin_state):
                history = plugin_state.get("history", [])
                history.append(message)
                return PluginResponse(
                    message="Got it!",
                    plugin_state={"history": history}
                )

    HTTP Plugins:
        For plugins that make HTTP requests, inherit from HTTPPluginBase
        in meshgate.plugins.base for common error handling.

    Example implementation:
        class MyPlugin(Plugin):
            @property
            def metadata(self) -> PluginMetadata:
                return PluginMetadata(
                    name="My Plugin",
                    description="Does something cool",
                    menu_number=5,
                    commands=("!do", "!undo")
                )

            def get_welcome_message(self) -> str:
                return "Welcome to My Plugin!\\nSend !help for commands."

            def get_help_text(self) -> str:
                return "Commands:\\n!do - Do it\\n!undo - Undo it\\n!exit - Return to menu"

            async def handle(
                self, message: str, context: NodeContext, plugin_state: dict[str, Any]
            ) -> PluginResponse:
                if message == "!do":
                    return PluginResponse(message="Done!")
                return PluginResponse(message="Unknown command")
    """

    @property
    @abstractmethod
    def metadata(self) -> PluginMetadata:
        """Return plugin metadata (name, description, menu_number, commands)."""

    @abstractmethod
    def get_welcome_message(self) -> str:
        """Message shown when user enters this plugin.

        Should include a brief description and hint about !help.
        """

    @abstractmethod
    def get_help_text(self) -> str:
        """Help text showing plugin-specific commands.

        Should list all available commands with descriptions.
        Always include !exit as it's universal.
        """

    @abstractmethod
    async def handle(
        self, message: str, context: NodeContext, plugin_state: dict[str, Any]
    ) -> PluginResponse:
        """Handle a message while user is in this plugin.

        Args:
            message: The incoming message text from the user
            context: Information about the sending node (id, name, location)
            plugin_state: Current state for this node's session with this plugin

        Returns:
            PluginResponse with the message to send and optional state updates
        """
