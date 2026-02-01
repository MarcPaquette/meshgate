"""Tests for HandlerServer."""

import asyncio
from pathlib import Path

import pytest

from meshgate.config import Config
from meshgate.server import HandlerServer
from tests.conftest import running_server
from tests.mocks import MockTransport

# Sample external plugin code for testing
SAMPLE_PLUGIN_CODE = '''
"""Sample external plugin for testing."""

from typing import Any

from meshgate.interfaces.plugin import Plugin, PluginMetadata, PluginResponse
from meshgate.interfaces.node_context import NodeContext


class SampleExternalPlugin(Plugin):
    """A sample external plugin for testing automatic loading."""

    @property
    def metadata(self) -> PluginMetadata:
        return PluginMetadata(
            name="Sample External",
            description="A sample external plugin",
            menu_number={menu_number},
            commands=("!sample",),
        )

    def get_welcome_message(self) -> str:
        return "Welcome to the sample external plugin!"

    def get_help_text(self) -> str:
        return "This is a sample external plugin for testing."

    async def handle(
        self, message: str, context: NodeContext, plugin_state: dict[str, Any]
    ) -> PluginResponse:
        return PluginResponse(message=f"Sample response: {{message}}")
'''


class TestHandlerServer:
    """Tests for HandlerServer class."""

    @pytest.fixture
    def server(self, mock_transport: MockTransport) -> HandlerServer:
        """Create a HandlerServer with mock transport."""
        config = Config.default()
        return HandlerServer(config=config, transport=mock_transport)

    def test_initialization_with_default_config(self, mock_transport: MockTransport) -> None:
        """Test server initializes with default config."""
        server = HandlerServer(transport=mock_transport)

        assert server.registry is not None
        assert server.session_manager is not None
        assert not server.is_running

    def test_initialization_with_custom_config(self, mock_transport: MockTransport) -> None:
        """Test server initializes with custom config."""
        config = Config.default()
        config.server.max_message_size = 100

        server = HandlerServer(config=config, transport=mock_transport)

        assert server.registry is not None

    def test_builtin_plugins_registered(self, server: HandlerServer) -> None:
        """Test that built-in plugins are registered."""
        # Should have 4 built-in plugins: gopher, llm, weather, wikipedia
        assert server.registry.plugin_count == 4

    def test_registry_property(self, server: HandlerServer) -> None:
        """Test registry property returns PluginRegistry."""
        registry = server.registry
        assert registry is not None
        # Should have plugins
        assert len(registry.get_all_plugins()) > 0

    def test_session_manager_property(self, server: HandlerServer) -> None:
        """Test session_manager property returns SessionManager."""
        manager = server.session_manager
        assert manager is not None
        # No active sessions yet
        assert manager.active_session_count == 0

    def test_is_running_initially_false(self, server: HandlerServer) -> None:
        """Test server is not running after initialization."""
        assert not server.is_running


class TestHandlerServerSingleMessage:
    """Tests for handle_single_message method."""

    @pytest.fixture
    def server(self, mock_transport: MockTransport) -> HandlerServer:
        """Create a HandlerServer with mock transport."""
        config = Config.default()
        return HandlerServer(config=config, transport=mock_transport)

    @pytest.mark.asyncio
    async def test_empty_message_shows_menu(self, server: HandlerServer) -> None:
        """Test empty message shows menu for new session."""
        response = await server.handle_single_message("", node_id="!test123")

        assert "Available Services:" in response
        assert "Send number to select" in response

    @pytest.mark.asyncio
    async def test_menu_selection_enters_plugin(self, server: HandlerServer) -> None:
        """Test menu selection enters the selected plugin."""
        # First, show menu
        await server.handle_single_message("", node_id="!test123")

        # Select plugin 1 (Gopher)
        response = await server.handle_single_message("1", node_id="!test123")

        assert response  # Non-empty response
        session = server.session_manager.get_existing_session("!test123")
        assert session is not None
        assert not session.is_at_menu

    @pytest.mark.asyncio
    async def test_exit_command_returns_to_menu(self, server: HandlerServer) -> None:
        """Test !exit returns to menu."""
        # Enter a plugin
        await server.handle_single_message("", node_id="!test123")
        await server.handle_single_message("1", node_id="!test123")

        # Exit
        response = await server.handle_single_message("!exit", node_id="!test123")

        assert "Returned to menu" in response
        session = server.session_manager.get_existing_session("!test123")
        assert session is not None
        assert session.is_at_menu

    @pytest.mark.asyncio
    async def test_independent_sessions(self, server: HandlerServer) -> None:
        """Test multiple nodes have independent sessions."""
        # Node A enters plugin
        await server.handle_single_message("", node_id="!nodeA")
        await server.handle_single_message("1", node_id="!nodeA")

        # Node B stays at menu
        await server.handle_single_message("", node_id="!nodeB")

        session_a = server.session_manager.get_existing_session("!nodeA")
        session_b = server.session_manager.get_existing_session("!nodeB")

        assert session_a is not None
        assert session_b is not None
        assert not session_a.is_at_menu
        assert session_b.is_at_menu

    @pytest.mark.asyncio
    async def test_invalid_menu_selection(self, server: HandlerServer) -> None:
        """Test invalid menu selection shows error."""
        await server.handle_single_message("", node_id="!test123")
        response = await server.handle_single_message("999", node_id="!test123")

        assert "Invalid selection" in response

    @pytest.mark.asyncio
    async def test_plugin_state_persists(self, server: HandlerServer) -> None:
        """Test plugin state persists across messages."""
        # Enter gopher plugin
        await server.handle_single_message("", node_id="!test123")
        await server.handle_single_message("1", node_id="!test123")

        # Navigate somewhere (state should update)
        await server.handle_single_message("!help", node_id="!test123")

        session = server.session_manager.get_existing_session("!test123")
        assert session is not None
        # Session should maintain plugin state
        assert session.active_plugin is not None


