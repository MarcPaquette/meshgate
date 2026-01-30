"""Meshtastic transport implementation."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import AsyncIterator
from typing import TYPE_CHECKING

from meshgate.interfaces.message_transport import (
    IncomingMessage,
    MessageHandler,
    MessageTransport,
)
from meshgate.interfaces.node_context import GPSLocation, NodeContext

if TYPE_CHECKING:
    from meshgate.core.node_filter import NodeFilter

logger = logging.getLogger(__name__)


class MeshtasticTransport(MessageTransport):
    """Transport implementation for Meshtastic devices.

    Supports serial, BLE, and TCP connections to Meshtastic devices.
    """

    def __init__(
        self,
        connection_type: str = "serial",
        device: str | None = None,
        tcp_host: str | None = None,
        tcp_port: int = 4403,
        node_filter: NodeFilter | None = None,
    ) -> None:
        """Initialize the Meshtastic transport.

        Args:
            connection_type: Type of connection - "serial", "ble", or "tcp"
            device: Device path for serial (None for auto-detect)
            tcp_host: Host address for TCP connection
            tcp_port: Port for TCP connection
            node_filter: Optional node filter for allowlist/denylist enforcement
        """
        self._connection_type = connection_type
        self._device = device
        self._tcp_host = tcp_host
        self._tcp_port = tcp_port
        self._node_filter = node_filter

        self._interface = None
        self._message_handler: MessageHandler | None = None
        self._connected = False
        self._message_queue: asyncio.Queue[IncomingMessage] = asyncio.Queue()

    async def connect(self) -> None:
        """Establish connection to the Meshtastic device.

        Raises:
            ConnectionError: If connection cannot be established
            ImportError: If meshtastic package is not installed
        """
        try:
            import meshtastic.serial_interface
            import meshtastic.tcp_interface
        except ImportError as e:
            raise ImportError(
                "meshtastic package is required. Install with: pip install meshtastic"
            ) from e

        try:
            if self._connection_type == "serial":
                self._interface = meshtastic.serial_interface.SerialInterface(devPath=self._device)
            elif self._connection_type == "tcp":
                if not self._tcp_host:
                    raise ValueError("tcp_host is required for TCP connections")
                self._interface = meshtastic.tcp_interface.TCPInterface(
                    hostname=self._tcp_host, portNumber=self._tcp_port
                )
            elif self._connection_type == "ble":
                import meshtastic.ble_interface

                self._interface = meshtastic.ble_interface.BLEInterface(address=self._device)
            else:
                raise ValueError(f"Unsupported connection type: {self._connection_type}")

            # Subscribe to received messages
            from pubsub import pub

            pub.subscribe(self._on_receive, "meshtastic.receive.text")

            self._connected = True
            logger.info(f"Connected to Meshtastic device via {self._connection_type}")

        except Exception as e:
            self._connected = False
            raise ConnectionError(f"Failed to connect: {e}") from e

    async def disconnect(self) -> None:
        """Disconnect from the Meshtastic device."""
        if self._interface:
            try:
                from pubsub import pub

                pub.unsubscribe(self._on_receive, "meshtastic.receive.text")
                self._interface.close()
            except Exception as e:
                logger.warning(f"Error during disconnect: {e}")
            finally:
                self._interface = None
                self._connected = False
                logger.info("Disconnected from Meshtastic device")

    async def send_message(self, node_id: str, message: str) -> bool:
        """Send a message to a specific node.

        Args:
            node_id: The destination node ID
            message: The message text to send

        Returns:
            True if message was sent successfully, False otherwise
        """
        if not self._interface:
            logger.error("Cannot send message: not connected")
            return False

        try:
            # Run in executor since meshtastic library is synchronous
            loop = asyncio.get_event_loop()
            await loop.run_in_executor(
                None,
                lambda: self._interface.sendText(text=message, destinationId=node_id, wantAck=True),
            )
            logger.debug(f"Sent message to {node_id}: {message[:50]}...")
            return True
        except Exception as e:
            logger.error(f"Failed to send message to {node_id}: {e}")
            return False

    def set_message_handler(self, handler: MessageHandler) -> None:
        """Set the callback for handling incoming messages.

        Args:
            handler: Async function to call when a message is received
        """
        self._message_handler = handler

    async def listen(self) -> AsyncIterator[IncomingMessage]:
        """Listen for incoming messages.

        Yields:
            IncomingMessage for each received message
        """
        while self._connected:
            try:
                # Wait for message with timeout to allow checking connection status
                message = await asyncio.wait_for(self._message_queue.get(), timeout=1.0)
                yield message
            except TimeoutError:
                continue

    def _on_receive(self, packet: dict, interface: object) -> None:
        """Handle incoming message from Meshtastic.

        This is called by the pubsub system when a text message is received.
        """
        try:
            # Extract message text
            text = packet.get("decoded", {}).get("text", "")
            if not text:
                return

            # Extract sender info
            from_id = packet.get("fromId", "")
            if not from_id:
                return

            # Check node filter if configured
            if self._node_filter is not None and not self._node_filter.is_allowed(from_id):
                return

            # Try to get node info
            node_name = None
            location = None

            if self._interface:
                node_info = self._interface.nodes.get(from_id, {})
                user_info = node_info.get("user", {})
                node_name = user_info.get("longName") or user_info.get("shortName")

                # Get position if available
                position = node_info.get("position", {})
                lat = position.get("latitude")
                lon = position.get("longitude")
                alt = position.get("altitude")

                if lat is not None and lon is not None:
                    location = GPSLocation(latitude=lat, longitude=lon, altitude=alt)

            context = NodeContext(node_id=from_id, node_name=node_name, location=location)
            incoming = IncomingMessage(text=text, context=context)

            # Add to queue for async processing
            try:
                self._message_queue.put_nowait(incoming)
            except asyncio.QueueFull:
                logger.warning("Message queue full, dropping message")

            # Also call handler if set
            if self._message_handler:
                # Schedule the async handler
                loop = asyncio.get_event_loop()
                if loop.is_running():
                    asyncio.create_task(self._message_handler(incoming))

        except Exception as e:
            logger.error(f"Error processing received message: {e}")

    @property
    def is_connected(self) -> bool:
        """Check if transport is currently connected."""
        return self._connected
