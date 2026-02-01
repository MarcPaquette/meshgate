"""Main HandlerServer orchestrator."""

import asyncio
import logging
from dataclasses import asdict

from meshgate.config import Config
from meshgate.core.content_chunker import ContentChunker
from meshgate.core.message_router import MessageRouter
from meshgate.core.node_filter import NodeFilter
from meshgate.core.plugin_loader import PluginLoader
from meshgate.core.plugin_registry import PluginRegistry
from meshgate.core.rate_limiter import RateLimiter
from meshgate.core.session_manager import SessionManager
from meshgate.interfaces.message_transport import IncomingMessage, MessageTransport
from meshgate.plugins.gopher_plugin import GopherPlugin
from meshgate.plugins.llm_plugin import LLMPlugin
from meshgate.plugins.weather_plugin import WeatherPlugin
from meshgate.plugins.wikipedia_plugin import WikipediaPlugin
from meshgate.transport.meshtastic_transport import MeshtasticTransport

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
        self._cleanup_task: asyncio.Task | None = None

        self._setup_components()
        self._setup_security()
        self._setup_transport(transport)
        self._register_builtin_plugins()
        self._load_external_plugins()

    def _setup_components(self) -> None:
        """Initialize core server components."""
        self._registry = PluginRegistry()
        self._session_manager = SessionManager(
            session_timeout_minutes=self._config.server.session_timeout_minutes,
            max_sessions=self._config.server.max_sessions,
        )
        self._router = MessageRouter(self._registry)
        self._chunker = ContentChunker(max_size=self._config.server.max_message_size)

    def _setup_security(self) -> None:
        """Initialize security components (node filter, rate limiter)."""
        security = self._config.security

        # Create node filter if any filtering is configured
        self._node_filter: NodeFilter | None = None
        if security.node_allowlist or security.node_denylist or security.require_allowlist:
            self._node_filter = NodeFilter(
                allowlist=security.node_allowlist,
                denylist=security.node_denylist,
                require_allowlist=security.require_allowlist,
            )

        # Create rate limiter
        self._rate_limiter = RateLimiter(
            max_messages=security.rate_limit_messages,
            window_seconds=security.rate_limit_window_seconds,
            enabled=security.rate_limit_enabled,
        )

    def _setup_transport(self, transport: MessageTransport | None) -> None:
        """Initialize the message transport.

        Args:
            transport: Custom transport or None to create default MeshtasticTransport
        """
        if transport is not None:
            self._transport = transport
        else:
            self._transport = MeshtasticTransport(
                connection_type=self._config.meshtastic.connection_type,
                device=self._config.meshtastic.device,
                tcp_host=self._config.meshtastic.tcp_host,
                tcp_port=self._config.meshtastic.tcp_port,
                node_filter=self._node_filter,
            )

    def _register_builtin_plugins(self) -> None:
        """Register the built-in plugins based on configuration."""
        plugins_cfg = self._config.plugins

        # Gopher only uses root_directory (allow_escape is unused)
        self._registry.register(
            GopherPlugin(root_directory=plugins_cfg.gopher.root_directory)
        )
        # LLM, Weather, Wikipedia configs map directly to plugin constructors
        self._registry.register(LLMPlugin(**asdict(plugins_cfg.llm)))
        self._registry.register(WeatherPlugin(**asdict(plugins_cfg.weather)))
        self._registry.register(WikipediaPlugin(**asdict(plugins_cfg.wikipedia)))

        logger.info(f"Registered {self._registry.plugin_count} built-in plugins")

    def _load_external_plugins(self) -> None:
        """Load and register external plugins from configured paths.

        Scans each directory in config.plugin_paths for Python files containing
        Plugin subclasses. Plugins are automatically instantiated and registered.

        Errors during loading are logged but don't stop the server.
        """
        if not self._config.plugin_paths:
            return

        loader = PluginLoader()
        loaded_count = 0

        for path in self._config.plugin_paths:
            plugins = loader.discover_plugins(path)

            for plugin in plugins:
                try:
                    self._registry.register(plugin)
                    loaded_count += 1
                    logger.info(
                        f"Registered external plugin '{plugin.metadata.name}' "
                        f"(menu #{plugin.metadata.menu_number})"
                    )
                except ValueError as e:
                    # Registration failed (duplicate name or menu number)
                    logger.warning(
                        f"Failed to register plugin '{plugin.metadata.name}': {e}"
                    )

        if loaded_count > 0:
            logger.info(f"Loaded {loaded_count} external plugins")
            logger.info(f"Total plugins: {self._registry.plugin_count}")

    async def start(self) -> None:
        """Start the server and begin handling messages."""
        logger.info("Starting Meshtastic Handler Server...")

        try:
            await self._transport.connect()
            self._running = True

            # Start periodic cleanup task
            self._cleanup_task = asyncio.create_task(self._periodic_cleanup())

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

        # Cancel cleanup task if running
        if self._cleanup_task is not None:
            self._cleanup_task.cancel()
            try:
                await self._cleanup_task
            except asyncio.CancelledError:
                pass
            self._cleanup_task = None

        await self._transport.disconnect()
        logger.info("Server stopped")

    async def _periodic_cleanup(self) -> None:
        """Periodically clean up expired sessions and rate limiter data."""
        interval_seconds = self._config.server.session_cleanup_interval_minutes * 60
        while self._running:
            try:
                await asyncio.sleep(interval_seconds)
                if self._running:
                    # Clean up expired sessions
                    removed = self._session_manager.cleanup_expired_sessions()
                    if removed > 0:
                        logger.info(f"Cleaned up {removed} expired sessions")

                    # Clean up inactive rate limiter data
                    rate_removed = self._rate_limiter.cleanup_inactive()
                    if rate_removed > 0:
                        logger.debug(
                            f"Cleaned up rate limit data for {rate_removed} nodes"
                        )
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Error during cleanup: {e}")

    async def _handle_message(self, incoming: IncomingMessage) -> None:
        """Handle an incoming message.

        Args:
            incoming: The incoming message to handle
        """
        try:
            node_id = incoming.context.node_id
            logger.debug(f"Message from {node_id}: {incoming.text}")

            # Check rate limit
            rate_result = self._rate_limiter.check(node_id)
            if not rate_result.allowed:
                retry_seconds = int(rate_result.retry_after_seconds or 0)
                await self._send_response(
                    node_id, f"Rate limited. Try in {retry_seconds}s"
                )
                return

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
        from meshgate.interfaces.node_context import NodeContext

        context = NodeContext(node_id=node_id, node_name=node_name)
        session = self._session_manager.get_session(node_id)

        if session.is_at_menu and not text.strip():
            return self._router.get_menu()

        response = await self._router.route(text, session, context)
        return response.message