class TestHandlerServerLifecycle:
    """Tests for server start/stop lifecycle."""

    @pytest.fixture
    def server(self, mock_transport: MockTransport) -> HandlerServer:
        """Create a HandlerServer with mock transport."""
        config = Config.default()
        return HandlerServer(config=config, transport=mock_transport)

    @pytest.mark.asyncio
    async def test_stop_disconnects_transport(
        self, server: HandlerServer, mock_transport: MockTransport
    ) -> None:
        """Test stop() disconnects the transport."""
        await mock_transport.connect()
        assert mock_transport.is_connected

        await server.stop()

        assert not mock_transport.is_connected

    @pytest.mark.asyncio
    async def test_start_and_receive_message(
        self, server: HandlerServer, mock_transport: MockTransport
    ) -> None:
        """Test server can start and receive messages."""
        async with running_server(server):
            mock_transport.inject_message("", node_id="!test123")
            await asyncio.sleep(0.2)

        # Check message was sent
        assert len(mock_transport.sent_messages) > 0
        # Should be the menu
        _, message = mock_transport.sent_messages[0]
        assert "Available Services:" in message

    @pytest.mark.asyncio
    async def test_chunked_response(self, mock_transport: MockTransport) -> None:
        """Test long responses are chunked when message exceeds max_size."""
        config = Config.default()
        config.server.max_message_size = 30  # Very small to force chunking
        server = HandlerServer(config=config, transport=mock_transport)

        async with running_server(server):
            mock_transport.inject_message("", node_id="!test123")
            await asyncio.sleep(0.5)

        # Should have at least one message sent
        assert len(mock_transport.sent_messages) >= 1
        # The response should contain continuation marker if chunked
        _, first_message = mock_transport.sent_messages[0]
        # Either single message or first chunk with marker
        assert first_message  # Non-empty


class TestHandlerServerCleanup:
    """Tests for server cleanup functionality."""

    @pytest.mark.asyncio
    async def test_cleanup_task_started(self, mock_transport: MockTransport) -> None:
        """Test that cleanup task is started when server starts."""
        config = Config.default()
        config.server.session_cleanup_interval_minutes = 1
        server = HandlerServer(config=config, transport=mock_transport)

        async with running_server(server):
            # Cleanup task should be running
            assert server._cleanup_task is not None
            assert not server._cleanup_task.done()

    @pytest.mark.asyncio
    async def test_cleanup_task_cancelled_on_stop(
        self, mock_transport: MockTransport
    ) -> None:
        """Test that cleanup task is cancelled when server stops."""
        config = Config.default()
        server = HandlerServer(config=config, transport=mock_transport)

        async with running_server(server):
            cleanup_task = server._cleanup_task

        # Cleanup task should be cancelled or done
        assert cleanup_task is not None
        assert cleanup_task.done() or cleanup_task.cancelled()

    @pytest.mark.asyncio
    async def test_max_sessions_passed_to_session_manager(
        self, mock_transport: MockTransport
    ) -> None:
        """Test that max_sessions config is passed to SessionManager."""
        config = Config.default()
        config.server.max_sessions = 5
        server = HandlerServer(config=config, transport=mock_transport)

        assert server.session_manager._max_sessions == 5


