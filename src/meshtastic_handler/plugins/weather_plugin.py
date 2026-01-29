"""Weather plugin - GPS-based weather using Open-Meteo API."""

import logging
from typing import Any

from meshtastic_handler.interfaces.node_context import NodeContext
from meshtastic_handler.interfaces.plugin import PluginMetadata, PluginResponse
from meshtastic_handler.plugins.base import HTTPPluginBase

logger = logging.getLogger(__name__)


# WMO Weather interpretation codes
WMO_CODES = {
    0: "Clear",
    1: "Mainly clear",
    2: "Partly cloudy",
    3: "Overcast",
    45: "Foggy",
    48: "Depositing rime fog",
    51: "Light drizzle",
    53: "Moderate drizzle",
    55: "Dense drizzle",
    56: "Light freezing drizzle",
    57: "Dense freezing drizzle",
    61: "Slight rain",
    63: "Moderate rain",
    65: "Heavy rain",
    66: "Light freezing rain",
    67: "Heavy freezing rain",
    71: "Slight snow",
    73: "Moderate snow",
    75: "Heavy snow",
    77: "Snow grains",
    80: "Slight rain showers",
    81: "Moderate rain showers",
    82: "Violent rain showers",
    85: "Slight snow showers",
    86: "Heavy snow showers",
    95: "Thunderstorm",
    96: "Thunderstorm with slight hail",
    99: "Thunderstorm with heavy hail",
}


class WeatherPlugin(HTTPPluginBase):
    """Weather plugin using Open-Meteo API.

    Uses the node's GPS location to fetch current weather conditions.
    No API key required (Open-Meteo is free and open).

    Commands:
        !forecast - Show 3-day forecast
        !refresh - Update current weather
        !help - Show help
        !exit - Return to main menu
    """

    OPEN_METEO_URL = "https://api.open-meteo.com/v1/forecast"

    def __init__(self, timeout: float = 10.0) -> None:
        """Initialize the Weather plugin.

        Args:
            timeout: Request timeout in seconds
        """
        super().__init__(timeout=timeout, service_name="weather service")

    @property
    def metadata(self) -> PluginMetadata:
        """Return plugin metadata."""
        return PluginMetadata(
            name="Weather",
            description="GPS-based weather",
            menu_number=3,
            commands=("!forecast", "!refresh", "!help", "!exit"),
        )

    def get_welcome_message(self) -> str:
        """Message shown when user enters this plugin."""
        return (
            "Weather Service\n"
            "Getting current weather...\n"
            "Send !help for commands"
        )

    def get_help_text(self) -> str:
        """Help text showing plugin-specific commands."""
        return (
            "Weather Commands:\n"
            "!refresh - Current weather\n"
            "!forecast - 3-day forecast\n"
            "!help - Show this help\n"
            "!exit - Return to menu"
        )

    async def handle(
        self, message: str, context: NodeContext, plugin_state: dict[str, Any]
    ) -> PluginResponse:
        """Handle a message while user is in this plugin."""
        message = message.strip().lower()

        # Check for GPS location
        if not context.location:
            return PluginResponse(
                message="No GPS location available. Enable GPS on your device.",
                plugin_state=plugin_state,
            )

        lat = context.location.latitude
        lon = context.location.longitude

        # Handle commands
        if message == "!refresh" or message == "":
            return await self._handle_current_weather(lat, lon)

        if message == "!forecast":
            return await self._handle_forecast(lat, lon)

        # Treat any other message as a refresh request
        return await self._handle_current_weather(lat, lon)

    async def _handle_current_weather(
        self, lat: float, lon: float
    ) -> PluginResponse:
        """Fetch and display current weather."""
        result = await self._fetch_json(
            self.OPEN_METEO_URL,
            params={
                "latitude": lat,
                "longitude": lon,
                "current": [
                    "temperature_2m",
                    "relative_humidity_2m",
                    "weather_code",
                    "wind_speed_10m",
                    "wind_direction_10m",
                ],
                "temperature_unit": "celsius",
                "wind_speed_unit": "kmh",
            },
        )

        if isinstance(result, PluginResponse):
            return result

        current = result.get("current", {})
        temp = current.get("temperature_2m", "?")
        humidity = current.get("relative_humidity_2m", "?")
        weather_code = current.get("weather_code", 0)
        wind_speed = current.get("wind_speed_10m", "?")
        wind_dir = current.get("wind_direction_10m", 0)

        condition = WMO_CODES.get(weather_code, "Unknown")
        wind_cardinal = self._degrees_to_cardinal(wind_dir)

        weather_text = (
            f"Current Weather:\n"
            f"{condition}\n"
            f"Temp: {temp}C\n"
            f"Humidity: {humidity}%\n"
            f"Wind: {wind_speed}km/h {wind_cardinal}"
        )

        return PluginResponse(
            message=weather_text,
            plugin_state={"last_lat": lat, "last_lon": lon},
        )

    async def _handle_forecast(self, lat: float, lon: float) -> PluginResponse:
        """Fetch and display 3-day forecast."""
        result = await self._fetch_json(
            self.OPEN_METEO_URL,
            params={
                "latitude": lat,
                "longitude": lon,
                "daily": [
                    "weather_code",
                    "temperature_2m_max",
                    "temperature_2m_min",
                ],
                "temperature_unit": "celsius",
                "forecast_days": 3,
            },
        )

        if isinstance(result, PluginResponse):
            return result

        daily = result.get("daily", {})
        dates = daily.get("time", [])
        codes = daily.get("weather_code", [])
        highs = daily.get("temperature_2m_max", [])
        lows = daily.get("temperature_2m_min", [])

        lines = ["3-Day Forecast:"]
        for i, date in enumerate(dates[:3]):
            # Format date as Mon, Tue, etc.
            from datetime import datetime

            try:
                dt = datetime.fromisoformat(date)
                day_name = dt.strftime("%a")
            except Exception:
                day_name = date

            condition = WMO_CODES.get(codes[i] if i < len(codes) else 0, "?")
            high = highs[i] if i < len(highs) else "?"
            low = lows[i] if i < len(lows) else "?"

            lines.append(f"{day_name}: {condition} {low}-{high}C")

        return PluginResponse(
            message="\n".join(lines),
            plugin_state={"last_lat": lat, "last_lon": lon},
        )

    def _degrees_to_cardinal(self, degrees: float) -> str:
        """Convert degrees to cardinal direction."""
        directions = ["N", "NE", "E", "SE", "S", "SW", "W", "NW"]
        index = round(degrees / 45) % 8
        return directions[index]
