"""Tests for MeshtasticTransport.

The meshtastic library is synchronous and talks to real hardware, so the
interface classes and the pubsub bus are replaced with fakes. The important
behaviour under test is the hand-off from meshtastic's publishing thread to the
asyncio event loop, which is why several tests drive _on_receive from a real
thread rather than calling it inline.
"""

import asyncio
import threading

import meshtastic.serial_interface
import meshtastic.tcp_interface
import pytest
from pubsub import pub

from meshgate.core.node_filter import NodeFilter
from meshgate.transport.meshtastic_transport import MeshtasticTransport


class FakeInterface:
    """Stand-in for a meshtastic interface."""

    def __init__(self, nodes: dict | None = None, **kwargs) -> None:
        self.kwargs = kwargs
        self.nodes = {} if nodes is None else nodes
        self.sent: list[dict] = []
        self.closed = False
        self.send_error: Exception | None = None

    # Name and signature mirror the meshtastic library's camelCase API.
    def sendText(  # noqa: N802
        self, text: str, destinationId: str, wantAck: bool = False  # noqa: N803
    ) -> None:
        if self.send_error is not None:
            raise self.send_error
        self.sent.append({"text": text, "destinationId": destinationId, "wantAck": wantAck})

    def close(self) -> None:
        self.closed = True


@pytest.fixture
def fake_pubsub(monkeypatch: pytest.MonkeyPatch) -> dict:
    """Record subscribe/unsubscribe calls instead of touching the real bus."""
    calls: dict = {"subscribed": [], "unsubscribed": []}
    monkeypatch.setattr(
        pub, "subscribe", lambda listener, topic: calls["subscribed"].append((listener, topic))
    )
    monkeypatch.setattr(
        pub, "unsubscribe", lambda listener, topic: calls["unsubscribed"].append((listener, topic))
    )
    return calls


@pytest.fixture
def fake_serial(monkeypatch: pytest.MonkeyPatch) -> list[FakeInterface]:
    """Replace SerialInterface with a fake, returning the instances created."""
    created: list[FakeInterface] = []

    def factory(**kwargs) -> FakeInterface:
        iface = FakeInterface(**kwargs)
        created.append(iface)
        return iface

    monkeypatch.setattr(meshtastic.serial_interface, "SerialInterface", factory)
    return created


def make_packet(text: str = "hello", from_id: str = "!abc123") -> dict:
    """Build a meshtastic text packet."""
    return {"decoded": {"text": text}, "fromId": from_id}


class TestConnect:
    """Tests for connect() across the supported connection types."""

    async def test_serial_connect(self, fake_serial, fake_pubsub) -> None:
        transport = MeshtasticTransport(connection_type="serial", device="/dev/ttyUSB0")
        await transport.connect()

        assert transport.is_connected
        assert fake_serial[0].kwargs["devPath"] == "/dev/ttyUSB0"
        assert fake_pubsub["subscribed"][0][1] == "meshtastic.receive.text"

    async def test_tcp_connect(self, monkeypatch, fake_pubsub) -> None:
        created: list[FakeInterface] = []
        monkeypatch.setattr(
            meshtastic.tcp_interface,
            "TCPInterface",
            lambda **kw: created.append(FakeInterface(**kw)) or created[-1],
        )

        transport = MeshtasticTransport(
            connection_type="tcp", tcp_host="10.0.0.5", tcp_port=4403
        )
        await transport.connect()

        assert transport.is_connected
        assert created[0].kwargs == {"hostname": "10.0.0.5", "portNumber": 4403}

    async def test_tcp_requires_host(self, fake_pubsub) -> None:
        transport = MeshtasticTransport(connection_type="tcp", tcp_host=None)

        with pytest.raises(ConnectionError, match="tcp_host is required"):
            await transport.connect()
        assert not transport.is_connected

    async def test_unsupported_connection_type(self, fake_pubsub) -> None:
        transport = MeshtasticTransport(connection_type="carrier-pigeon")

        with pytest.raises(ConnectionError, match="Unsupported connection type"):
            await transport.connect()

    async def test_failed_connect_does_not_leak_subscription(
        self, monkeypatch, fake_pubsub
    ) -> None:
        """A retry after a failure must not register the callback twice."""

        def explode(**kwargs):
            raise OSError("device busy")

        monkeypatch.setattr(meshtastic.serial_interface, "SerialInterface", explode)
        transport = MeshtasticTransport(connection_type="serial")

        with pytest.raises(ConnectionError):
            await transport.connect()

        # Nothing was subscribed because the interface never came up; and if a
        # subscription had been made it must have been undone.
        assert len(fake_pubsub["subscribed"]) == len(fake_pubsub["unsubscribed"])


class TestSendMessage:
    """Tests for send_message()."""

    async def test_send_success(self, fake_serial, fake_pubsub) -> None:
        transport = MeshtasticTransport()
        await transport.connect()

        assert await transport.send_message("!dest", "hi") is True
        assert fake_serial[0].sent == [
            {"text": "hi", "destinationId": "!dest", "wantAck": True}
        ]

    async def test_send_when_not_connected(self) -> None:
        transport = MeshtasticTransport()
        assert await transport.send_message("!dest", "hi") is False

    async def test_send_failure_returns_false(self, fake_serial, fake_pubsub) -> None:
        transport = MeshtasticTransport()
        await transport.connect()
        fake_serial[0].send_error = OSError("radio unplugged")

        assert await transport.send_message("!dest", "hi") is False


