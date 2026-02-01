"""Tests for Weather plugin."""

import pytest
import respx
from httpx import Response

from meshgate.interfaces.node_context import GPSLocation, NodeContext
from meshgate.plugins.weather_plugin import WeatherPlugin


class TestWeatherPlugin:
    """Tests for WeatherPlugin class."""

    @pytest.fixture
    def plugin(self) -> WeatherPlugin:
        """Create a WeatherPlugin."""
        return WeatherPlugin(timeout=5.0)

    @pytest.fixture
    def context_with_gps(self) -> NodeContext:
        """Create test NodeContext with GPS."""
        return NodeContext(
            node_id="!test123",
            location=GPSLocation(latitude=40.7128, longitude=-74.0060),
        )

    def test_welcome_message(self, plugin: WeatherPlugin) -> None:
        """Test welcome message."""
        welcome = plugin.get_welcome_message()
        assert "Weather" in welcome

    def test_help_text(self, plugin: WeatherPlugin) -> None:
        """Test help text includes commands."""
        help_text = plugin.get_help_text()
        assert "!forecast" in help_text
        assert "!refresh" in help_text
        assert "!exit" in help_text

    @pytest.mark.asyncio
    async def test_no_gps_error(self, plugin: WeatherPlugin, context: NodeContext) -> None:
        """Test error when no GPS location available."""
        response = await plugin.handle("!refresh", context, {})

        assert "GPS" in response.message or "location" in response.message.lower()

    @pytest.mark.asyncio
    @respx.mock
    async def test_current_weather(
        self, plugin: WeatherPlugin, context_with_gps: NodeContext
    ) -> None:
        """Test fetching current weather."""
        respx.get("https://api.open-meteo.com/v1/forecast").mock(
            return_value=Response(
                200,
                json={
                    "current": {
                        "temperature_2m": 22.5,
                        "relative_humidity_2m": 65,
                        "weather_code": 1,
                        "wind_speed_10m": 15.0,
                        "wind_direction_10m": 180,
                    }
                },
            )
        )

        response = await plugin.handle("!refresh", context_with_gps, {})

        # Verify response contains data from mock
        assert response.message  # Non-empty
        assert "22.5" in response.message  # Temperature from mock
        assert "65" in response.message  # Humidity from mock

    @pytest.mark.asyncio
    @respx.mock
    async def test_forecast(self, plugin: WeatherPlugin, context_with_gps: NodeContext) -> None:
        """Test fetching forecast."""
        respx.get("https://api.open-meteo.com/v1/forecast").mock(
            return_value=Response(
                200,
                json={
                    "daily": {
                        "time": ["2024-01-15", "2024-01-16", "2024-01-17"],
                        "weather_code": [0, 3, 61],
                        "temperature_2m_max": [25.0, 23.0, 20.0],
                        "temperature_2m_min": [15.0, 14.0, 12.0],
                    }
                },
            )
        )

        response = await plugin.handle("!forecast", context_with_gps, {})

        # Verify response structure and data from mock
        assert response.message  # Non-empty
        assert "25" in response.message  # Max temp from mock

    def test_degrees_to_cardinal(self, plugin: WeatherPlugin) -> None:
        """Test wind direction conversion."""
        assert plugin._degrees_to_cardinal(0) == "N"
        assert plugin._degrees_to_cardinal(45) == "NE"
        assert plugin._degrees_to_cardinal(90) == "E"
        assert plugin._degrees_to_cardinal(180) == "S"
        assert plugin._degrees_to_cardinal(270) == "W"
        assert plugin._degrees_to_cardinal(360) == "N"

    @pytest.mark.asyncio
    @respx.mock
    async def test_empty_message_refreshes(
        self, plugin: WeatherPlugin, context_with_gps: NodeContext
    ) -> None:
        """Test that empty message acts as refresh."""
        respx.get("https://api.open-meteo.com/v1/forecast").mock(
            return_value=Response(
                200,
                json={
                    "current": {
                        "temperature_2m": 20.0,
                        "relative_humidity_2m": 50,
                        "weather_code": 0,
                        "wind_speed_10m": 10.0,
                        "wind_direction_10m": 0,
                    }
                },
            )
        )

        response = await plugin.handle("", context_with_gps, {})

        assert "Current Weather" in response.message

    @pytest.mark.asyncio
    @respx.mock
    async def test_malformed_json_response(
        self, plugin: WeatherPlugin, context_with_gps: NodeContext
    ) -> None:
        """Test handling of malformed JSON response."""
        respx.get("https://api.open-meteo.com/v1/forecast").mock(
            return_value=Response(
                200,
                json={"unexpected": "format"},
            )
        )

        response = await plugin.handle("!refresh", context_with_gps, {})

        # Should handle gracefully
        assert response.message  # Non-empty response
