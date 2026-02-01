"""Configuration loading from YAML files."""

from dataclasses import dataclass, field, fields
from pathlib import Path
from typing import Any, TypeVar

import yaml

T = TypeVar("T")


def _dataclass_from_dict(cls: type[T], data: dict[str, Any]) -> T:
    """Create a dataclass instance from a dictionary.

    Uses dataclass field introspection to automatically map dict keys to fields,
    using field defaults when keys are missing.

    Args:
        cls: The dataclass type to instantiate
        data: Dictionary with field values

    Returns:
        Instance of the dataclass with values from dict (or defaults)
    """
    kwargs = {}
    for f in fields(cls):
        if f.name in data:
            kwargs[f.name] = data[f.name]
        # If not in data, dataclass will use its own default
    return cls(**kwargs)


def _dataclass_to_dict(obj: Any) -> dict[str, Any]:
    """Convert a dataclass instance to a dictionary.

    Recursively handles nested dataclasses.

    Args:
        obj: Dataclass instance to convert

    Returns:
        Dictionary representation of the dataclass
    """
    result = {}
    for f in fields(obj):
        value = getattr(obj, f.name)
        # Check if value is itself a dataclass (has __dataclass_fields__)
        if hasattr(value, "__dataclass_fields__"):
            result[f.name] = _dataclass_to_dict(value)
        elif isinstance(value, list):
            # Handle lists (e.g., plugin_paths, allowlist)
            result[f.name] = value.copy() if value else []
        else:
            result[f.name] = value
    return result


@dataclass
class ServerConfig:
    """Server configuration settings."""

    max_message_size: int = 200
    ack_timeout_seconds: float = 30.0
    session_timeout_minutes: int = 60
    session_cleanup_interval_minutes: int = 5  # How often to run cleanup
    max_sessions: int = 0  # Max concurrent sessions (0 = unlimited)


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
class SecurityConfig:
    """Security configuration settings."""

    # Node filtering
    node_allowlist: list[str] = field(default_factory=list)  # Empty = allow all
    node_denylist: list[str] = field(default_factory=list)
    require_allowlist: bool = False  # If True, only allowlisted nodes can connect

    # Rate limiting
    rate_limit_enabled: bool = False
    rate_limit_messages: int = 10  # Max messages per window
    rate_limit_window_seconds: int = 60


@dataclass
class Config:
    """Main configuration container."""

    server: ServerConfig = field(default_factory=ServerConfig)
    meshtastic: MeshtasticConfig = field(default_factory=MeshtasticConfig)
    plugins: PluginsConfig = field(default_factory=PluginsConfig)
    security: SecurityConfig = field(default_factory=SecurityConfig)
    plugin_paths: list[str] = field(default_factory=lambda: ["./external_plugins"])

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Config":
        """Create Config from dictionary.

        Args:
            data: Configuration dictionary

        Returns:
            Config instance
        """
        # Build nested plugin configs
        plugins_data = data.get("plugins", {})
        plugins = PluginsConfig(
            gopher=_dataclass_from_dict(GopherConfig, plugins_data.get("gopher", {})),
            llm=_dataclass_from_dict(LLMConfig, plugins_data.get("llm", {})),
            weather=_dataclass_from_dict(WeatherConfig, plugins_data.get("weather", {})),
            wikipedia=_dataclass_from_dict(WikipediaConfig, plugins_data.get("wikipedia", {})),
        )

        return cls(
            server=_dataclass_from_dict(ServerConfig, data.get("server", {})),
            meshtastic=_dataclass_from_dict(MeshtasticConfig, data.get("meshtastic", {})),
            plugins=plugins,
            security=_dataclass_from_dict(SecurityConfig, data.get("security", {})),
            plugin_paths=data.get("plugin_paths", ["./external_plugins"]),
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
        return _dataclass_to_dict(self)

    def save_yaml(self, path: str | Path) -> None:
        """Save configuration to YAML file.

        Args:
            path: Path to save configuration
        """
        path = Path(path)
        with open(path, "w") as f:
            yaml.safe_dump(self.to_dict(), f, default_flow_style=False)