class TestOnReceive:
    """Tests for the pubsub callback and its hand-off to the event loop."""

    async def _connected(self, nodes: dict | None = None) -> MeshtasticTransport:
        transport = MeshtasticTransport()
        await transport.connect()
        if nodes is not None:
            transport._interface.nodes = nodes
        return transport

    async def test_delivers_message(self, fake_serial, fake_pubsub) -> None:
        transport = await self._connected()
        transport._on_receive(make_packet("hello"), None)
        await asyncio.sleep(0)  # let call_soon_threadsafe run

        message = transport._message_queue.get_nowait()
        assert message.text == "hello"
        assert message.context.node_id == "!abc123"

    async def test_ignores_empty_text_and_missing_sender(
        self, fake_serial, fake_pubsub
    ) -> None:
        transport = await self._connected()

        transport._on_receive({"decoded": {"text": ""}, "fromId": "!abc"}, None)
        transport._on_receive({"decoded": {"text": "hi"}, "fromId": ""}, None)
        await asyncio.sleep(0)

        assert transport._message_queue.empty()

    async def test_node_filter_rejection(self, fake_serial, fake_pubsub) -> None:
        transport = MeshtasticTransport(
            node_filter=NodeFilter(denylist=["!blocked"], allowlist=[], require_allowlist=False)
        )
        await transport.connect()

        transport._on_receive(make_packet("hi", from_id="!blocked"), None)
        await asyncio.sleep(0)

        assert transport._message_queue.empty()

    async def test_enriches_name_and_location(self, fake_serial, fake_pubsub) -> None:
        transport = await self._connected(
            nodes={
                "!abc123": {
                    "user": {"longName": "Base Camp"},
                    "position": {"latitude": 40.7, "longitude": -74.0, "altitude": 10},
                }
            }
        )

        transport._on_receive(make_packet(), None)
        await asyncio.sleep(0)

        message = transport._message_queue.get_nowait()
        assert message.context.node_name == "Base Camp"
        assert message.context.location.latitude == 40.7
        assert message.context.location.altitude == 10

    async def test_message_survives_missing_node_db(self, fake_serial, fake_pubsub) -> None:
        """nodes is None until the node database downloads - don't drop the text."""
        transport = await self._connected()
        transport._interface.nodes = None

        transport._on_receive(make_packet("still here"), None)
        await asyncio.sleep(0)

        message = transport._message_queue.get_nowait()
        assert message.text == "still here"
        assert message.context.node_name is None

    async def test_delivery_from_a_real_thread(self, fake_serial, fake_pubsub) -> None:
        """The callback runs on meshtastic's publishing thread, not the loop."""
        transport = await self._connected()
        done = threading.Event()

        def publish() -> None:
            transport._on_receive(make_packet("from another thread"), None)
            done.set()

        thread = threading.Thread(target=publish)
        thread.start()
        thread.join(timeout=5)
        assert done.is_set()

        message = await asyncio.wait_for(transport._message_queue.get(), timeout=5)
        assert message.text == "from another thread"

    async def test_handoff_uses_call_soon_threadsafe(
        self, fake_serial, fake_pubsub, monkeypatch
    ) -> None:
        """Deterministic counterpart to the threaded test above.

        asyncio.Queue is not thread-safe, so the enqueue must go through the
        loop rather than being called directly from the pubsub thread. The
        threaded test can pass by luck; this one cannot.
        """
        transport = await self._connected()
        handoffs = []
        real = transport._loop.call_soon_threadsafe

        def spy(callback, *args):
            handoffs.append(callback)
            return real(callback, *args)

        monkeypatch.setattr(transport._loop, "call_soon_threadsafe", spy)

        transport._on_receive(make_packet(), None)
        await asyncio.sleep(0)

        assert handoffs == [transport._enqueue]

    async def test_queue_full_drops_message(self, fake_serial, fake_pubsub) -> None:
        """The bounded queue makes the QueueFull path reachable."""
        transport = MeshtasticTransport(max_queue_size=2)
        await transport.connect()

        for i in range(5):
            transport._on_receive(make_packet(f"msg{i}"), None)
        await asyncio.sleep(0)

        assert transport._message_queue.qsize() == 2

    async def test_drops_message_when_loop_unavailable(self, fake_serial, fake_pubsub) -> None:
        """A packet arriving before connect has no loop to hand off to."""
        transport = MeshtasticTransport()
        transport._on_receive(make_packet(), None)
        assert transport._message_queue.empty()


class TestListenAndDisconnect:
    """Tests for the listen() generator and shutdown."""

    async def test_listen_yields_queued_messages(self, fake_serial, fake_pubsub) -> None:
        transport = MeshtasticTransport()
        await transport.connect()
        transport._on_receive(make_packet("one"), None)
        await asyncio.sleep(0)

        received = []
        async for message in transport.listen():
            received.append(message.text)
            break

        assert received == ["one"]

    async def test_listen_stops_when_disconnected(self, fake_serial, fake_pubsub) -> None:
        transport = MeshtasticTransport()
        await transport.connect()
        await transport.disconnect()

        received = [m async for m in transport.listen()]
        assert received == []

    async def test_disconnect_closes_and_unsubscribes(self, fake_serial, fake_pubsub) -> None:
        transport = MeshtasticTransport()
        await transport.connect()
        interface = fake_serial[0]

        await transport.disconnect()

        assert interface.closed
        assert not transport.is_connected
        assert fake_pubsub["unsubscribed"][0][1] == "meshtastic.receive.text"

    async def test_disconnect_clears_connected_without_interface(self) -> None:
        """Previously a transport with no interface stayed marked connected."""
        transport = MeshtasticTransport()
        transport._connected = True

        await transport.disconnect()

        assert not transport.is_connected
