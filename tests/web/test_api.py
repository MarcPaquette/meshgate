"""Tests for the dashboard API endpoints."""

from httpx import ASGITransport, AsyncClient

from meshgate.server import HandlerServer
from meshgate.web.app import create_app
from tests.web.conftest import LOCAL_HEADERS, WRITE_HEADERS, build_server


class TestStatus:
    """GET /api/status."""

    async def test_reports_gateway_state(self, client: AsyncClient, server: HandlerServer) -> None:
        body = (await client.get("/api/status")).json()

        assert body["enabled_plugins"] == 4
        assert body["disabled_plugins"] == 0
        assert body["active_sessions"] == 0
        assert body["transcripts_enabled"] is True
        assert body["rate_limit"]["enabled"] is False

    async def test_counts_sessions(self, client: AsyncClient, server: HandlerServer) -> None:
        server.session_manager.get_session("!a")
        server.session_manager.get_session("!b")

        body = (await client.get("/api/status")).json()

        assert body["active_sessions"] == 2

    async def test_reflects_disabled_plugin(
        self, client: AsyncClient, server: HandlerServer
    ) -> None:
        server.registry.disable("Weather")

        body = (await client.get("/api/status")).json()

        assert body["enabled_plugins"] == 3
        assert body["disabled_plugins"] == 1


class TestPlugins:
    """GET /api/plugins and the toggle endpoints."""

    async def test_lists_all_with_state(self, client: AsyncClient) -> None:
        plugins = (await client.get("/api/plugins")).json()

        assert len(plugins) == 4
        assert all(p["enabled"] for p in plugins)
        assert [p["menu_number"] for p in plugins] == [1, 2, 3, 4]

    async def test_includes_metadata(self, client: AsyncClient) -> None:
        plugins = (await client.get("/api/plugins")).json()
        wikipedia = next(p for p in plugins if p["name"] == "Wikipedia")

        assert wikipedia["description"]
        assert "!search" in wikipedia["commands"]

    async def test_etag_tracks_registry_version(
        self, client: AsyncClient, server: HandlerServer
    ) -> None:
        first = await client.get("/api/plugins")
        etag = first.headers["ETag"]

        # Unchanged registry keeps the same tag.
        assert (await client.get("/api/plugins")).headers["ETag"] == etag

        server.registry.disable("Weather")
        assert (await client.get("/api/plugins")).headers["ETag"] != etag

    async def test_disable_then_enable(self, client: AsyncClient, server: HandlerServer) -> None:
        response = await client.post("/api/plugins/Weather/disable", headers=WRITE_HEADERS)
        assert response.status_code == 200
        assert response.json()["ok"] is True
        assert server.registry.get_by_name("Weather") is None

        response = await client.post("/api/plugins/Weather/enable", headers=WRITE_HEADERS)
        assert response.status_code == 200
        assert server.registry.get_by_name("Weather") is not None

    async def test_disabled_plugin_leaves_the_menu(
        self, client: AsyncClient, server: HandlerServer
    ) -> None:
        await client.post("/api/plugins/Weather/disable", headers=WRITE_HEADERS)

        assert "Weather" not in server.router.get_menu()

        plugins = (await client.get("/api/plugins")).json()
        weather = next(p for p in plugins if p["name"] == "Weather")
        assert weather["enabled"] is False
        # Still listed, and still holding its slot.
        assert weather["menu_number"] == 3

    async def test_unknown_plugin_404s(self, client: AsyncClient) -> None:
        response = await client.post("/api/plugins/Nope/disable", headers=WRITE_HEADERS)

        assert response.status_code == 404

    async def test_toggling_twice_is_idempotent(self, client: AsyncClient) -> None:
        await client.post("/api/plugins/Weather/disable", headers=WRITE_HEADERS)
        again = await client.post("/api/plugins/Weather/disable", headers=WRITE_HEADERS)

        assert again.status_code == 200
        assert again.json()["ok"] is True


