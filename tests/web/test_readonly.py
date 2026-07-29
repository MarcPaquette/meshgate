"""The dashboard must never mutate gateway state by being read.

This is the most important test in the suite. SessionManager.get_session()
creates a session, refreshes its activity, and reorders the LRU, so a handler
that reached for it instead of get_existing_session() would invent sessions
merely by rendering a page - and would silently corrupt eviction order.
RateLimiter.check() has the same problem: it records a request.
"""

from httpx import AsyncClient

from meshgate.server import HandlerServer

# Every GET the dashboard exposes.
READ_PATHS = [
    "/api/status",
    "/api/plugins",
    "/api/sessions",
    "/api/sessions/!known",
    "/api/sessions/!known/transcript",
    "/api/logs",
    "/api/logs?since=1",
]


class TestReadsDoNotCreateSessions:
    """Reading must not bring sessions into existence."""

    async def test_no_session_is_created_by_any_get(
        self, client: AsyncClient, server: HandlerServer
    ) -> None:
        assert server.session_manager.active_session_count == 0

        for path in READ_PATHS:
            await client.get(path)

        assert server.session_manager.active_session_count == 0

    async def test_unknown_session_404s_without_creating(
        self, client: AsyncClient, server: HandlerServer
    ) -> None:
        response = await client.get("/api/sessions/!ghost")

        assert response.status_code == 404
        assert server.session_manager.get_existing_session("!ghost") is None
        assert server.session_manager.active_session_count == 0

    async def test_transcript_of_unknown_node_creates_nothing(
        self, client: AsyncClient, server: HandlerServer
    ) -> None:
        response = await client.get("/api/sessions/!ghost/transcript")

        assert response.status_code == 200
        assert response.json()["messages"] == []
        assert server.session_manager.active_session_count == 0


class TestReadsDoNotTouchActivity:
    """Reading must not refresh a session's activity or reorder the LRU."""

    async def test_last_activity_unchanged(
        self, client: AsyncClient, server: HandlerServer
    ) -> None:
        session = server.session_manager.get_session("!known")
        session.enter_plugin("Weather")
        before_activity = session.last_activity
        before_monotonic = session.last_activity_monotonic

        for path in READ_PATHS:
            await client.get(path)

        assert session.last_activity == before_activity
        assert session.last_activity_monotonic == before_monotonic

    async def test_lru_order_unchanged(self, client: AsyncClient, server: HandlerServer) -> None:
        """Eviction order must survive being read."""
        for node in ("!first", "!second", "!third"):
            server.session_manager.get_session(node)

        before = [s.node_id for s in server.session_manager.list_sessions()]

        for path in READ_PATHS + ["/api/sessions/!first"]:
            await client.get(path)

        after = [s.node_id for s in server.session_manager.list_sessions()]
        assert after == before

    async def test_plugin_state_is_copied_not_shared(
        self, client: AsyncClient, server: HandlerServer
    ) -> None:
        """The response must not hand out the live plugin_state dict."""
        session = server.session_manager.get_session("!known")
        session.enter_plugin("Wikipedia")
        session.update_plugin_state({"last_results": ["a", "b"]})

        response = await client.get("/api/sessions/!known")
        assert response.json()["plugin_state"]["last_results"] == ["a", "b"]

        # Mutating the live session afterwards must not have been pre-empted,
        # and the earlier response must not have aliased it.
        session.plugin_state["last_results"].append("c")
        again = await client.get("/api/sessions/!known")
        assert len(again.json()["plugin_state"]["last_results"]) == 3


class TestReadsDoNotConsumeRateLimit:
    """Reading status must not count as traffic against a node."""

    async def test_tracked_node_count_unchanged(
        self, client: AsyncClient, server: HandlerServer
    ) -> None:
        before = server.rate_limiter.tracked_node_count

        for _ in range(5):
            await client.get("/api/status")

        assert server.rate_limiter.tracked_node_count == before


class TestReadsDoNotAlterPlugins:
    """Reading the plugin list must not change registration."""

    async def test_registry_version_unchanged(
        self, client: AsyncClient, server: HandlerServer
    ) -> None:
        before = server.registry.version

        for _ in range(3):
            await client.get("/api/plugins")

        assert server.registry.version == before

    async def test_plugin_count_unchanged(self, client: AsyncClient, server: HandlerServer) -> None:
        before = server.registry.plugin_count

        for path in READ_PATHS:
            await client.get(path)

        assert server.registry.plugin_count == before


class TestReadsDoNotRecordTranscripts:
    """Viewing a transcript must not append to it."""

    async def test_transcript_length_unchanged(
        self, client: AsyncClient, server: HandlerServer
    ) -> None:
        server.transcript.record_inbound("!known", "hello")
        before = len(server.transcript.get("!known"))

        for _ in range(3):
            await client.get("/api/sessions/!known/transcript")

        assert len(server.transcript.get("!known")) == before
