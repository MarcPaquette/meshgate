"""Shared test fixtures for pytest."""

import pytest

from meshtastic_handler.config import Config
from meshtastic_handler.core.plugin_registry import PluginRegistry
from meshtastic_handler.core.session import Session
from meshtastic_handler.core.session_manager import SessionManager
from meshtastic_handler.interfaces.node_context import GPSLocation, NodeContext
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
def node_context_no_gps() -> NodeContext:
    """Create a test NodeContext without GPS."""
    return NodeContext(node_id="!test456", node_name="No GPS Node")


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
