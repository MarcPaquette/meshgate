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

    def test_timeout_attribute(self, plugin: ConcreteHTTPPlugin) -> None:
        """Test timeout attribute."""
        assert plugin.timeout == 5.0

    def test_default_timeout(self) -> None:
        """Test default timeout value."""
        plugin = ConcreteHTTPPlugin()
        assert plugin.timeout == 5.0

    def test_service_name_attribute(self, plugin: ConcreteHTTPPlugin) -> None:
        """Test service_name attribute."""
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

    @pytest.mark.asyncio
    @respx.mock
    async def test_request_json_get(self, plugin: ConcreteHTTPPlugin) -> None:
        """Test _request_json with GET method."""
        respx.get("https://example.com/api").mock(return_value=Response(200, json={"ok": True}))

        result = await plugin._request_json("get", "https://example.com/api")

        assert isinstance(result, dict)
        assert result["ok"] is True

    @pytest.mark.asyncio
    @respx.mock
    async def test_request_json_post(self, plugin: ConcreteHTTPPlugin) -> None:
        """Test _request_json with POST method."""
        respx.post("https://example.com/api").mock(return_value=Response(200, json={"ok": True}))

        result = await plugin._request_json("post", "https://example.com/api", json={"data": 1})

        assert isinstance(result, dict)
        assert result["ok"] is True

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