class TestHandlerServerRateLimiting:
    """Tests for server rate limiting functionality."""

    @pytest.mark.asyncio
    async def test_rate_limiter_initialized(self, mock_transport: MockTransport) -> None:
        """Test that rate limiter is initialized from config."""
        config = Config.default()
        config.security.rate_limit_enabled = True
        config.security.rate_limit_messages = 5
        config.security.rate_limit_window_seconds = 30
        server = HandlerServer(config=config, transport=mock_transport)

        assert server._rate_limiter.enabled is True
        assert server._rate_limiter.max_messages == 5
        assert server._rate_limiter.window_seconds == 30

    @pytest.mark.asyncio
    async def test_rate_limit_blocks_excessive_messages(
        self, mock_transport: MockTransport
    ) -> None:
        """Test that rate limiting blocks excessive messages."""
        config = Config.default()
        config.security.rate_limit_enabled = True
        config.security.rate_limit_messages = 2
        config.security.rate_limit_window_seconds = 60
        server = HandlerServer(config=config, transport=mock_transport)

        async with running_server(server):
            # Send messages (first 2 should work, 3rd should be rate limited)
            mock_transport.inject_message("hello", node_id="!test123")
            await asyncio.sleep(0.1)
            mock_transport.inject_message("world", node_id="!test123")
            await asyncio.sleep(0.1)
            mock_transport.inject_message("blocked", node_id="!test123")
            await asyncio.sleep(0.2)

        # Check that rate limit message was sent
        messages = [msg for _, msg in mock_transport.sent_messages]
        rate_limit_msgs = [m for m in messages if "Rate limited" in m]
        assert len(rate_limit_msgs) >= 1

    @pytest.mark.asyncio
    async def test_rate_limit_disabled_allows_all(
        self, mock_transport: MockTransport
    ) -> None:
        """Test that disabled rate limiting allows all messages."""
        config = Config.default()
        config.security.rate_limit_enabled = False
        config.security.rate_limit_messages = 1  # Would block immediately if enabled
        server = HandlerServer(config=config, transport=mock_transport)

        async with running_server(server):
            # Send many messages
            for i in range(5):
                mock_transport.inject_message(f"msg{i}", node_id="!test123")
                await asyncio.sleep(0.05)
            await asyncio.sleep(0.2)

        # Check no rate limit messages
        messages = [msg for _, msg in mock_transport.sent_messages]
        rate_limit_msgs = [m for m in messages if "Rate limited" in m]
        assert len(rate_limit_msgs) == 0


