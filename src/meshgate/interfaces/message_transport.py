"""Message transport interface - Abstract base class for transport implementations."""

from abc import ABC, abstractmethod
from collections.abc import AsyncIterator, Callable, Coroutine
from dataclasses import dataclass

from meshgate.interfaces.node_context import NodeContext


@dataclass(frozen=True)
class IncomingMessage:
    """An incoming message from the mesh network.

    Attributes:
        text: The message content
        context: Information about the sending node
    """

    text: str
    context: NodeContext


# Type alias for message handlers
MessageHandler = Callable[[IncomingMessage], Coroutine[None, None, None]]


class MessageTransport(ABC):
    """Abstract base class for message transport implementations.

    Transports handle the communication with the Meshtastic network,
    receiving messages and sending responses.
    """

    @abstractmethod
    async def connect(self) -> None:
        """Establish connection to the Meshtastic device/network.

        Raises:
            ConnectionError: If connection cannot be established
        """

    @abstractmethod
    async def disconnect(self) -> None:
        """Disconnect from the Meshtastic device/network."""

    @abstractmethod
    async def send_message(self, node_id: str, message: str) -> bool:
        """Send a message to a specific node.

        Args:
            node_id: The destination node ID
            message: The message text to send

        Returns:
            True if message was sent successfully, False otherwise
        """

    @abstractmethod
    def set_message_handler(self, handler: MessageHandler) -> None:
        """Set the callback for handling incoming messages.

        Args:
            handler: Async function to call when a message is received
        """

    @abstractmethod
    async def listen(self) -> AsyncIterator[IncomingMessage]:
        """Listen for incoming messages.

        Yields:
            IncomingMessage for each received message
        """

    @property
    @abstractmethod
    def is_connected(self) -> bool:
        """Check if transport is currently connected."""
