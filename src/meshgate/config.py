"""Configuration loading from YAML files."""

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml


@dataclass
class ServerConfig:
    """Server configuration settings."""

    max_message_size: int = 200
    ack_timeout_seconds: float = 30.0
    session_timeout_minutes: int = 60


@dataclass
class MeshtasticConfig:
    """Meshtastic connection configuration."""

    connection_type: str = "serial"
    device: str | None = None
    tcp_host: str | None = None
    tcp_port: int = 4403


@dataclass
class GopherConfig:
    """Gopher plugin configuration."""

    root_directory: str = "./gopher_content"
    allow_escape: bool = False


@dataclass
class LLMConfig:
    """LLM plugin configuration."""

    ollama_url: str = "http://localhost:11434"
    model: str = "llama3.2"
    max_response_length: int = 400
    timeout: float = 30.0


@dataclass
class WeatherConfig:
    """Weather plugin configuration."""

    timeout: float = 10.0


@dataclass
class WikipediaConfig:
    """Wikipedia plugin configuration."""

    language: str = "en"
    max_summary_length: int = 400
    timeout: float = 10.0


@dataclass
class PluginsConfig:
    """Plugin-specific configurations."""

    gopher: GopherConfig = field(default_factory=GopherConfig)
    llm: LLMConfig = field(default_factory=LLMConfig)
    weather: WeatherConfig = field(default_factory=WeatherConfig)
    wikipedia: WikipediaConfig = field(default_factory=WikipediaConfig)


@dataclass
class Config:
    """Main configuration container."""

    server: ServerConfig = field(default_factory=ServerConfig)
    meshtastic: MeshtasticConfig = field(default_factory=MeshtasticConfig)
    plugins: PluginsConfig = field(default_factory=PluginsConfig)
    plugin_paths: list[str] = field(default_factory=lambda: ["./external_plugins"])

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Config":
        """Create Config from dictionary.

        Args:
            data: Configuration dictionary

        Returns:
            Config instance
        """
        server_data = data.get("server", {})
        server = ServerConfig(
            max_message_size=server_data.get("max_message_size", 200),
            ack_timeout_seconds=server_data.get("ack_timeout_seconds", 30.0),
            session_timeout_minutes=server_data.get("session_timeout_minutes", 60),
        )

        mesh_data = data.get("meshtastic", {})
        meshtastic = MeshtasticConfig(
            connection_type=mesh_data.get("connection_type", "serial"),
            device=mesh_data.get("device"),
            tcp_host=mesh_data.get("tcp_host"),
            tcp_port=mesh_data.get("tcp_port", 4403),
        )

        plugins_data = data.get("plugins", {})

        gopher_data = plugins_data.get("gopher", {})
        gopher = GopherConfig(
            root_directory=gopher_data.get("root_directory", "./gopher_content"),
            allow_escape=gopher_data.get("allow_escape", False),
        )

        llm_data = plugins_data.get("llm", {})
        llm = LLMConfig(
            ollama_url=llm_data.get("ollama_url", "http://localhost:11434"),
            model=llm_data.get("model", "llama3.2"),
            max_response_length=llm_data.get("max_response_length", 400),
            timeout=llm_data.get("timeout", 30.0),
        )

        weather_data = plugins_data.get("weather", {})
        weather = WeatherConfig(
            timeout=weather_data.get("timeout", 10.0),
        )

        wiki_data = plugins_data.get("wikipedia", {})
        wikipedia = WikipediaConfig(
            language=wiki_data.get("language", "en"),
            max_summary_length=wiki_data.get("max_summary_length", 400),
            timeout=wiki_data.get("timeout", 10.0),
        )

        plugins = PluginsConfig(
            gopher=gopher,
            llm=llm,
            weather=weather,
            wikipedia=wikipedia,
        )

        plugin_paths = data.get("plugin_paths", ["./external_plugins"])

        return cls(
            server=server,
            meshtastic=meshtastic,
            plugins=plugins,
            plugin_paths=plugin_paths,
        )

    @classmethod
    def from_yaml(cls, path: str | Path) -> "Config":
        """Load configuration from YAML file.

        Args:
            path: Path to YAML configuration file

        Returns:
            Config instance
        """
        path = Path(path)
        if not path.exists():
            raise FileNotFoundError(f"Configuration file not found: {path}")

        with open(path) as f:
            data = yaml.safe_load(f) or {}

        return cls.from_dict(data)

    @classmethod
    def default(cls) -> "Config":
        """Create default configuration.

        Returns:
            Config instance with default values
        """
        return cls()

    def to_dict(self) -> dict[str, Any]:
        """Convert configuration to dictionary.

        Returns:
            Configuration as dictionary
        """
        return {
            "server": {
                "max_message_size": self.server.max_message_size,
                "ack_timeout_seconds": self.server.ack_timeout_seconds,
                "session_timeout_minutes": self.server.session_timeout_minutes,
            },
            "meshtastic": {
                "connection_type": self.meshtastic.connection_type,
                "device": self.meshtastic.device,
                "tcp_host": self.meshtastic.tcp_host,
                "tcp_port": self.meshtastic.tcp_port,
            },
            "plugins": {
                "gopher": {
                    "root_directory": self.plugins.gopher.root_directory,
                    "allow_escape": self.plugins.gopher.allow_escape,
                },
                "llm": {
                    "ollama_url": self.plugins.llm.ollama_url,
                    "model": self.plugins.llm.model,
                    "max_response_length": self.plugins.llm.max_response_length,
                    "timeout": self.plugins.llm.timeout,
                },
                "weather": {
                    "timeout": self.plugins.weather.timeout,
                },
                "wikipedia": {
                    "language": self.plugins.wikipedia.language,
                    "max_summary_length": self.plugins.wikipedia.max_summary_length,
                    "timeout": self.plugins.wikipedia.timeout,
                },
            },
            "plugin_paths": self.plugin_paths,
        }

    def save_yaml(self, path: str | Path) -> None:
        """Save configuration to YAML file.

        Args:
            path: Path to save configuration
        """
        path = Path(path)
        with open(path, "w") as f:
            yaml.safe_dump(self.to_dict(), f, default_flow_style=False)