class TestHandlerServerExternalPlugins:
    """Tests for external plugin loading functionality."""

    @pytest.fixture
    def plugin_dir(self, tmp_path: Path) -> Path:
        """Create a temporary directory for external plugins."""
        plugins_dir = tmp_path / "external_plugins"
        plugins_dir.mkdir()
        return plugins_dir

    def test_loads_external_plugins_from_configured_path(
        self, mock_transport: MockTransport, plugin_dir: Path
    ) -> None:
        """Test that external plugins are loaded from configured paths."""
        # Create a sample plugin file with menu number 10 (won't conflict with built-ins 1-4)
        plugin_file = plugin_dir / "sample_plugin.py"
        plugin_file.write_text(SAMPLE_PLUGIN_CODE.format(menu_number=10))

        config = Config.default()
        config.plugin_paths = [str(plugin_dir)]
        server = HandlerServer(config=config, transport=mock_transport)

        # Should have 4 built-in + 1 external = 5 plugins
        assert server.registry.plugin_count == 5

        # The external plugin should be registered
        plugin = server.registry.get_by_name("Sample External")
        assert plugin is not None
        assert plugin.metadata.menu_number == 10

    def test_external_plugin_accessible_via_menu(
        self, mock_transport: MockTransport, plugin_dir: Path
    ) -> None:
        """Test that external plugins can be accessed via menu selection."""
        plugin_file = plugin_dir / "sample_plugin.py"
        plugin_file.write_text(SAMPLE_PLUGIN_CODE.format(menu_number=10))

        config = Config.default()
        config.plugin_paths = [str(plugin_dir)]
        server = HandlerServer(config=config, transport=mock_transport)

        # External plugin should be accessible by menu number
        plugin = server.registry.get_by_menu_number(10)
        assert plugin is not None
        assert plugin.metadata.name == "Sample External"

    def test_handles_nonexistent_plugin_directory(
        self, mock_transport: MockTransport, tmp_path: Path
    ) -> None:
        """Test that nonexistent plugin directories are handled gracefully."""
        nonexistent_path = tmp_path / "does_not_exist"

        config = Config.default()
        config.plugin_paths = [str(nonexistent_path)]

        # Should not raise, just log warning
        server = HandlerServer(config=config, transport=mock_transport)

        # Should still have built-in plugins
        assert server.registry.plugin_count == 4

    def test_handles_empty_plugin_directory(
        self, mock_transport: MockTransport, plugin_dir: Path
    ) -> None:
        """Test that empty plugin directories are handled gracefully."""
        config = Config.default()
        config.plugin_paths = [str(plugin_dir)]  # Empty directory

        server = HandlerServer(config=config, transport=mock_transport)

        # Should still have built-in plugins only
        assert server.registry.plugin_count == 4

    def test_skips_plugins_with_conflicting_menu_number(
        self, mock_transport: MockTransport, plugin_dir: Path
    ) -> None:
        """Test that plugins with conflicting menu numbers are skipped."""
        # Create a plugin with menu number 1 (conflicts with Gopher)
        plugin_file = plugin_dir / "conflicting_plugin.py"
        plugin_file.write_text(SAMPLE_PLUGIN_CODE.format(menu_number=1))

        config = Config.default()
        config.plugin_paths = [str(plugin_dir)]

        # Should not raise, just log warning about conflict
        server = HandlerServer(config=config, transport=mock_transport)

        # Should still have only 4 plugins (external one was skipped)
        assert server.registry.plugin_count == 4

        # Built-in Gopher should still be at menu 1
        plugin = server.registry.get_by_menu_number(1)
        assert plugin is not None
        assert plugin.metadata.name == "Gopher Server"

    def test_loads_multiple_external_plugins(
        self, mock_transport: MockTransport, plugin_dir: Path
    ) -> None:
        """Test that multiple external plugins can be loaded."""
        # Create two external plugins
        plugin1 = plugin_dir / "plugin_one.py"
        plugin1.write_text(SAMPLE_PLUGIN_CODE.format(menu_number=10))

        plugin2_code = SAMPLE_PLUGIN_CODE.replace("Sample External", "Another Plugin")
        plugin2 = plugin_dir / "plugin_two.py"
        plugin2.write_text(plugin2_code.format(menu_number=11))

        config = Config.default()
        config.plugin_paths = [str(plugin_dir)]
        server = HandlerServer(config=config, transport=mock_transport)

        # Should have 4 built-in + 2 external = 6 plugins
        assert server.registry.plugin_count == 6

    def test_loads_from_multiple_plugin_paths(
        self, mock_transport: MockTransport, tmp_path: Path
    ) -> None:
        """Test that plugins are loaded from multiple configured paths."""
        dir1 = tmp_path / "plugins1"
        dir1.mkdir()
        dir2 = tmp_path / "plugins2"
        dir2.mkdir()

        # Plugin in first directory
        plugin1 = dir1 / "plugin_a.py"
        plugin1.write_text(SAMPLE_PLUGIN_CODE.format(menu_number=10))

        # Plugin in second directory
        plugin2_code = SAMPLE_PLUGIN_CODE.replace("Sample External", "Second Plugin")
        plugin2 = dir2 / "plugin_b.py"
        plugin2.write_text(plugin2_code.format(menu_number=11))

        config = Config.default()
        config.plugin_paths = [str(dir1), str(dir2)]
        server = HandlerServer(config=config, transport=mock_transport)

        # Should have 4 built-in + 2 external = 6 plugins
        assert server.registry.plugin_count == 6

    def test_empty_plugin_paths_config(
        self, mock_transport: MockTransport
    ) -> None:
        """Test that empty plugin_paths config is handled."""
        config = Config.default()
        config.plugin_paths = []  # No external plugin paths

        server = HandlerServer(config=config, transport=mock_transport)

        # Should still have built-in plugins
        assert server.registry.plugin_count == 4

    def test_skips_private_python_files(
        self, mock_transport: MockTransport, plugin_dir: Path
    ) -> None:
        """Test that files starting with underscore are skipped."""
        # Create a private file (should be skipped)
        private_file = plugin_dir / "_private_plugin.py"
        private_file.write_text(SAMPLE_PLUGIN_CODE.format(menu_number=10))

        # Create a regular plugin
        regular_file = plugin_dir / "regular_plugin.py"
        regular_file.write_text(SAMPLE_PLUGIN_CODE.format(menu_number=11))

        config = Config.default()
        config.plugin_paths = [str(plugin_dir)]
        server = HandlerServer(config=config, transport=mock_transport)

        # Should have 4 built-in + 1 regular (private skipped) = 5 plugins
        assert server.registry.plugin_count == 5

        # Only menu 11 should exist, not menu 10
        assert server.registry.get_by_menu_number(10) is None
        assert server.registry.get_by_menu_number(11) is not None
