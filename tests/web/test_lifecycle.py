"""Tests for running the dashboard alongside the gateway.

The dashboard is a peer asyncio task sharing the gateway's event loop. It must
come up on a real socket, shut down cleanly when cancelled, and never be a hard
dependency when disabled.
"""

import asyncio
import socket

import httpx
import pytest

from meshgate.config import Config
from meshgate.server import HandlerServer
from meshgate.web.app import serve
from tests.mocks import MockTransport


def free_port() -> int:
    """Find an unused TCP port."""
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


class TestServeOverARealSocket:
    """serve() runs uvicorn on the caller's loop."""

    async def test_serves_and_shuts_down(self) -> None:
        config = Config.default()
        config.web.enabled = True
        config.web.port = free_port()
        server = HandlerServer(config=config, transport=MockTransport())

        task = asyncio.ensure_future(serve(server))
        try:
            # Wait for the listener rather than sleeping a fixed amount.
            base = f"http://127.0.0.1:{config.web.port}"
            async with httpx.AsyncClient(base_url=base, timeout=5.0) as client:
                for _ in range(50):
                    try:
                        response = await client.get("/api/status")
                        break
                    except httpx.ConnectError:
                        await asyncio.sleep(0.1)
                else:
                    pytest.fail("dashboard never started listening")

                assert response.status_code == 200
                assert response.json()["running"] is False
        finally:
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)

        # The listening socket must actually be closed. uvicorn does not do
        # this on cancellation by itself, so serve() shuts it down explicitly;
        # without that the port stays bound.
        with socket.socket() as s:
            s.bind(("127.0.0.1", config.web.port))

    async def test_cancelling_stops_the_task(self) -> None:
        config = Config.default()
        config.web.enabled = True
        config.web.port = free_port()
        server = HandlerServer(config=config, transport=MockTransport())

        task = asyncio.ensure_future(serve(server))
        await asyncio.sleep(0.5)

        task.cancel()
        await asyncio.gather(task, return_exceptions=True)

        assert task.done()

    async def test_warns_when_not_bound_to_loopback(self, caplog: pytest.LogCaptureFixture) -> None:
        """Exposing transcripts off-loopback with no auth must be announced."""
        import logging

        config = Config.default()
        config.web.enabled = True
        config.web.host = "0.0.0.0"  # noqa: S104 - deliberately testing this case
        config.web.port = free_port()
        server = HandlerServer(config=config, transport=MockTransport())

        with caplog.at_level(logging.WARNING):
            task = asyncio.ensure_future(serve(server))
            await asyncio.sleep(0.5)
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)

        assert "SECURITY" in caplog.text
        assert "authentication" in caplog.text


class TestGatewayAndDashboardTogether:
    """Both tasks run on one loop; the gateway keeps serving the mesh."""

    async def test_mesh_traffic_flows_while_dashboard_is_up(self) -> None:
        config = Config.default()
        config.web.enabled = True
        config.web.transcript_enabled = True
        config.web.port = free_port()
        transport = MockTransport()
        server = HandlerServer(config=config, transport=transport)

        server_task = asyncio.ensure_future(server.start())
        web_task = asyncio.ensure_future(serve(server))
        try:
            base = f"http://127.0.0.1:{config.web.port}"
            async with httpx.AsyncClient(base_url=base, timeout=5.0) as client:
                for _ in range(50):
                    try:
                        await client.get("/api/status")
                        break
                    except httpx.ConnectError:
                        await asyncio.sleep(0.1)

                transport.inject_message("", node_id="!alice")
                await asyncio.sleep(0.4)

                sessions = (await client.get("/api/sessions")).json()
                assert [s["node_id"] for s in sessions] == ["!alice"]

                status = (await client.get("/api/status")).json()
                assert status["running"] is True
                assert status["active_sessions"] == 1
        finally:
            web_task.cancel()
            server_task.cancel()
            await asyncio.gather(web_task, server_task, return_exceptions=True)
            await server.stop()

    async def test_dashboard_changes_affect_the_mesh_menu(self) -> None:
        """Disabling a plugin over HTTP must change what nodes are offered."""
        config = Config.default()
        config.web.enabled = True
        config.web.port = free_port()
        transport = MockTransport()
        server = HandlerServer(config=config, transport=transport)

        server_task = asyncio.ensure_future(server.start())
        web_task = asyncio.ensure_future(serve(server))
        try:
            base = f"http://127.0.0.1:{config.web.port}"
            async with httpx.AsyncClient(base_url=base, timeout=5.0) as client:
                for _ in range(50):
                    try:
                        await client.get("/api/status")
                        break
                    except httpx.ConnectError:
                        await asyncio.sleep(0.1)

                await client.post("/api/plugins/Weather/disable", headers={"X-Meshgate": "1"})

                transport.inject_message("", node_id="!bob")
                await asyncio.sleep(0.4)

            menu = [m for n, m in transport.sent_messages if n == "!bob"]
            assert menu
            assert "Weather" not in " ".join(menu)
        finally:
            web_task.cancel()
            server_task.cancel()
            await asyncio.gather(web_task, server_task, return_exceptions=True)
            await server.stop()


class TestOptionalDependency:
    """The web extra must not be required when the dashboard is off."""

    def test_core_imports_do_not_pull_in_web_deps(self) -> None:
        """A plain `uv sync` install must be able to run the gateway."""
        import subprocess
        import sys

        result = subprocess.run(
            [
                sys.executable,
                "-c",
                "import sys; import meshgate.cli, meshgate.server; "
                "leaked = [m for m in sys.modules "
                "if m.split('.')[0] in {'fastapi','uvicorn','starlette'}]; "
                "sys.exit(1 if leaked else 0)",
            ],
            capture_output=True,
            timeout=60,
        )

        assert result.returncode == 0, "core imports must not require the web extra"
