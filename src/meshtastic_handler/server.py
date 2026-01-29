"""Main HandlerServer orchestrator."""

import asyncio
import logging

from meshtastic_handler.config import Config
from meshtastic_handler.core.content_chunker import ContentChunker
from meshtastic_handler.core.message_router import MessageRouter
from meshtastic_handler.core.plugin_registry import PluginRegistry
from meshtastic_handler.core.session_manager import SessionManager
from meshtastic_handler.interfaces.message_transport import IncomingMessage, MessageTransport
from meshtastic_handler.plugins.gopher_plugin import GopherPlugin
from meshtastic_handler.plugins.llm_plugin import LLMPlugin
from meshtastic_handler.plugins.weather_plugin import WeatherPlugin
from meshtastic_handler.plugins.wikipedia_plugin import WikipediaPlugin
from meshtastic_handler.transport.meshtastic_transport import MeshtasticTransport

logger = logging.getLogger(__name__)


class HandlerServer:
    """Main server orchestrating message handling with plugins.

    The HandlerServer coordinates:
    - Transport layer for Meshtastic communication
    - Plugin registry for available plugins
    - Session management for per-node state
    - Message routing to appropriate plugins
    - Response chunking for radio limits
    """

    # Delay between sending message chunks (seconds)
    CHUNK_DELAY_SECONDS = 0.5

    def __init__(
        self,
        config: Config | None = None,
        transport: MessageTransport | None = None,
    ) -> None:
        """Initialize the handler server.

        Args:
            config: Server configuration (default if not provided)
            transport: Custom transport (creates MeshtasticTransport if not provided)
        """
        self._config = config or Config.default()
        self._running = False

        # Initialize components
        self._registry = PluginRegistry()
        self._session_manager = SessionManager(
            session_timeout_minutes=self._config.server.session_timeout_minutes
        )
        self._router = MessageRouter(self._registry)
        self._chunker = ContentChunker(max_size=self._config.server.max_message_size)

        # Create or use provided transport
        if transport is not None:
            self._transport = transport
        else:
            self._transport = MeshtasticTransport(
                connection_type=self._config.meshtastic.connection_type,
                device=self._config.meshtastic.device,
                tcp_host=self._config.meshtastic.tcp_host,
                tcp_port=self._config.meshtastic.tcp_port,
            )

        # Register built-in plugins
        self._register_builtin_plugins()

    def _register_builtin_plugins(self) -> None:
        """Register the built-in plugins based on configuration."""
        # Gopher plugin
        gopher = GopherPlugin(root_directory=self._config.plugins.gopher.root_directory)
        self._registry.register(gopher)

        # LLM plugin
        llm = LLMPlugin(
            ollama_url=self._config.plugins.llm.ollama_url,
            model=self._config.plugins.llm.model,
            max_response_length=self._config.plugins.llm.max_response_length,
            timeout=self._config.plugins.llm.timeout,
        )
        self._registry.register(llm)

        # Weather plugin
        weather = WeatherPlugin(timeout=self._config.plugins.weather.timeout)
        self._registry.register(weather)

        # Wikipedia plugin
        wikipedia = WikipediaPlugin(
            language=self._config.plugins.wikipedia.language,
            max_summary_length=self._config.plugins.wikipedia.max_summary_length,
            timeout=self._config.plugins.wikipedia.timeout,
        )
        self._registry.register(wikipedia)

        logger.info(f"Registered {self._registry.plugin_count} plugins")

    async def start(self) -> None:
        """Start the server and begin handling messages."""
        logger.info("Starting Meshtastic Handler Server...")

        try:
            await self._transport.connect()
            self._running = True

            logger.info("Server started. Listening for messages...")

            # Main message processing loop
            async for message in self._transport.listen():
                if not self._running:
                    break
                await self._handle_message(message)

        except Exception as e:
            logger.error(f"Server error: {e}")
            raise
        finally:
            await self.stop()

    async def stop(self) -> None:
        """Stop the server and disconnect."""
        logger.info("Stopping server...")
        self._running = False
        await self._transport.disconnect()
        logger.info("Server stopped")

    async def _handle_message(self, incoming: IncomingMessage) -> None:
        """Handle an incoming message.

        Args:
            incoming: The incoming message to handle
        """
        try:
            node_id = incoming.context.node_id
            logger.debug(f"Message from {node_id}: {incoming.text}")

            # Get or create session
            session = self._session_manager.get_session(node_id)

            # First message from this node - show menu
            if session.is_at_menu and not incoming.text.strip():
                response_text = self._router.get_menu()
            else:
                # Route message
                response = await self._router.route(incoming.text, session, incoming.context)
                response_text = response.message

            # Send response (chunked if necessary)
            await self._send_response(node_id, response_text)

        except Exception as e:
            logger.error(f"Error handling message: {e}")
            # Try to send error response
            try:
                await self._send_response(incoming.context.node_id, f"Error: {e}")
            except Exception:
                pass

    async def _send_response(self, node_id: str, message: str) -> None:
        """Send a response, chunking if necessary.

        Args:
            node_id: Destination node ID
            message: Message to send
        """
        chunks = self._chunker.chunk(message)

        for chunk in chunks:
            success = await self._transport.send_message(node_id, chunk)
            if not success:
                logger.warning(f"Failed to send chunk to {node_id}")

            # Small delay between chunks to avoid overwhelming the network
            if len(chunks) > 1:
                await asyncio.sleep(self.CHUNK_DELAY_SECONDS)

    @property
    def registry(self) -> PluginRegistry:
        """Get the plugin registry."""
        return self._registry

    @property
    def session_manager(self) -> SessionManager:
        """Get the session manager."""
        return self._session_manager

    @property
    def is_running(self) -> bool:
        """Check if server is running."""
        return self._running

    async def handle_single_message(
        self, text: str, node_id: str, node_name: str | None = None
    ) -> str:
        """Handle a single message and return the response.

        This is useful for testing and direct interaction without transport.

        Args:
            text: Message text
            node_id: Node ID
            node_name: Optional node name

        Returns:
            Response text
        """
        from meshtastic_handler.interfaces.node_context import NodeContext

        context = NodeContext(node_id=node_id, node_name=node_name)
        session = self._session_manager.get_session(node_id)

        if session.is_at_menu and not text.strip():
            return self._router.get_menu()

        response = await self._router.route(text, session, context)
        return response.message
