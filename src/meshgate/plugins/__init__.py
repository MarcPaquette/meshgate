"""Plugins module - Built-in plugin implementations."""

from meshgate.plugins.gopher_plugin import GopherPlugin
from meshgate.plugins.llm_plugin import LLMPlugin
from meshgate.plugins.weather_plugin import WeatherPlugin
from meshgate.plugins.wikipedia_plugin import WikipediaPlugin

__all__ = [
    "GopherPlugin",
    "LLMPlugin",
    "WeatherPlugin",
    "WikipediaPlugin",
]
