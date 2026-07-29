"""Fixtures for dashboard tests.

Requests go through httpx's ASGI transport, so no socket is opened and the
handlers run on the test's own event loop - the same arrangement as production,
where the dashboard shares the gateway's loop.
"""

from collections.abc import AsyncIterator

import pytest
from httpx import ASGITransport, AsyncClient

from meshgate.config import Config
from meshgate.server import HandlerServer
from meshgate.web.app import create_app
from meshgate.web.security import CSRF_HEADER
from tests.mocks import MockTransport

# Host must look like loopback or the DNS-rebinding guard rejects the request.
LOCAL_HEADERS = {"host": "127.0.0.1:8080"}
# Mutating requests additionally need the CSRF header.
WRITE_HEADERS = {**LOCAL_HEADERS, CSRF_HEADER: "1"}


def build_server(**web_overrides) -> HandlerServer:
    """Build a gateway with the dashboard configured.

    Args:
        **web_overrides: Fields to override on config.web
    """
    config = Config.default()
    config.web.enabled = True
    for key, value in web_overrides.items():
        setattr(config.web, key, value)
    return HandlerServer(config=config, transport=MockTransport())


@pytest.fixture
def server() -> HandlerServer:
    """Gateway with transcripts enabled."""
    return build_server(transcript_enabled=True)


@pytest.fixture
async def client(server: HandlerServer) -> AsyncIterator[AsyncClient]:
    """Client bound to the dashboard app, with loopback headers preset."""
    app = create_app(server)
    transport = ASGITransport(app=app)
    async with AsyncClient(
        transport=transport, base_url="http://127.0.0.1:8080", headers=LOCAL_HEADERS
    ) as ac:
        yield ac
