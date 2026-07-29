"""Meshtastic transport implementation."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import AsyncIterator
from concurrent.futures import ThreadPoolExecutor
from typing import TYPE_CHECKING

from meshgate.interfaces.message_transport import (
    IncomingMessage,
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
        max_queue_size: int = 100,
    ) -> None:
        """Initialize the Meshtastic transport.

        Args:
            connection_type: Type of connection - "serial", "ble", or "tcp"
            device: Device path for serial (None for auto-detect)
            tcp_host: Host address for TCP connection
            tcp_port: Port for TCP connection
            node_filter: Optional node filter for allowlist/denylist enforcement
            max_queue_size: Maximum queued inbound messages before dropping
        """
        self._connection_type = connection_type
        self._device = device
        self._tcp_host = tcp_host
        self._tcp_port = tcp_port
        self._node_filter = node_filter

        self._interface = None
        self._connected = False
        # Bounded, so a burst while a slow plugin call is in flight drops the
        # excess instead of growing without limit.
        self._message_queue: asyncio.Queue[IncomingMessage] = asyncio.Queue(maxsize=max_queue_size)
        # Captured at connect(): _on_receive runs on meshtastic's publishing
        # thread and needs the loop to hand messages over safely.
        self._loop: asyncio.AbstractEventLoop | None = None
        self._subscribed = False
        # Radio sends get their own single thread so concurrent handlers cannot
        # interleave writes on the serial stream.
        self._send_executor = ThreadPoolExecutor(
            max_workers=1, thread_name_prefix="meshtastic-send"
        )

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

        self._loop = asyncio.get_running_loop()

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
            self._subscribed = True

            self._connected = True
            logger.info(f"Connected to Meshtastic device via {self._connection_type}")

        except Exception as e:
            self._connected = False
            # Leaving the subscription in place would make a retry register the
            # callback twice, enqueuing every message once per attempt.
            self._unsubscribe()
            raise ConnectionError(f"Failed to connect: {e}") from e

    def _unsubscribe(self) -> None:
        """Remove the pubsub subscription if one is active."""
        if not self._subscribed:
            return
        try:
            from pubsub import pub

            pub.unsubscribe(self._on_receive, "meshtastic.receive.text")
        except Exception as e:
            logger.warning(f"Error unsubscribing: {e}")
        finally:
            self._subscribed = False

    async def disconnect(self) -> None:
        """Disconnect from the Meshtastic device."""
        self._unsubscribe()

        if self._interface:
            try:
                self._interface.close()
            except Exception as e:
                logger.warning(f"Error during disconnect: {e}")
            finally:
                self._interface = None
                logger.info("Disconnected from Meshtastic device")

        # Cleared unconditionally: previously a transport that never finished
        # connecting stayed marked as connected forever.
        self._connected = False
        self._send_executor.shutdown(wait=False)

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
            loop = asyncio.get_running_loop()
            interface = self._interface
            await loop.run_in_executor(
                self._send_executor,
                lambda: interface.sendText(text=message, destinationId=node_id, wantAck=True),
            )
            logger.debug(f"Sent message to {node_id}: {message[:50]}...")
            return True
        except Exception as e:
            logger.error(f"Failed to send message to {node_id}: {e}")
            return False

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

            node_name, location = self._lookup_node_info(from_id)

            context = NodeContext(node_id=from_id, node_name=node_name, location=location)
            incoming = IncomingMessage(text=text, context=context)

            # This runs on meshtastic's publishing thread, not the event loop.
            # asyncio.Queue is not thread-safe, so hand the item over through
            # the loop instead of calling put_nowait directly.
            loop = self._loop
            if loop is None or loop.is_closed():
                logger.warning("Received message before connect or after shutdown, dropping")
                return
            loop.call_soon_threadsafe(self._enqueue, incoming)

        except Exception as e:
            logger.error(f"Error processing received message: {e}")

    def _lookup_node_info(self, from_id: str) -> tuple[str | None, GPSLocation | None]:
        """Look up a node's name and position, tolerating an incomplete node DB.

        Enrichment is best-effort: the message text is already known, so a
        failure here must not discard it.
        """
        try:
            interface = self._interface
            if interface is None:
                return None, None

            # nodes is None until the node database finishes downloading.
            nodes = getattr(interface, "nodes", None)
            if not nodes:
                return None, None

            node_info = nodes.get(from_id) or {}
            user_info = node_info.get("user") or {}
            node_name = user_info.get("longName") or user_info.get("shortName")

            position = node_info.get("position") or {}
            lat = position.get("latitude")
            lon = position.get("longitude")
            alt = position.get("altitude")

            location = None
            if lat is not None and lon is not None:
                location = GPSLocation(latitude=lat, longitude=lon, altitude=alt)

            return node_name, location
        except Exception as e:
            logger.warning(f"Could not read node info for {from_id}: {e}")
            return None, None

    def _enqueue(self, incoming: IncomingMessage) -> None:
        """Put a message on the queue. Runs on the event loop thread."""
        try:
            self._message_queue.put_nowait(incoming)
        except asyncio.QueueFull:
            logger.warning("Message queue full, dropping message")

    @property
    def is_connected(self) -> bool:
        """Check if transport is currently connected."""
        return self._connected
