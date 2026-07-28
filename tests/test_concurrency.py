"""Tests for concurrent message handling.

One slow plugin call must not stall other nodes, but a single node's messages
must still be processed in order - Session is mutable and unlocked, so
overlapping messages from the same node would corrupt plugin_state.
"""

import asyncio
import time
from typing import Any

import pytest

from meshgate.config import Config
from meshgate.interfaces.node_context import NodeContext
from meshgate.interfaces.plugin import Plugin, PluginMetadata, PluginResponse
from meshgate.server import HandlerServer
from tests.conftest import running_server
from tests.mocks import MockTransport


class SlowPlugin(Plugin):
    """Plugin whose handle() takes a configurable amount of time."""

    def __init__(self, delay: float = 0.3) -> None:
        self._delay = delay
        self.started: list[float] = []
        self.finished: list[float] = []
        self.order: list[str] = []

    @property
    def metadata(self) -> PluginMetadata:
        return PluginMetadata(
            name="Slow", description="Slow plugin", menu_number=1, commands=()
        )

    def get_welcome_message(self) -> str:
        return "slow ready"

    def get_help_text(self) -> str:
        return "slow help"

    async def handle(
        self, message: str, context: NodeContext, plugin_state: dict[str, Any]
    ) -> PluginResponse:
        self.started.append(time.monotonic())
        self.order.append(f"start:{message}")
        await asyncio.sleep(self._delay)
        self.order.append(f"end:{message}")
        self.finished.append(time.monotonic())
        return PluginResponse(message=f"done {message}")


@pytest.fixture
def slow_server() -> tuple[HandlerServer, MockTransport, SlowPlugin]:
    """Server with only a slow plugin registered."""
    config = Config.default()
    transport = MockTransport()
    server = HandlerServer(config=config, transport=transport)

    plugin = SlowPlugin(delay=0.3)
    for existing in server.registry.get_all_plugins():
        server.registry.unregister(existing.metadata.name)
    server.registry.register(plugin)

    return server, transport, plugin


class TestConcurrentHandling:
    """Different nodes should be handled in parallel."""

    async def test_two_nodes_are_handled_concurrently(self, slow_server) -> None:
        server, transport, plugin = slow_server

        async with running_server(server):
            # Put both nodes into the slow plugin.
            transport.inject_message("1", node_id="!nodeA")
            transport.inject_message("1", node_id="!nodeB")
            await asyncio.sleep(0.1)

            transport.inject_message("hello", node_id="!nodeA")
            transport.inject_message("hello", node_id="!nodeB")

            # Wait for completion rather than a fixed sleep, so the span
            # measured below reflects the handlers and not this timeout.
            deadline = time.monotonic() + 3.0
            while len(plugin.finished) < 2 and time.monotonic() < deadline:
                await asyncio.sleep(0.01)

        assert len(plugin.finished) == 2, "both nodes should have been handled"
        # Serialized handling spans at least 2 * 0.3s; overlapping spans ~0.3s.
        span = max(plugin.finished) - min(plugin.started)
        assert span < 0.55, f"handling appears serialized (span {span:.2f}s)"

    async def test_same_node_messages_stay_ordered(self, slow_server) -> None:
        server, transport, plugin = slow_server

        async with running_server(server):
            transport.inject_message("1", node_id="!solo")
            await asyncio.sleep(0.1)

            transport.inject_message("first", node_id="!solo")
            transport.inject_message("second", node_id="!solo")
            await asyncio.sleep(1.0)

        # Strictly interleaved start/end means no overlap for a single node.
        assert plugin.order == [
            "start:first",
            "end:first",
            "start:second",
            "end:second",
        ]

    async def test_slow_node_does_not_block_a_fast_one(self, slow_server) -> None:
        server, transport, plugin = slow_server

        async with running_server(server):
            transport.inject_message("1", node_id="!slow")
            await asyncio.sleep(0.1)
            transport.inject_message("work", node_id="!slow")

            # This node stays at the menu, so its reply needs no plugin call.
            await asyncio.sleep(0.05)
            transport.inject_message("!menu", node_id="!fast")
            await asyncio.sleep(0.1)

            replies = [msg for node, msg in transport.sent_messages if node == "!fast"]

        assert replies, "fast node got no reply while the slow node was busy"


class TestShutdown:
    """stop() should drain in-flight work rather than truncating it."""

    async def test_inflight_handler_completes_on_stop(self, slow_server) -> None:
        server, transport, plugin = slow_server

        async with running_server(server):
            transport.inject_message("1", node_id="!nodeA")
            await asyncio.sleep(0.1)
            transport.inject_message("work", node_id="!nodeA")
            await asyncio.sleep(0.05)  # stop() lands mid-handle

        assert plugin.order == ["start:work", "end:work"]
        assert any("done work" in msg for _, msg in transport.sent_messages)

    async def test_stop_is_idempotent(self, slow_server) -> None:
        server, transport, _ = slow_server

        async with running_server(server):
            pass
        await server.stop()

        assert not server.is_running
