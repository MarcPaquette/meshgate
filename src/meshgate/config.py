"""Configuration loading from YAML files."""

import logging
import os
import tempfile
from dataclasses import asdict, dataclass, field, fields
from pathlib import Path
from typing import Any, TypeVar

import yaml

logger = logging.getLogger(__name__)

T = TypeVar("T")


def _dataclass_from_dict(cls: type[T], data: dict[str, Any] | None) -> T:
    """Create a dataclass instance from a dictionary, ignoring unknown keys.

    A YAML section with no body parses as None rather than an empty mapping,
    so None is treated the same as {} (all defaults).
    """
    if not data:
        return cls()

    valid = {f.name for f in fields(cls)}
    unknown = set(data) - valid
    if unknown:
        # A typo in a security setting would otherwise be silently ignored,
        # leaving the operator believing a protection is enabled.
        logger.warning("Ignoring unknown %s keys: %s", cls.__name__, ", ".join(sorted(unknown)))
    return cls(**{k: v for k, v in data.items() if k in valid})


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

    enabled: bool = True
    root_directory: str = "./gopher_content"
    allow_escape: bool = False


@dataclass
class LLMConfig:
    """LLM plugin configuration."""

    enabled: bool = True
    ollama_url: str = "http://localhost:11434"
    model: str = "llama3.2"
    max_response_length: int = 400
    timeout: float = 30.0


@dataclass
class WeatherConfig:
    """Weather plugin configuration."""

    enabled: bool = True
    timeout: float = 10.0


@dataclass
class WikipediaConfig:
    """Wikipedia plugin configuration."""

    enabled: bool = True
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

    # Plugin state limits
    max_plugin_state_bytes: int = 10240  # 10 KB default (0 = unlimited)


@dataclass
class WebConfig:
    """Web dashboard configuration.

    Disabled by default. Note that enabling transcripts records the message
    content of every node that talks to the gateway (in memory only).
    """

    enabled: bool = False
    host: str = "127.0.0.1"
    port: int = 8080
    transcript_enabled: bool = False
    transcript_max_messages: int = 50
    transcript_max_nodes: int = 200
    log_buffer_size: int = 1000


@dataclass
class Config:
    """Main configuration container."""

    server: ServerConfig = field(default_factory=ServerConfig)
    meshtastic: MeshtasticConfig = field(default_factory=MeshtasticConfig)
    plugins: PluginsConfig = field(default_factory=PluginsConfig)
    security: SecurityConfig = field(default_factory=SecurityConfig)
    web: WebConfig = field(default_factory=WebConfig)
    plugin_paths: list[str] = field(default_factory=list)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Config":
        """Create Config from dictionary.

        Args:
            data: Configuration dictionary

        Returns:
            Config instance
        """
        # `or {}` rather than a .get() default: a valueless YAML section
        # ("server:") is present but parses as None, so the default never fires.
        data = data or {}
        plugins_data = data.get("plugins") or {}
        plugins = PluginsConfig(
            gopher=_dataclass_from_dict(GopherConfig, plugins_data.get("gopher")),
            llm=_dataclass_from_dict(LLMConfig, plugins_data.get("llm")),
            weather=_dataclass_from_dict(WeatherConfig, plugins_data.get("weather")),
            wikipedia=_dataclass_from_dict(WikipediaConfig, plugins_data.get("wikipedia")),
        )

        config = cls(
            server=_dataclass_from_dict(ServerConfig, data.get("server")),
            meshtastic=_dataclass_from_dict(MeshtasticConfig, data.get("meshtastic")),
            plugins=plugins,
            security=_dataclass_from_dict(SecurityConfig, data.get("security")),
            web=_dataclass_from_dict(WebConfig, data.get("web")),
            plugin_paths=data.get("plugin_paths") or [],
        )
        config.validate()
        return config

    def validate(self) -> None:
        """Check values that would otherwise fail deep inside runtime code.

        Raises:
            ValueError: If any setting is out of range or unrecognized
        """
        errors = []

        valid_connections = {"serial", "tcp", "ble"}
        if self.meshtastic.connection_type not in valid_connections:
            errors.append(
                f"meshtastic.connection_type must be one of "
                f"{sorted(valid_connections)}, got {self.meshtastic.connection_type!r}"
            )
        if not 1 <= self.meshtastic.tcp_port <= 65535:
            errors.append(f"meshtastic.tcp_port must be 1-65535, got {self.meshtastic.tcp_port}")

        if self.server.max_message_size < 20:
            errors.append(
                f"server.max_message_size must be at least 20, got {self.server.max_message_size}"
            )
        if self.server.session_timeout_minutes <= 0:
            errors.append(
                f"server.session_timeout_minutes must be positive, "
                f"got {self.server.session_timeout_minutes}"
            )
        if self.server.session_cleanup_interval_minutes <= 0:
            errors.append(
                f"server.session_cleanup_interval_minutes must be positive, "
                f"got {self.server.session_cleanup_interval_minutes}"
            )

        # A window of 0 would make every check reject permanently.
        if self.security.rate_limit_messages <= 0:
            errors.append(
                f"security.rate_limit_messages must be positive, "
                f"got {self.security.rate_limit_messages}"
            )
        if self.security.rate_limit_window_seconds <= 0:
            errors.append(
                f"security.rate_limit_window_seconds must be positive, "
                f"got {self.security.rate_limit_window_seconds}"
            )

        if not 1 <= self.web.port <= 65535:
            errors.append(f"web.port must be 1-65535, got {self.web.port}")
        if self.web.transcript_max_messages <= 0:
            errors.append(
                f"web.transcript_max_messages must be positive, "
                f"got {self.web.transcript_max_messages}"
            )
        if self.web.transcript_max_nodes <= 0:
            errors.append(
                f"web.transcript_max_nodes must be positive, got {self.web.transcript_max_nodes}"
            )
        if self.web.log_buffer_size <= 0:
            errors.append(f"web.log_buffer_size must be positive, got {self.web.log_buffer_size}")

        if errors:
            raise ValueError("Invalid configuration:\n  - " + "\n  - ".join(errors))

        if self.security.require_allowlist and not self.security.node_allowlist:
            logger.warning(
                "security.require_allowlist is set with an empty node_allowlist - "
                "all traffic will be rejected"
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
        return asdict(self)

    def save_yaml(self, path: str | Path) -> None:
        """Save configuration to YAML file.

        Args:
            path: Path to save configuration
        """
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)

        # Write to a temp file in the same directory, then rename, so a crash
        # mid-write can't truncate an existing config.
        fd, tmp_path = tempfile.mkstemp(dir=path.parent, suffix=".tmp")
        try:
            with os.fdopen(fd, "w") as f:
                yaml.safe_dump(self.to_dict(), f, default_flow_style=False)
            os.replace(tmp_path, path)
        except BaseException:
            Path(tmp_path).unlink(missing_ok=True)
            raise
