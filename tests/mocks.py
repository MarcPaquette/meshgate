"""Mock classes for testing."""

import asyncio
from collections.abc import AsyncIterator
from typing import Any

from meshgate.interfaces.message_transport import (
    IncomingMessage,
    MessageHandler,
    MessageTransport,
)
from meshgate.interfaces.node_context import NodeContext
from meshgate.interfaces.plugin import Plugin, PluginMetadata, PluginResponse


class MockTransport(MessageTransport):
    """Mock transport for testing."""

    def __init__(self) -> None:
        self._connected = False
        self._handler: MessageHandler | None = None
        self._message_queue: asyncio.Queue[IncomingMessage] = asyncio.Queue()
        self._sent_messages: list[tuple[str, str]] = []

    async def connect(self) -> None:
        self._connected = True

    async def disconnect(self) -> None:
        self._connected = False

    async def send_message(self, node_id: str, message: str) -> bool:
        self._sent_messages.append((node_id, message))
        return True

    def set_message_handler(self, handler: MessageHandler) -> None:
        self._handler = handler

    async def listen(self) -> AsyncIterator[IncomingMessage]:
        while self._connected:
            try:
                message = await asyncio.wait_for(self._message_queue.get(), timeout=0.1)
                yield message
            except TimeoutError:
                continue

    @property
    def is_connected(self) -> bool:
        return self._connected

    def inject_message(self, text: str, node_id: str = "!test123") -> None:
        """Inject a message for testing."""
        context = NodeContext(node_id=node_id)
        message = IncomingMessage(text=text, context=context)
        self._message_queue.put_nowait(message)

    @property
    def sent_messages(self) -> list[tuple[str, str]]:
        """Get list of (node_id, message) tuples that were sent."""
        return self._sent_messages


class MockPlugin(Plugin):
    """Mock plugin for testing."""

    def __init__(
        self,
        name: str = "Mock Plugin",
        menu_number: int = 99,
        welcome: str = "Welcome to mock",
        help_text: str = "Mock help",
    ) -> None:
        self._name = name
        self._menu_number = menu_number
        self._welcome = welcome
        self._help_text = help_text
        self._handle_calls: list[tuple[str, NodeContext, dict]] = []

    @property
    def metadata(self) -> PluginMetadata:
        return PluginMetadata(
            name=self._name,
            description="A mock plugin",
            menu_number=self._menu_number,
            commands=("!mock",),
        )

    def get_welcome_message(self) -> str:
        return self._welcome

    def get_help_text(self) -> str:
        return self._help_text

    async def handle(
        self, message: str, context: NodeContext, plugin_state: dict[str, Any]
    ) -> PluginResponse:
        self._handle_calls.append((message, context, plugin_state))
        return PluginResponse(
            message=f"Mock response to: {message}",
            plugin_state={"last_message": message},
        )

    @property
    def handle_calls(self) -> list[tuple[str, NodeContext, dict]]:
        """Get list of handle() calls for verification."""
        return self._handle_calls
