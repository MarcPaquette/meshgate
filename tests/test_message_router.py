"""Tests for message router."""

from typing import Any

import pytest

from meshgate.core.message_router import MessageRouter
from meshgate.core.plugin_registry import PluginRegistry
from meshgate.core.session import Session
from meshgate.interfaces.node_context import NodeContext
from meshgate.interfaces.plugin import Plugin, PluginMetadata, PluginResponse
from tests.mocks import MockPlugin


class ExceptionPlugin(Plugin):
    """A plugin that raises an exception when handle() is called."""

    @property
    def metadata(self) -> PluginMetadata:
        return PluginMetadata(
            name="Exception Plugin",
            description="A plugin that always raises",
            menu_number=99,
        )

    def get_welcome_message(self) -> str:
        return "Welcome to crash city"

    def get_help_text(self) -> str:
        return "This plugin will crash"

    async def handle(
        self, message: str, context: NodeContext, plugin_state: dict[str, Any]
    ) -> PluginResponse:
        raise RuntimeError("Plugin crashed!")


class TestMessageRouter:
    """Tests for MessageRouter class."""

    def test_get_menu_empty_registry(self) -> None:
        """Test get_menu with no plugins."""
        registry = PluginRegistry()
        router = MessageRouter(registry)

        result = router.get_menu()
        assert "Available Services:" in result
        assert "Send number to select" in result

    def test_get_menu_with_plugins(self) -> None:
        """Test get_menu with plugins."""
        registry = PluginRegistry()
        registry.register(MockPlugin(name="Gopher Server", menu_number=1))
        registry.register(MockPlugin(name="LLM Assistant", menu_number=2))
        router = MessageRouter(registry)

        result = router.get_menu()

        assert "Available Services:" in result
        assert "1. Gopher Server" in result
        assert "2. LLM Assistant" in result
        assert "Send number to select" in result

    @pytest.fixture
    def router_with_plugin(self) -> tuple[MessageRouter, MockPlugin, PluginRegistry]:
        """Create router with a mock plugin."""
        registry = PluginRegistry()
        plugin = MockPlugin(name="Test Plugin", menu_number=1, welcome="Welcome!")
        registry.register(plugin)
        router = MessageRouter(registry)
        return router, plugin, registry

    @pytest.mark.asyncio
    async def test_menu_selection_enters_plugin(
        self, router_with_plugin: tuple[MessageRouter, MockPlugin, PluginRegistry]
    ) -> None:
        """Test that number selection enters a plugin."""
        router, plugin, _ = router_with_plugin
        session = Session(node_id="!test123")
        context = NodeContext(node_id="!test123")

        response = await router.route("1", session, context)

        assert "Welcome!" in response.message
        assert session.active_plugin == "Test Plugin"
        assert not session.is_at_menu

    @pytest.mark.asyncio
    async def test_invalid_menu_selection(
        self, router_with_plugin: tuple[MessageRouter, MockPlugin, PluginRegistry]
    ) -> None:
        """Test invalid menu selection shows error."""
        router, _, _ = router_with_plugin
        session = Session(node_id="!test123")
        context = NodeContext(node_id="!test123")

        response = await router.route("99", session, context)

        assert "Invalid selection" in response.message
        assert session.is_at_menu

    @pytest.mark.asyncio
    async def test_non_number_at_menu(
        self, router_with_plugin: tuple[MessageRouter, MockPlugin, PluginRegistry]
    ) -> None:
        """Test non-number input at menu shows error."""
        router, _, _ = router_with_plugin
        session = Session(node_id="!test123")
        context = NodeContext(node_id="!test123")

        response = await router.route("hello", session, context)

        assert "Invalid selection" in response.message
        assert "send a number" in response.message.lower()

    @pytest.mark.asyncio
    async def test_exit_command(
        self, router_with_plugin: tuple[MessageRouter, MockPlugin, PluginRegistry]
    ) -> None:
        """Test !exit returns to menu."""
        router, _, _ = router_with_plugin
        session = Session(node_id="!test123")
        session.enter_plugin("Test Plugin")
        context = NodeContext(node_id="!test123")

        response = await router.route("!exit", session, context)

        assert "Returned to menu" in response.message
        assert session.is_at_menu

    @pytest.mark.asyncio
    async def test_exit_case_insensitive(
        self, router_with_plugin: tuple[MessageRouter, MockPlugin, PluginRegistry]
    ) -> None:
        """Test !exit is case insensitive."""
        router, _, _ = router_with_plugin
        session = Session(node_id="!test123")
        session.enter_plugin("Test Plugin")
        context = NodeContext(node_id="!test123")

        await router.route("!EXIT", session, context)

        assert session.is_at_menu

    @pytest.mark.asyncio
    async def test_menu_command(
        self, router_with_plugin: tuple[MessageRouter, MockPlugin, PluginRegistry]
    ) -> None:
        """Test !menu shows menu."""
        router, _, _ = router_with_plugin
        session = Session(node_id="!test123")
        session.enter_plugin("Test Plugin")
        context = NodeContext(node_id="!test123")

        response = await router.route("!menu", session, context)

        assert "Available Services:" in response.message
        # Should NOT exit plugin
        assert not session.is_at_menu

    @pytest.mark.asyncio
    async def test_help_in_plugin(
        self, router_with_plugin: tuple[MessageRouter, MockPlugin, PluginRegistry]
    ) -> None:
        """Test !help shows plugin help."""
        router, plugin, _ = router_with_plugin
        session = Session(node_id="!test123")
        session.enter_plugin("Test Plugin")
        context = NodeContext(node_id="!test123")

        response = await router.route("!help", session, context)

        assert response.message == plugin.get_help_text()

    @pytest.mark.asyncio
    async def test_message_routed_to_plugin(
        self, router_with_plugin: tuple[MessageRouter, MockPlugin, PluginRegistry]
    ) -> None:
        """Test messages are routed to active plugin."""
        router, plugin, _ = router_with_plugin
        session = Session(node_id="!test123")
        session.enter_plugin("Test Plugin")
        context = NodeContext(node_id="!test123")

        response = await router.route("test message", session, context)

        # Verify response comes from plugin (contains mock response text)
        assert "Mock response" in response.message
        # Verify plugin received the message
        assert plugin.handle_calls  # At least one call
        assert plugin.handle_calls[-1][0] == "test message"

    @pytest.mark.asyncio
    async def test_plugin_state_updated(
        self, router_with_plugin: tuple[MessageRouter, MockPlugin, PluginRegistry]
    ) -> None:
        """Test plugin state is updated after handle."""
        router, _, _ = router_with_plugin
        session = Session(node_id="!test123")
        session.enter_plugin("Test Plugin")
        context = NodeContext(node_id="!test123")

        await router.route("hello", session, context)

        assert session.plugin_state.get("last_message") == "hello"

    @pytest.mark.asyncio
    async def test_whitespace_stripped(
        self, router_with_plugin: tuple[MessageRouter, MockPlugin, PluginRegistry]
    ) -> None:
        """Test that message whitespace is stripped."""
        router, _, _ = router_with_plugin
        session = Session(node_id="!test123")
        context = NodeContext(node_id="!test123")

        await router.route("  1  ", session, context)

        assert session.active_plugin == "Test Plugin"

    @pytest.mark.asyncio
    async def test_plugin_throws_exception(self) -> None:
        """Test that plugin exceptions bubble up."""
        registry = PluginRegistry()
        registry.register(ExceptionPlugin())
        router = MessageRouter(registry)

        session = Session(node_id="!test123")
        session.enter_plugin("Exception Plugin")
        context = NodeContext(node_id="!test123")

        # The exception should propagate up
        with pytest.raises(RuntimeError, match="Plugin crashed"):
            await router.route("test", session, context)

    @pytest.mark.asyncio
    async def test_empty_registry_menu_selection(self) -> None:
        """Test menu selection with empty registry."""
        registry = PluginRegistry()
        router = MessageRouter(registry)

        session = Session(node_id="!test123")
        context = NodeContext(node_id="!test123")

        response = await router.route("1", session, context)

        assert "Invalid selection" in response.message
        assert session.is_at_menu

    @pytest.mark.asyncio
    async def test_plugin_removed_while_in_session(self) -> None:
        """Test handling when plugin is removed while user is in it."""
        registry = PluginRegistry()
        plugin = MockPlugin(name="Removable Plugin", menu_number=5)
        registry.register(plugin)
        router = MessageRouter(registry)

        session = Session(node_id="!test123")
        session.enter_plugin("Removable Plugin")
        context = NodeContext(node_id="!test123")

        # Remove the plugin while user is in session
        registry.unregister("Removable Plugin")

        response = await router.route("test message", session, context)

        assert "not available" in response.message.lower()
        assert session.is_at_menu

    @pytest.mark.asyncio
    async def test_exit_at_menu_is_noop(
        self, router_with_plugin: tuple[MessageRouter, MockPlugin, PluginRegistry]
    ) -> None:
        """Test !exit at menu doesn't cause issues."""
        router, _, _ = router_with_plugin
        session = Session(node_id="!test123")
        context = NodeContext(node_id="!test123")

        response = await router.route("!exit", session, context)

        assert "Returned to menu" in response.message
        assert session.is_at_menu

    @pytest.mark.asyncio
    async def test_plugin_state_passed_to_plugin(
        self, router_with_plugin: tuple[MessageRouter, MockPlugin, PluginRegistry]
    ) -> None:
        """Test that existing plugin state is passed to plugin handle."""
        router, plugin, _ = router_with_plugin
        session = Session(node_id="!test123")
        session.enter_plugin("Test Plugin")
        session.update_plugin_state({"existing": "state"})
        context = NodeContext(node_id="!test123")

        await router.route("message", session, context)

        # Verify the state was passed to handle
        assert len(plugin.handle_calls) == 1
        passed_state = plugin.handle_calls[0][2]
        assert passed_state.get("existing") == "state"
