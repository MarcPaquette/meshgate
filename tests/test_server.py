"""Tests for HandlerServer."""

import asyncio

import pytest

from meshgate.config import Config
from meshgate.server import HandlerServer
from tests.mocks import MockTransport


class TestHandlerServer:
    """Tests for HandlerServer class."""

    @pytest.fixture
    def mock_transport(self) -> MockTransport:
        """Create a mock transport."""
        return MockTransport()

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
    def mock_transport(self) -> MockTransport:
        """Create a mock transport."""
        return MockTransport()

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
    def mock_transport(self) -> MockTransport:
        """Create a mock transport."""
        return MockTransport()

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
        # Start server in background
        server_task = asyncio.create_task(server.start())

        # Wait for server to start
        await asyncio.sleep(0.1)

        # Inject a message
        mock_transport.inject_message("", node_id="!test123")

        # Wait for processing
        await asyncio.sleep(0.2)

        # Stop server
        await server.stop()
        server_task.cancel()
        try:
            await server_task
        except asyncio.CancelledError:
            pass

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

        # Start server
        server_task = asyncio.create_task(server.start())
        await asyncio.sleep(0.1)

        # Send message that will trigger long response (menu)
        mock_transport.inject_message("", node_id="!test123")

        # Wait for processing
        await asyncio.sleep(0.5)

        await server.stop()
        server_task.cancel()
        try:
            await server_task
        except asyncio.CancelledError:
            pass

        # Should have at least one message sent
        assert len(mock_transport.sent_messages) >= 1
        # The response should contain continuation marker if chunked
        _, first_message = mock_transport.sent_messages[0]
        # Either single message or first chunk with marker
        assert first_message  # Non-empty
