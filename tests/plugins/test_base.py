"""Tests for plugin base classes."""

from typing import Any

import httpx
import pytest
import respx
from httpx import Response

from meshgate.interfaces.node_context import NodeContext
from meshgate.interfaces.plugin import PluginMetadata, PluginResponse
from meshgate.plugins.base import HTTPPluginBase


class ConcreteHTTPPlugin(HTTPPluginBase):
    """Concrete implementation for testing."""

    def __init__(self, timeout: float = 5.0) -> None:
        super().__init__(timeout=timeout, service_name="Test Service")

    @property
    def metadata(self) -> PluginMetadata:
        return PluginMetadata(
            name="Test HTTP Plugin",
            description="For testing",
            menu_number=99,
        )

    def get_welcome_message(self) -> str:
        return "Welcome to test plugin"

    def get_help_text(self) -> str:
        return "Test help"

    async def handle(
        self, message: str, context: NodeContext, plugin_state: dict[str, Any]
    ) -> PluginResponse:
        return PluginResponse(message="Test response")


class TestHTTPPluginBase:
    """Tests for HTTPPluginBase class."""

    @pytest.fixture
    def plugin(self) -> ConcreteHTTPPlugin:
        """Create a concrete HTTP plugin."""
        return ConcreteHTTPPlugin(timeout=5.0)

    def test_timeout_property(self, plugin: ConcreteHTTPPlugin) -> None:
        """Test timeout property."""
        assert plugin.timeout == 5.0

    def test_default_timeout(self) -> None:
        """Test default timeout value."""
        plugin = ConcreteHTTPPlugin()
        assert plugin.timeout == 5.0

    def test_service_name_property(self, plugin: ConcreteHTTPPlugin) -> None:
        """Test service_name property."""
        assert plugin.service_name == "Test Service"

    def test_create_client(self, plugin: ConcreteHTTPPlugin) -> None:
        """Test _create_client returns configured client."""
        client = plugin._create_client()
        assert isinstance(client, httpx.AsyncClient)

    @pytest.mark.asyncio
    @respx.mock
    async def test_safe_request_success(self, plugin: ConcreteHTTPPlugin) -> None:
        """Test _safe_request with successful response."""
        respx.get("https://example.com/api").mock(return_value=Response(200, json={"key": "value"}))

        async with plugin._create_client() as client:
            result = await plugin._safe_request(client.get, "https://example.com/api")

        assert isinstance(result, httpx.Response)
        assert result.json() == {"key": "value"}

    @pytest.mark.asyncio
    @respx.mock
    async def test_safe_request_connect_error(self, plugin: ConcreteHTTPPlugin) -> None:
        """Test _safe_request with connection error."""
        respx.get("https://example.com/api").mock(
            side_effect=httpx.ConnectError("Connection refused")
        )

        async with plugin._create_client() as client:
            result = await plugin._safe_request(client.get, "https://example.com/api")

        assert isinstance(result, PluginResponse)
        assert "Cannot connect" in result.message
        assert "Test Service" in result.message

    @pytest.mark.asyncio
    @respx.mock
    async def test_safe_request_timeout(self, plugin: ConcreteHTTPPlugin) -> None:
        """Test _safe_request with timeout."""
        respx.get("https://example.com/api").mock(side_effect=httpx.TimeoutException("Timeout"))

        async with plugin._create_client() as client:
            result = await plugin._safe_request(client.get, "https://example.com/api")

        assert isinstance(result, PluginResponse)
        assert "timed out" in result.message

    @pytest.mark.asyncio
    @respx.mock
    async def test_safe_request_http_error(self, plugin: ConcreteHTTPPlugin) -> None:
        """Test _safe_request with HTTP error status."""
        respx.get("https://example.com/api").mock(return_value=Response(500, text="Server Error"))

        async with plugin._create_client() as client:
            result = await plugin._safe_request(client.get, "https://example.com/api")

        assert isinstance(result, PluginResponse)
        assert "500" in result.message

    @pytest.mark.asyncio
    @respx.mock
    async def test_fetch_json_success(self, plugin: ConcreteHTTPPlugin) -> None:
        """Test _fetch_json with successful response."""
        respx.get("https://example.com/api").mock(return_value=Response(200, json={"data": "test"}))

        result = await plugin._fetch_json("https://example.com/api")

        assert isinstance(result, dict)
        assert result["data"] == "test"

    @pytest.mark.asyncio
    @respx.mock
    async def test_fetch_json_with_params(self, plugin: ConcreteHTTPPlugin) -> None:
        """Test _fetch_json with query parameters."""
        respx.get("https://example.com/api").mock(return_value=Response(200, json={"result": "ok"}))

        result = await plugin._fetch_json("https://example.com/api", params={"key": "value"})

        assert isinstance(result, dict)
        assert result["result"] == "ok"

    @pytest.mark.asyncio
    @respx.mock
    async def test_fetch_json_error(self, plugin: ConcreteHTTPPlugin) -> None:
        """Test _fetch_json with error response."""
        respx.get("https://example.com/api").mock(side_effect=httpx.ConnectError("Failed"))

        result = await plugin._fetch_json("https://example.com/api")

        assert isinstance(result, PluginResponse)
        assert "Cannot connect" in result.message

    @pytest.mark.asyncio
    @respx.mock
    async def test_post_json_success(self, plugin: ConcreteHTTPPlugin) -> None:
        """Test _post_json with successful response."""
        respx.post("https://example.com/api").mock(
            return_value=Response(200, json={"created": True})
        )

        result = await plugin._post_json("https://example.com/api", json_data={"name": "test"})

        assert isinstance(result, dict)
        assert result["created"] is True

    @pytest.mark.asyncio
    @respx.mock
    async def test_post_json_error(self, plugin: ConcreteHTTPPlugin) -> None:
        """Test _post_json with error."""
        respx.post("https://example.com/api").mock(return_value=Response(400, text="Bad Request"))

        result = await plugin._post_json("https://example.com/api", json_data={"invalid": "data"})

        assert isinstance(result, PluginResponse)
        assert "400" in result.message

    def test_error_response(self, plugin: ConcreteHTTPPlugin) -> None:
        """Test _error_response helper."""
        response = plugin._error_response("Something went wrong")

        assert response.message == "Something went wrong"
        assert response.plugin_state is None

    def test_error_response_with_state(self, plugin: ConcreteHTTPPlugin) -> None:
        """Test _error_response with preserved state."""
        response = plugin._error_response("Error", plugin_state={"key": "value"})

        assert response.message == "Error"
        assert response.plugin_state == {"key": "value"}

    def test_success_response(self, plugin: ConcreteHTTPPlugin) -> None:
        """Test _success_response helper."""
        response = plugin._success_response("All good")

        assert response.message == "All good"
        assert response.plugin_state is None
        assert response.exit_plugin is False

    def test_success_response_with_exit(self, plugin: ConcreteHTTPPlugin) -> None:
        """Test _success_response with exit flag."""
        response = plugin._success_response(
            "Done",
            plugin_state={"final": True},
            exit_plugin=True,
        )

        assert response.message == "Done"
        assert response.plugin_state == {"final": True}
        assert response.exit_plugin is True

    def test_truncate_within_limit(self, plugin: ConcreteHTTPPlugin) -> None:
        """Test _truncate when text is within limit."""
        text = "Short text"
        result = plugin._truncate(text, 100)
        assert result == text

    def test_truncate_at_exact_limit(self, plugin: ConcreteHTTPPlugin) -> None:
        """Test _truncate when text is exactly at limit."""
        text = "Exactly10c"
        result = plugin._truncate(text, 10)
        assert result == text

    def test_truncate_exceeds_limit(self, plugin: ConcreteHTTPPlugin) -> None:
        """Test _truncate when text exceeds limit."""
        text = "This is a longer text that needs truncation"
        result = plugin._truncate(text, 20)
        assert result == "This is a longer ..."
        assert len(result) == 20

    def test_truncate_custom_suffix(self, plugin: ConcreteHTTPPlugin) -> None:
        """Test _truncate with custom suffix."""
        text = "This is a long text"
        result = plugin._truncate(text, 15, suffix="[more]")
        assert result == "This is a[more]"
        assert len(result) == 15
