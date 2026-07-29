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

    @pytest.mark.asyncio
    @respx.mock
    async def test_wind_direction_in_response(
        self, plugin: WeatherPlugin, context_with_gps: NodeContext
    ) -> None:
        """Test wind direction is shown as cardinal direction in response."""
        respx.get("https://api.open-meteo.com/v1/forecast").mock(
            return_value=Response(
                200,
                json={
                    "current": {
                        "temperature_2m": 20.0,
                        "relative_humidity_2m": 50,
                        "weather_code": 0,
                        "wind_speed_10m": 10.0,
                        "wind_direction_10m": 180,
                    }
                },
            )
        )

        response = await plugin.handle("!refresh", context_with_gps, {})

        # Wind from 180° → cardinal "S"
        assert "S" in response.message

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

        assert "20" in response.message  # Temperature from mock

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

        assert response.message


class TestNullFieldHandling:
    """Open-Meteo returns null for some fields at some stations."""

    @pytest.fixture
    def plugin(self) -> WeatherPlugin:
        return WeatherPlugin(timeout=5.0)

    @pytest.fixture
    def context_with_gps(self) -> NodeContext:
        return NodeContext(
            node_id="!test123",
            location=GPSLocation(latitude=40.7128, longitude=-74.0060),
        )

    @respx.mock
    @pytest.mark.asyncio
    async def test_null_wind_direction_does_not_crash(
        self, plugin: WeatherPlugin, context_with_gps: NodeContext
    ) -> None:
        """Regression: null wind direction raised TypeError in round()."""
        respx.get("https://api.open-meteo.com/v1/forecast").mock(
            return_value=Response(
                200,
                json={
                    "current": {
                        "temperature_2m": 12.0,
                        "relative_humidity_2m": 60,
                        "weather_code": 0,
                        "wind_speed_10m": 5.0,
                        "wind_direction_10m": None,
                    }
                },
            )
        )

        response = await plugin.handle("!refresh", context_with_gps, {})

        assert "12.0" in response.message
        assert "Error" not in response.message

    @respx.mock
    @pytest.mark.asyncio
    async def test_valid_wind_direction_still_rendered(
        self, plugin: WeatherPlugin, context_with_gps: NodeContext
    ) -> None:
        respx.get("https://api.open-meteo.com/v1/forecast").mock(
            return_value=Response(
                200,
                json={
                    "current": {
                        "temperature_2m": 12.0,
                        "relative_humidity_2m": 60,
                        "weather_code": 0,
                        "wind_speed_10m": 5.0,
                        "wind_direction_10m": 90,
                    }
                },
            )
        )

        response = await plugin.handle("!refresh", context_with_gps, {})

        assert "E" in response.message
