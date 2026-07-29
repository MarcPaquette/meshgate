"""Tests for the dashboard's request guards.

Binding to loopback is not sufficient on its own. A page the operator visits
can send a cross-origin form POST to 127.0.0.1 with no CORS preflight, and DNS
rebinding can point an attacker-controlled hostname at loopback to read
responses back. These tests pin the guards that close both holes.
"""

import pytest
from httpx import AsyncClient

from meshgate.server import HandlerServer
from meshgate.web.security import CSRF_HEADER, _host_is_local
from tests.web.conftest import LOCAL_HEADERS, WRITE_HEADERS

MUTATING_REQUESTS = [
    ("POST", "/api/plugins/Weather/disable"),
    ("POST", "/api/plugins/Weather/enable"),
    ("DELETE", "/api/sessions/!node"),
]


class TestCsrfGuard:
    """State-changing requests need a header a form POST cannot set."""

    @pytest.mark.parametrize(("method", "path"), MUTATING_REQUESTS)
    async def test_rejected_without_header(
        self, client: AsyncClient, method: str, path: str
    ) -> None:
        response = await client.request(method, path, headers=LOCAL_HEADERS)

        assert response.status_code == 403
        assert CSRF_HEADER in response.json()["detail"]

    @pytest.mark.parametrize(("method", "path"), MUTATING_REQUESTS)
    async def test_allowed_with_header(
        self, client: AsyncClient, server: HandlerServer, method: str, path: str
    ) -> None:
        server.session_manager.get_session("!node")

        response = await client.request(method, path, headers=WRITE_HEADERS)

        assert response.status_code != 403

    async def test_state_is_unchanged_when_rejected(
        self, client: AsyncClient, server: HandlerServer
    ) -> None:
        """A blocked request must not have taken effect."""
        before = server.registry.version

        await client.post("/api/plugins/Weather/disable", headers=LOCAL_HEADERS)

        assert server.registry.version == before
        assert server.registry.get_by_name("Weather") is not None

    async def test_reads_do_not_need_the_header(self, client: AsyncClient) -> None:
        response = await client.get("/api/status", headers=LOCAL_HEADERS)

        assert response.status_code == 200


class TestHostGuard:
    """Defeats DNS rebinding: the attacker's hostname travels in Host."""

    async def test_rejects_foreign_host(self, client: AsyncClient) -> None:
        response = await client.get("/api/status", headers={"host": "evil.example.com"})

        assert response.status_code == 421

    async def test_rejects_foreign_host_on_mutation(
        self, client: AsyncClient, server: HandlerServer
    ) -> None:
        response = await client.post(
            "/api/plugins/Weather/disable",
            headers={"host": "evil.example.com", CSRF_HEADER: "1"},
        )

        assert response.status_code == 421
        assert server.registry.get_by_name("Weather") is not None

    async def test_accepts_loopback_variants(self, client: AsyncClient) -> None:
        for host in ("127.0.0.1:8080", "127.0.0.1", "localhost:8080", "localhost"):
            response = await client.get("/api/status", headers={"host": host})
            assert response.status_code == 200, host

    async def test_rejects_rebinding_style_hostname(self, client: AsyncClient) -> None:
        """A name that resolves to loopback still carries its own Host."""
        response = await client.get("/api/status", headers={"host": "127.0.0.1.attacker.example"})

        assert response.status_code == 421


class TestHostParsing:
    """Unit coverage for the Host matcher."""

    @pytest.mark.parametrize(
        "host",
        ["localhost", "localhost:8080", "127.0.0.1", "127.0.0.1:9999", "[::1]:8080", "::1"],
    )
    def test_local_hosts(self, host: str) -> None:
        assert _host_is_local(host) is True

    @pytest.mark.parametrize(
        "host",
        [
            "",
            "evil.com",
            "evil.com:8080",
            "127.0.0.1.evil.com",
            "localhost.evil.com",
            "192.168.1.5:8080",
            "0.0.0.0",
        ],
    )
    def test_non_local_hosts(self, host: str) -> None:
        assert _host_is_local(host) is False

    def test_case_insensitive(self) -> None:
        assert _host_is_local("LOCALHOST:8080") is True


class TestNoCors:
    """Cross-origin reads should stay blocked - no CORS middleware installed."""

    async def test_no_allow_origin_header(self, client: AsyncClient) -> None:
        response = await client.get(
            "/api/status", headers={**LOCAL_HEADERS, "origin": "https://evil.example.com"}
        )

        assert "access-control-allow-origin" not in {k.lower() for k in response.headers}

    async def test_preflight_is_not_permitted(self, client: AsyncClient) -> None:
        response = await client.request(
            "OPTIONS",
            "/api/plugins/Weather/disable",
            headers={
                **LOCAL_HEADERS,
                "origin": "https://evil.example.com",
                "access-control-request-method": "POST",
            },
        )

        # Without CORS middleware there is no successful preflight.
        assert response.status_code >= 400
        assert "access-control-allow-origin" not in {k.lower() for k in response.headers}
