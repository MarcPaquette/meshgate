"""Tests for configuration loading."""

import tempfile
from pathlib import Path

import pytest

from meshgate.config import Config


class TestConfig:
    """Tests for Config class."""

    def test_default_config(self) -> None:
        """Test creating default configuration."""
        config = Config.default()

        assert config.server.max_message_size == 200
        assert config.server.ack_timeout_seconds == 30.0
        assert config.meshtastic.connection_type == "serial"
        assert config.plugins.llm.model == "llama3.2"

    def test_from_dict(self) -> None:
        """Test creating config from dictionary."""
        data = {
            "server": {
                "max_message_size": 150,
            },
            "meshtastic": {
                "connection_type": "tcp",
                "tcp_host": "192.168.1.100",
            },
            "plugins": {
                "llm": {
                    "model": "mistral",
                },
            },
        }

        config = Config.from_dict(data)

        assert config.server.max_message_size == 150
        assert config.meshtastic.connection_type == "tcp"
        assert config.meshtastic.tcp_host == "192.168.1.100"
        assert config.plugins.llm.model == "mistral"

    def test_from_yaml(self) -> None:
        """Test loading config from YAML file."""
        yaml_content = """
server:
  max_message_size: 175
  ack_timeout_seconds: 45.0

meshtastic:
  connection_type: tcp
  tcp_host: 10.0.0.1
  tcp_port: 4403

plugins:
  llm:
    ollama_url: "http://localhost:11434"
    model: "phi3"
"""
        with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as f:
            f.write(yaml_content)
            f.flush()

            config = Config.from_yaml(f.name)

        assert config.server.max_message_size == 175
        assert config.server.ack_timeout_seconds == 45.0
        assert config.meshtastic.connection_type == "tcp"
        assert config.meshtastic.tcp_host == "10.0.0.1"
        assert config.plugins.llm.model == "phi3"

        # Cleanup
        Path(f.name).unlink()

    def test_from_yaml_not_found(self) -> None:
        """Test loading config from non-existent file."""
        with pytest.raises(FileNotFoundError):
            Config.from_yaml("/nonexistent/path.yaml")

    def test_to_dict(self) -> None:
        """Test converting config to dictionary."""
        config = Config.default()
        data = config.to_dict()

        assert "server" in data
        assert "meshtastic" in data
        assert "plugins" in data
        assert data["server"]["max_message_size"] == 200

    def test_save_yaml(self) -> None:
        """Test saving config to YAML file."""
        config = Config.default()
        config.server.max_message_size = 123

        with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as f:
            temp_path = f.name

        config.save_yaml(temp_path)

        # Load and verify
        loaded = Config.from_yaml(temp_path)
        assert loaded.server.max_message_size == 123

        # Cleanup
        Path(temp_path).unlink()

    def test_empty_yaml(self) -> None:
        """Test loading empty YAML uses defaults."""
        with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as f:
            f.write("")
            f.flush()

            config = Config.from_yaml(f.name)

        assert config.server.max_message_size == 200

        Path(f.name).unlink()

    def test_partial_yaml(self) -> None:
        """Test partial YAML uses defaults for missing fields."""
        yaml_content = """
plugins:
  weather:
    timeout: 5.0
"""
        with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as f:
            f.write(yaml_content)
            f.flush()

            config = Config.from_yaml(f.name)

        # Specified value
        assert config.plugins.weather.timeout == 5.0
        # Default values
        assert config.server.max_message_size == 200
        assert config.plugins.llm.model == "llama3.2"

        Path(f.name).unlink()


class TestSecurityConfig:
    """Tests for SecurityConfig parsing."""

    def test_default_security_config(self) -> None:
        """Test default security configuration."""
        config = Config.default()

        assert config.security.node_allowlist == []
        assert config.security.node_denylist == []
        assert config.security.require_allowlist is False
        assert config.security.rate_limit_enabled is False
        assert config.security.rate_limit_messages == 10
        assert config.security.rate_limit_window_seconds == 60

    def test_security_config_from_dict(self) -> None:
        """Test creating security config from dictionary."""
        data = {
            "security": {
                "node_allowlist": ["!node1", "!node2"],
                "node_denylist": ["!badnode"],
                "require_allowlist": True,
                "rate_limit_enabled": True,
                "rate_limit_messages": 5,
                "rate_limit_window_seconds": 30,
            }
        }

        config = Config.from_dict(data)

        assert config.security.node_allowlist == ["!node1", "!node2"]
        assert config.security.node_denylist == ["!badnode"]
        assert config.security.require_allowlist is True
        assert config.security.rate_limit_enabled is True
        assert config.security.rate_limit_messages == 5
        assert config.security.rate_limit_window_seconds == 30

    def test_security_config_to_dict(self) -> None:
        """Test converting security config to dictionary."""
        config = Config.default()
        config.security.node_allowlist = ["!test"]
        config.security.rate_limit_enabled = True

        data = config.to_dict()

        assert "security" in data
        assert data["security"]["node_allowlist"] == ["!test"]
        assert data["security"]["rate_limit_enabled"] is True

    def test_security_config_from_yaml(self) -> None:
        """Test loading security config from YAML."""
        yaml_content = """
security:
  node_allowlist:
    - "!allowed1"
    - "!allowed2"
  node_denylist:
    - "!denied"
  require_allowlist: true
  rate_limit_enabled: true
  rate_limit_messages: 20
  rate_limit_window_seconds: 120
"""
        with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as f:
            f.write(yaml_content)
            f.flush()

            config = Config.from_yaml(f.name)

        assert config.security.node_allowlist == ["!allowed1", "!allowed2"]
        assert config.security.node_denylist == ["!denied"]
        assert config.security.require_allowlist is True
        assert config.security.rate_limit_enabled is True
        assert config.security.rate_limit_messages == 20
        assert config.security.rate_limit_window_seconds == 120

        Path(f.name).unlink()

    def test_session_cleanup_config(self) -> None:
        """Test session cleanup configuration."""
        data = {
            "server": {
                "session_cleanup_interval_minutes": 10,
                "max_sessions": 500,
            }
        }

        config = Config.from_dict(data)

        assert config.server.session_cleanup_interval_minutes == 10
        assert config.server.max_sessions == 500
