"""Tests for configuration loading."""

import tempfile
from pathlib import Path

import pytest

from meshtastic_handler.config import Config


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