class TestSessions:
    """GET /api/sessions and friends."""

    async def test_empty_by_default(self, client: AsyncClient) -> None:
        assert (await client.get("/api/sessions")).json() == []

    async def test_lists_sessions_most_recent_first(
        self, client: AsyncClient, server: HandlerServer
    ) -> None:
        server.session_manager.get_session("!older")
        server.session_manager.get_session("!newer")

        sessions = (await client.get("/api/sessions")).json()

        assert [s["node_id"] for s in sessions] == ["!newer", "!older"]

    async def test_reports_active_plugin(self, client: AsyncClient, server: HandlerServer) -> None:
        server.session_manager.get_session("!node").enter_plugin("Weather")

        sessions = (await client.get("/api/sessions")).json()

        assert sessions[0]["active_plugin"] == "Weather"
        assert sessions[0]["at_menu"] is False

    async def test_detail_includes_plugin_state(
        self, client: AsyncClient, server: HandlerServer
    ) -> None:
        session = server.session_manager.get_session("!node")
        session.enter_plugin("Wikipedia")
        session.update_plugin_state({"last_results": ["Alpha"]})

        body = (await client.get("/api/sessions/!node")).json()

        assert body["plugin_state"] == {"last_results": ["Alpha"]}

    async def test_detail_404_for_unknown(self, client: AsyncClient) -> None:
        assert (await client.get("/api/sessions/!ghost")).status_code == 404

    async def test_end_session(self, client: AsyncClient, server: HandlerServer) -> None:
        server.session_manager.get_session("!node")

        response = await client.delete("/api/sessions/!node", headers=WRITE_HEADERS)

        assert response.status_code == 200
        assert server.session_manager.get_existing_session("!node") is None

    async def test_end_session_discards_transcript(
        self, client: AsyncClient, server: HandlerServer
    ) -> None:
        server.session_manager.get_session("!node")
        server.transcript.record_inbound("!node", "private")

        await client.delete("/api/sessions/!node", headers=WRITE_HEADERS)

        assert server.transcript.get("!node") == []

    async def test_end_unknown_session_404s(self, client: AsyncClient) -> None:
        response = await client.delete("/api/sessions/!ghost", headers=WRITE_HEADERS)

        assert response.status_code == 404


class TestTranscripts:
    """GET /api/sessions/{node}/transcript."""

    async def test_returns_recorded_messages(
        self, client: AsyncClient, server: HandlerServer
    ) -> None:
        server.transcript.record_inbound("!node", "hello")
        server.transcript.record_outbound("!node", "hi there")

        body = (await client.get("/api/sessions/!node/transcript")).json()

        assert [m["direction"] for m in body["messages"]] == ["inbound", "outbound"]
        assert [m["text"] for m in body["messages"]] == ["hello", "hi there"]

    async def test_404_when_recording_disabled(self) -> None:
        server = build_server(transcript_enabled=False)
        app = create_app(server)
        async with AsyncClient(
            transport=ASGITransport(app=app),
            base_url="http://127.0.0.1:8080",
            headers=LOCAL_HEADERS,
        ) as ac:
            response = await ac.get("/api/sessions/!node/transcript")

        assert response.status_code == 404
        assert "disabled" in response.json()["detail"].lower()

    async def test_status_reports_disabled(self) -> None:
        server = build_server(transcript_enabled=False)
        app = create_app(server)
        async with AsyncClient(
            transport=ASGITransport(app=app),
            base_url="http://127.0.0.1:8080",
            headers=LOCAL_HEADERS,
        ) as ac:
            body = (await ac.get("/api/status")).json()

        assert body["transcripts_enabled"] is False


class TestLogs:
    """GET /api/logs."""

    async def test_reports_unavailable_without_a_buffer(self, client: AsyncClient) -> None:
        """No buffer attached in tests unless one is set explicitly."""
        body = (await client.get("/api/logs")).json()

        assert body["available"] is False
        assert body["records"] == []

    async def test_returns_records_when_buffer_attached(self, client: AsyncClient) -> None:
        import logging

        from meshgate.core.log_buffer import (
            RingBufferHandler,
            get_active_buffer,
            set_active_buffer,
        )

        original = get_active_buffer()
        handler = RingBufferHandler(capacity=10)
        log = logging.getLogger("meshgate.web.test")
        log.addHandler(handler)
        log.setLevel(logging.INFO)
        set_active_buffer(handler)
        try:
            log.info("first")
            log.info("second")

            body = (await client.get("/api/logs")).json()
            assert body["available"] is True
            assert [r["message"] for r in body["records"]] == ["first", "second"]

            # Cursor returns only newer records.
            after = (await client.get(f"/api/logs?since={body['records'][0]['seq']}")).json()
            assert [r["message"] for r in after["records"]] == ["second"]
        finally:
            log.removeHandler(handler)
            set_active_buffer(original)

    async def test_rejects_negative_cursor(self, client: AsyncClient) -> None:
        assert (await client.get("/api/logs?since=-1")).status_code == 422


class TestDashboardPage:
    """The static page is served."""

    async def test_index_is_html(self, client: AsyncClient) -> None:
        response = await client.get("/")

        assert response.status_code == 200
        assert "text/html" in response.headers["content-type"]
        assert "Meshgate" in response.text

    async def test_static_assets_served(self, client: AsyncClient) -> None:
        assert (await client.get("/static/app.js")).status_code == 200
        assert (await client.get("/static/style.css")).status_code == 200
