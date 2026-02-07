"""Message router for handling menu selection and plugin routing."""

import logging

from meshgate.core.plugin_registry import PluginRegistry
from meshgate.core.session import Session
from meshgate.interfaces.node_context import NodeContext
from meshgate.interfaces.plugin import PluginResponse

logger = logging.getLogger(__name__)


class MessageRouter:
    """Routes messages to the appropriate plugin or handles menu navigation.

    Flow:
    1. At main menu: Number selects plugin, enters it, shows welcome
    2. Inside plugin: All messages go to active plugin's handle()
    3. "!exit": Universal command, returns to main menu
    4. "!help": Shows plugin-specific help (plugin implements this)
    5. "!menu": Shows main menu even while in plugin
    """

    # Universal commands handled by router
    EXIT_COMMAND = "!exit"
    MENU_COMMAND = "!menu"
    HELP_COMMAND = "!help"

    def __init__(self, registry: PluginRegistry, max_state_bytes: int = 0) -> None:
        """Initialize the message router.

        Args:
            registry: The plugin registry containing available plugins
            max_state_bytes: Maximum allowed plugin state size in bytes (0 = unlimited)
        """
        self._registry = registry
        self._max_state_bytes = max_state_bytes

    def _render_menu(self) -> str:
        """Render the main menu showing available plugins.

        Returns:
            The formatted menu string
        """
        lines = ["Available Services:"]
        for plugin in self._registry.get_all_plugins():
            meta = plugin.metadata
            lines.append(f"{meta.menu_number}. {meta.name}")

        lines.append("")
        lines.append("Send number to select")
        return "\n".join(lines)

    async def route(self, message: str, session: Session, context: NodeContext) -> PluginResponse:
        """Route a message to the appropriate handler.

        Args:
            message: The incoming message text
            session: The node's session state
            context: Information about the sending node

        Returns:
            PluginResponse with the message to send back
        """
        message = message.strip()

        # Universal commands work anywhere
        if message.lower() == self.EXIT_COMMAND:
            return self._handle_exit(session)

        if message.lower() == self.MENU_COMMAND:
            return PluginResponse(message=self._render_menu())

        # At main menu - handle menu selection
        if session.is_at_menu:
            return await self._handle_menu_selection(message, session)

        # Inside a plugin - route to plugin
        return await self._handle_plugin_message(message, session, context)

    def _handle_exit(self, session: Session) -> PluginResponse:
        """Handle the !exit command.

        Args:
            session: The node's session state

        Returns:
            PluginResponse with menu
        """
        session.exit_plugin()
        return PluginResponse(message=f"Returned to menu.\n\n{self._render_menu()}")

    async def _handle_menu_selection(self, message: str, session: Session) -> PluginResponse:
        """Handle menu number selection.

        Args:
            message: The message (should be a number)
            session: The node's session state

        Returns:
            PluginResponse with plugin welcome or error
        """
        try:
            menu_number = int(message)
        except ValueError:
            # Not a number - show menu again
            menu = self._render_menu()
            return PluginResponse(message=f"Invalid selection. Please send a number.\n\n{menu}")

        plugin = self._registry.get_by_menu_number(menu_number)
        if plugin is None:
            return PluginResponse(
                message=f"Invalid selection '{menu_number}'.\n\n{self._render_menu()}"
            )

        # Enter the plugin
        session.enter_plugin(plugin.metadata.name)
        return PluginResponse(message=plugin.get_welcome_message())

    async def _handle_plugin_message(
        self, message: str, session: Session, context: NodeContext
    ) -> PluginResponse:
        """Route message to the active plugin.

        Args:
            message: The message text
            session: The node's session state
            context: Information about the sending node

        Returns:
            PluginResponse from the plugin
        """
        plugin = self._registry.get_by_name(session.active_plugin)
        if plugin is None:
            # Plugin no longer exists - return to menu
            session.exit_plugin()
            return PluginResponse(message=f"Plugin not available.\n\n{self._render_menu()}")

        # Handle !help specially - show plugin's help text
        if message.lower() == self.HELP_COMMAND:
            return PluginResponse(message=plugin.get_help_text())

        # Route to plugin
        response: PluginResponse = await plugin.handle(message, context, session.plugin_state)

        # Update state if provided
        if response.plugin_state is not None:
            if not session.update_plugin_state(response.plugin_state, self._max_state_bytes):
                logger.warning(
                    f"Plugin state exceeded limit for {session.node_id} "
                    f"(limit: {self._max_state_bytes} bytes)"
                )

        # Check if plugin wants to exit
        if response.exit_plugin:
            session.exit_plugin()
            return PluginResponse(message=f"{response.message}\n\n{self._render_menu()}")

        return response

    def get_menu(self) -> str:
        """Get the main menu text.

        Returns:
            The formatted menu string
        """
        return self._render_menu()
