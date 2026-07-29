"""Main HandlerServer orchestrator."""

import asyncio
import logging
import time

from meshgate.config import Config
from meshgate.core.content_chunker import ContentChunker
from meshgate.core.message_router import MessageRouter
from meshgate.core.node_filter import NodeFilter
from meshgate.core.plugin_loader import PluginLoader
from meshgate.core.plugin_registry import PluginRegistry
from meshgate.core.rate_limiter import RateLimiter
from meshgate.core.session_manager import SessionManager
from meshgate.core.transcript import TranscriptRecorder
from meshgate.interfaces.message_transport import IncomingMessage, MessageTransport
from meshgate.interfaces.plugin import Plugin
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

    # Maximum messages handled concurrently across all nodes
    MAX_CONCURRENT_HANDLERS = 10

    # How long stop() waits for in-flight handlers before cancelling them
    SHUTDOWN_GRACE_SECONDS = 5.0

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

        # Messages are handled concurrently so one slow plugin call cannot
        # stall the whole mesh, but each node is serialized against itself:
        # Session is mutable and unlocked, so two overlapping messages from the
        # same node would otherwise interleave and corrupt plugin_state.
        self._semaphore = asyncio.Semaphore(self.MAX_CONCURRENT_HANDLERS)
        self._node_locks: dict[str, asyncio.Lock] = {}
        self._inflight: set[asyncio.Task] = set()

        # When each node was last told it is rate limited
        self._rate_limit_notified: dict[str, float] = {}

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
        self._router = MessageRouter(
            self._registry,
            max_state_bytes=self._config.security.max_plugin_state_bytes,
        )
        self._chunker = ContentChunker(max_size=self._config.server.max_message_size)
        web = self._config.web
        self._transcript = TranscriptRecorder(
            enabled=web.transcript_enabled,
            max_messages=web.transcript_max_messages,
            max_nodes=web.transcript_max_nodes,
        )

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
        """Register the built-in plugins based on configuration.

        Constructor arguments are mapped explicitly rather than splatted from
        asdict(): asdict() passes every field, so any config field that is not
        also a constructor parameter (such as `enabled`) becomes an unexpected
        keyword argument and breaks startup.
        """
        plugins_cfg = self._config.plugins

        builtins: list[tuple[bool, Plugin]] = [
            # Gopher only uses root_directory (allow_escape is unused)
            (
                plugins_cfg.gopher.enabled,
                GopherPlugin(root_directory=plugins_cfg.gopher.root_directory),
            ),
            (
                plugins_cfg.llm.enabled,
                LLMPlugin(
                    ollama_url=plugins_cfg.llm.ollama_url,
                    model=plugins_cfg.llm.model,
                    max_response_length=plugins_cfg.llm.max_response_length,
                    timeout=plugins_cfg.llm.timeout,
                ),
            ),
            (
                plugins_cfg.weather.enabled,
                WeatherPlugin(timeout=plugins_cfg.weather.timeout),
            ),
            (
                plugins_cfg.wikipedia.enabled,
                WikipediaPlugin(
                    language=plugins_cfg.wikipedia.language,
                    max_summary_length=plugins_cfg.wikipedia.max_summary_length,
                    timeout=plugins_cfg.wikipedia.timeout,
                ),
            ),
        ]

        for enabled, plugin in builtins:
            self._registry.register(plugin)
            if not enabled:
                # Registered then disabled, so the plugin keeps its menu number
                # reserved and can be toggled back on at runtime.
                self._registry.disable(plugin.metadata.name)

        logger.info(
            f"Registered {self._registry.plugin_count} built-in plugins "
            f"({self._registry.disabled_count} disabled)"
        )

    def _load_external_plugins(self) -> None:
        """Load and register external plugins from configured paths.

        Scans each directory in config.plugin_paths for Python files containing
        Plugin subclasses. Plugins are automatically instantiated and registered.

        Errors during loading are logged but don't stop the server.
        """
        if not self._config.plugin_paths:
            return

        logger.warning(
            "SECURITY: External plugin loading enabled. "
            "Plugins execute arbitrary code with full system access. "
            "Paths: %s",
            self._config.plugin_paths,
        )

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
                    logger.warning(f"Failed to register plugin '{plugin.metadata.name}': {e}")

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

            # Main message processing loop. Dispatch rather than await, so a
            # slow plugin call for one node does not block every other node.
            async for message in self._transport.listen():
                if not self._running:
                    break
                self._dispatch(message)

        except Exception as e:
            logger.error(f"Server error: {e}")
            raise

    def _dispatch(self, incoming: IncomingMessage) -> None:
        """Schedule handling of an incoming message without blocking the loop."""
        task = asyncio.create_task(self._handle_serialized(incoming))
        # Keep a strong reference: asyncio only holds a weak one, so an
        # untracked task can be garbage collected mid-flight.
        self._inflight.add(task)
        task.add_done_callback(self._inflight.discard)

    async def _handle_serialized(self, incoming: IncomingMessage) -> None:
        """Handle a message under the global cap and the node's own lock."""
        node_id = incoming.context.node_id
        lock = self._node_locks.setdefault(node_id, asyncio.Lock())
        try:
            async with self._semaphore, lock:
                await self._handle_message(incoming)
        except asyncio.CancelledError:
            raise
        except Exception as e:
            logger.error(f"Unhandled error dispatching message from {node_id}: {e}")

    async def stop(self) -> None:
        """Stop the server and disconnect.

        Safe to call more than once.
        """
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

        # Let in-flight handlers finish before cancelling, so a multi-chunk
        # reply already going out is not truncated mid-send.
        if self._inflight:
            pending = list(self._inflight)
            done, still_running = await asyncio.wait(pending, timeout=self.SHUTDOWN_GRACE_SECONDS)
            for task in still_running:
                task.cancel()
            if still_running:
                logger.warning(f"Cancelled {len(still_running)} in-flight handlers")
                await asyncio.gather(*still_running, return_exceptions=True)
            self._inflight.clear()
        self._node_locks.clear()

        await self._close_plugin_clients()
        await self._transport.disconnect()
        logger.info("Server stopped")

    async def _close_plugin_clients(self) -> None:
        """Close HTTP clients held by plugins that expose an aclose() hook."""
        for plugin in self._registry.get_all_plugins():
            aclose = getattr(plugin, "aclose", None)
            if aclose is None:
                continue
            try:
                await aclose()
            except Exception as e:
                logger.warning(f"Error closing plugin '{plugin.metadata.name}': {e}")

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
                        logger.debug(f"Cleaned up rate limit data for {rate_removed} nodes")

                    # Drop per-node locks that nobody is holding or waiting on,
                    # otherwise the dict grows one entry per node seen.
                    for node_id, lock in list(self._node_locks.items()):
                        if not lock.locked():
                            del self._node_locks[node_id]

                    window = self._config.security.rate_limit_window_seconds
                    now = time.monotonic()
                    for node_id, notified_at in list(self._rate_limit_notified.items()):
                        if now - notified_at > window:
                            del self._rate_limit_notified[node_id]

                    # Drop transcripts for nodes whose sessions are gone, so
                    # the recorder does not accumulate node IDs indefinitely.
                    if self._transcript.enabled:
                        live = {s.node_id for s in self._session_manager.list_sessions()}
                        dropped = self._transcript.retain_only(live)
                        if dropped > 0:
                            logger.debug(f"Dropped {dropped} stale transcripts")
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
                # Notify at most once per window. Replying to every rejected
                # message would spend more shared airtime than it saves on a
                # duty-cycle-limited half-duplex mesh.
                if self._should_notify_rate_limit(node_id):
                    retry_seconds = int(rate_result.retry_after_seconds or 0)
                    await self._send_response(node_id, f"Rate limited. Try in {retry_seconds}s")
                return

            # Recorded after the rate-limit check so a flood cannot fill the
            # transcript with messages that were never acted on.
            self._transcript.record_inbound(node_id, incoming.text)

            # Get or create session
            session = self._session_manager.get_session(node_id)

            # First message from this node - show menu
            if session.is_at_menu and not incoming.text.strip():
                response_text = self._router.get_menu()
            else:
                # Route message
                response = await self._router.route(incoming.text, session, incoming.context)
                response_text = response.message

            self._transcript.record_outbound(node_id, response_text)

            # Send response (chunked if necessary)
            await self._send_response(node_id, response_text)

        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("Error handling message")
            # Send a fixed string, never the exception text: it is unbounded
            # in length and can expose internal URLs and paths.
            try:
                await self._send_response(incoming.context.node_id, "Sorry, something went wrong.")
            except Exception:
                pass

    def _should_notify_rate_limit(self, node_id: str) -> bool:
        """Check whether this node is due another rate-limit notice.

        Args:
            node_id: The node being rate limited

        Returns:
            True if a notice should be sent now
        """
        window = self._config.security.rate_limit_window_seconds
        now = time.monotonic()
        last = self._rate_limit_notified.get(node_id)
        if last is not None and now - last < window:
            return False
        self._rate_limit_notified[node_id] = now
        return True

    async def _send_response(self, node_id: str, message: str) -> None:
        """Send a response, chunking if necessary.

        Args:
            node_id: Destination node ID
            message: Message to send
        """
        chunks = self._chunker.chunk(message)

        last_index = len(chunks) - 1
        for i, chunk in enumerate(chunks):
            success = await self._transport.send_message(node_id, chunk)
            if not success:
                logger.warning(f"Failed to send chunk to {node_id}")

            # Small delay between chunks to avoid overwhelming the network.
            # Only between chunks - a trailing sleep is pure dead airtime.
            if i < last_index:
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
    def config(self) -> Config:
        """Get the server configuration."""
        return self._config

    @property
    def rate_limiter(self) -> RateLimiter:
        """Get the rate limiter (read its properties; do not call check())."""
        return self._rate_limiter

    @property
    def transport(self) -> MessageTransport:
        """Get the message transport."""
        return self._transport

    @property
    def transcript(self) -> TranscriptRecorder:
        """Get the chat transcript recorder."""
        return self._transcript

    @property
    def router(self) -> MessageRouter:
        """Get the message router."""
        return self._router

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
