"""Shared test fixtures for pytest."""

import asyncio
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

import pytest

from meshgate.config import Config
from meshgate.core.plugin_registry import PluginRegistry
from meshgate.core.session import Session
from meshgate.core.session_manager import SessionManager
from meshgate.interfaces.node_context import GPSLocation, NodeContext
from meshgate.server import HandlerServer
from tests.mocks import MockPlugin, MockTransport


@pytest.fixture
def node_context() -> NodeContext:
    """Create a test NodeContext."""
    return NodeContext(
        node_id="!test123",
        node_name="Test Node",
        location=GPSLocation(latitude=40.7128, longitude=-74.0060),
    )


@pytest.fixture
def context() -> NodeContext:
    """Create a simple test NodeContext (alias for common test use)."""
    return NodeContext(node_id="!test123")


@pytest.fixture
def session() -> Session:
    """Create a test Session."""
    return Session(node_id="!test123")


@pytest.fixture
def session_manager() -> SessionManager:
    """Create a test SessionManager."""
    return SessionManager(session_timeout_minutes=60)


@pytest.fixture
def plugin_registry() -> PluginRegistry:
    """Create a test PluginRegistry."""
    return PluginRegistry()


@pytest.fixture
def mock_plugin() -> MockPlugin:
    """Create a MockPlugin."""
    return MockPlugin()


@pytest.fixture
def mock_transport() -> MockTransport:
    """Create a MockTransport."""
    return MockTransport()


@pytest.fixture
def default_config() -> Config:
    """Create default configuration."""
    return Config.default()


@asynccontextmanager
async def running_server(server: HandlerServer) -> AsyncGenerator[HandlerServer]:
    """Async context manager that starts a server and stops it on exit.

    Usage:
        async with running_server(server) as srv:
            # server is running, do tests
            mock_transport.inject_message(...)
        # server is stopped automatically
    """
    server_task = asyncio.create_task(server.start())
    await asyncio.sleep(0.1)  # Wait for server to start
    try:
        yield server
    finally:
        await server.stop()
        server_task.cancel()
        try:
            await server_task
        except asyncio.CancelledError:
            pass
