"""Tests for rate-limit notification and shutdown cleanup.

Both are end-to-end paths through HandlerServer: the rate-limit branch is a
security control whose reply costs shared radio airtime, and plugin HTTP
clients are now long-lived so they must actually be closed on shutdown.
"""

import asyncio
from typing import Any

import pytest

from meshgate.config import Config
from meshgate.interfaces.node_context import NodeContext
from meshgate.interfaces.plugin import Plugin, PluginMetadata, PluginResponse
from meshgate.plugins.base import HTTPPluginBase
from meshgate.server import HandlerServer
from tests.conftest import running_server
from tests.mocks import MockTransport


@pytest.fixture
def rate_limited_server() -> tuple[HandlerServer, MockTransport]:
    """Server allowing a single message per window."""
    config = Config.default()
    config.security.rate_limit_enabled = True
    config.security.rate_limit_messages = 1
    config.security.rate_limit_window_seconds = 60

    transport = MockTransport()
    return HandlerServer(config=config, transport=transport), transport


class TestRateLimitNotification:
    """Replying to every rejected message wastes more airtime than it saves."""

    async def test_notifies_once_per_window(self, rate_limited_server) -> None:
        server, transport = rate_limited_server

        async with running_server(server):
            for _ in range(6):
                transport.inject_message("!menu", node_id="!spammer")
            await asyncio.sleep(0.4)

        notices = [m for _, m in transport.sent_messages if "Rate limited" in m]
        assert len(notices) == 1, f"expected one notice, got {len(notices)}"

    async def test_allowed_message_still_answered(self, rate_limited_server) -> None:
        server, transport = rate_limited_server

        async with running_server(server):
            transport.inject_message("!menu", node_id="!user")
            await asyncio.sleep(0.3)

        replies = [m for _, m in transport.sent_messages if "Rate limited" not in m]
        assert replies, "the first message should get a real reply"

    async def test_each_node_notified_independently(self, rate_limited_server) -> None:
        server, transport = rate_limited_server

        async with running_server(server):
            for node in ("!nodeA", "!nodeB"):
                for _ in range(3):
                    transport.inject_message("!menu", node_id=node)
            await asyncio.sleep(0.5)

        notified = {n for n, m in transport.sent_messages if "Rate limited" in m}
        assert notified == {"!nodeA", "!nodeB"}

    def test_notification_window_resets(self, rate_limited_server) -> None:
        server, _ = rate_limited_server

        assert server._should_notify_rate_limit("!n") is True
        assert server._should_notify_rate_limit("!n") is False

        # Wind the record back past the window.
        server._rate_limit_notified["!n"] -= 61

        assert server._should_notify_rate_limit("!n") is True


class ClosablePlugin(HTTPPluginBase):
    """Plugin that records whether its client was closed."""

    def __init__(self) -> None:
        super().__init__(timeout=5.0, service_name="test")
        self.closed = False

    @property
    def metadata(self) -> PluginMetadata:
        return PluginMetadata(name="Closable", description="d", menu_number=1, commands=())

    def get_welcome_message(self) -> str:
        return "hi"

    def get_help_text(self) -> str:
        return "help"

    async def handle(
        self, message: str, context: NodeContext, plugin_state: dict[str, Any]
    ) -> PluginResponse:
        return PluginResponse(message="ok")

    async def aclose(self) -> None:
        self.closed = True
        await super().aclose()


class ExplodingPlugin(Plugin):
    """Plugin whose aclose() raises, to check shutdown is not derailed."""

    @property
    def metadata(self) -> PluginMetadata:
        return PluginMetadata(name="Exploding", description="d", menu_number=2, commands=())

    def get_welcome_message(self) -> str:
        return "hi"

    def get_help_text(self) -> str:
        return "help"

    async def handle(
        self, message: str, context: NodeContext, plugin_state: dict[str, Any]
    ) -> PluginResponse:
        return PluginResponse(message="ok")

    async def aclose(self) -> None:
        raise RuntimeError("boom")


class TestPluginClientShutdown:
    """HTTP clients are now shared per plugin, so stop() must close them."""

    def _bare_server(self) -> tuple[HandlerServer, MockTransport]:
        transport = MockTransport()
        server = HandlerServer(config=Config.default(), transport=transport)
        for existing in server.registry.get_all_plugins():
            server.registry.unregister(existing.metadata.name)
        return server, transport

    async def test_plugin_client_closed_on_stop(self) -> None:
        server, _ = self._bare_server()
        plugin = ClosablePlugin()
        server.registry.register(plugin)

        await server.stop()

        assert plugin.closed

    async def test_underlying_httpx_client_is_closed(self) -> None:
        server, _ = self._bare_server()
        plugin = ClosablePlugin()
        server.registry.register(plugin)
        client = plugin._get_client()

        await server.stop()

        assert client.is_closed

    async def test_failing_aclose_does_not_stop_shutdown(self) -> None:
        """One bad plugin must not prevent the others from closing."""
        server, _ = self._bare_server()
        good = ClosablePlugin()
        server.registry.register(ExplodingPlugin())
        server.registry.register(good)

        await server.stop()

        assert good.closed
        assert not server.is_running

    async def test_plugin_without_aclose_is_skipped(self) -> None:
        """Plugins predating the hook have no aclose() and must be tolerated."""
        from tests.mocks import MockPlugin

        server, _ = self._bare_server()
        server.registry.register(MockPlugin(name="Plain", menu_number=3))

        await server.stop()

        assert not server.is_running


class TestHTTPClientReuse:
    """The client is created once per plugin, not per request."""

    def test_same_client_returned(self) -> None:
        plugin = ClosablePlugin()
        assert plugin._get_client() is plugin._get_client()

    async def test_client_recreated_after_close(self) -> None:
        plugin = ClosablePlugin()
        first = plugin._get_client()
        await plugin.aclose()

        assert plugin._get_client() is not first

    def test_client_follows_redirects(self) -> None:
        """Wikipedia returns 302 for redirect titles; httpx defaults to False."""
        assert ClosablePlugin()._get_client().follow_redirects is True
