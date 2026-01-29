"""Tests for CLI argument parsing and config loading."""

import tempfile
from pathlib import Path

import pytest

from meshgate.cli import load_config, parse_args
from meshgate.config import Config


class TestParseArgs:
    """Tests for argument parsing."""

    def test_default_args(self) -> None:
        """Test parsing with no arguments."""
        args = parse_args([])

        assert args.config is None
        assert args.verbose is False
        assert args.connection is None
        assert args.device is None
        assert args.tcp_host is None
        assert args.tcp_port is None

    def test_config_path(self) -> None:
        """Test config file path argument."""
        args = parse_args(["-c", "/path/to/config.yaml"])
        assert args.config == "/path/to/config.yaml"

        args = parse_args(["--config", "/other/path.yaml"])
        assert args.config == "/other/path.yaml"

    def test_verbose_flag(self) -> None:
        """Test verbose flag."""
        args = parse_args(["-v"])
        assert args.verbose is True

        args = parse_args(["--verbose"])
        assert args.verbose is True

    def test_connection_type(self) -> None:
        """Test connection type argument."""
        args = parse_args(["--connection", "serial"])
        assert args.connection == "serial"

        args = parse_args(["--connection", "tcp"])
        assert args.connection == "tcp"

        args = parse_args(["--connection", "ble"])
        assert args.connection == "ble"

    def test_invalid_connection_type(self) -> None:
        """Test invalid connection type raises error."""
        with pytest.raises(SystemExit):
            parse_args(["--connection", "invalid"])

    def test_device_path(self) -> None:
        """Test device path argument."""
        args = parse_args(["--device", "/dev/ttyUSB0"])
        assert args.device == "/dev/ttyUSB0"

    def test_tcp_host(self) -> None:
        """Test TCP host argument."""
        args = parse_args(["--tcp-host", "192.168.1.100"])
        assert args.tcp_host == "192.168.1.100"

    def test_tcp_port(self) -> None:
        """Test TCP port argument."""
        args = parse_args(["--tcp-port", "4403"])
        assert args.tcp_port == 4403

    def test_multiple_args(self) -> None:
        """Test multiple arguments together."""
        args = parse_args(
            [
                "-c",
                "config.yaml",
                "-v",
                "--connection",
                "tcp",
                "--tcp-host",
                "192.168.1.1",
                "--tcp-port",
                "5000",
            ]
        )

        assert args.config == "config.yaml"
        assert args.verbose is True
        assert args.connection == "tcp"
        assert args.tcp_host == "192.168.1.1"
        assert args.tcp_port == 5000


class TestLoadConfig:
    """Tests for configuration loading."""

    def test_load_default_config_when_no_file(self) -> None:
        """Test loading default config when no file specified."""
        args = parse_args([])
        # This assumes no default config files exist in test environment
        config = load_config(args)

        assert isinstance(config, Config)

    def test_load_config_from_file(self) -> None:
        """Test loading config from YAML file."""
        with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as f:
            f.write("""
server:
  max_message_size: 100
  session_timeout_minutes: 120
meshtastic:
  connection_type: tcp
  tcp_host: 192.168.1.50
""")
            config_path = f.name

        try:
            args = parse_args(["-c", config_path])
            config = load_config(args)

            assert config.server.max_message_size == 100
            assert config.server.session_timeout_minutes == 120
            assert config.meshtastic.connection_type == "tcp"
            assert config.meshtastic.tcp_host == "192.168.1.50"
        finally:
            Path(config_path).unlink()

    def test_config_file_not_found_exits(self) -> None:
        """Test that missing config file exits with error."""
        args = parse_args(["-c", "/nonexistent/config.yaml"])

        with pytest.raises(SystemExit) as exc_info:
            load_config(args)
        assert exc_info.value.code == 1

    def test_cli_overrides_connection(self) -> None:
        """Test CLI overrides config connection type."""
        with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as f:
            f.write("""
meshtastic:
  connection_type: serial
""")
            config_path = f.name

        try:
            args = parse_args(["-c", config_path, "--connection", "tcp"])
            config = load_config(args)

            # CLI should override file config
            assert config.meshtastic.connection_type == "tcp"
        finally:
            Path(config_path).unlink()

    def test_cli_overrides_device(self) -> None:
        """Test CLI overrides config device."""
        with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as f:
            f.write("""
meshtastic:
  device: /dev/ttyACM0
""")
            config_path = f.name

        try:
            args = parse_args(["-c", config_path, "--device", "/dev/ttyUSB1"])
            config = load_config(args)

            assert config.meshtastic.device == "/dev/ttyUSB1"
        finally:
            Path(config_path).unlink()

    def test_cli_overrides_tcp_host(self) -> None:
        """Test CLI overrides TCP host."""
        args = parse_args(["--tcp-host", "10.0.0.1"])
        config = load_config(args)

        assert config.meshtastic.tcp_host == "10.0.0.1"

    def test_cli_overrides_tcp_port(self) -> None:
        """Test CLI overrides TCP port."""
        args = parse_args(["--tcp-port", "9999"])
        config = load_config(args)

        assert config.meshtastic.tcp_port == 9999

    def test_all_overrides_together(self) -> None:
        """Test all CLI overrides applied together."""
        args = parse_args(
            [
                "--connection",
                "tcp",
                "--device",
                "/dev/custom",
                "--tcp-host",
                "host.local",
                "--tcp-port",
                "1234",
            ]
        )
        config = load_config(args)

        assert config.meshtastic.connection_type == "tcp"
        assert config.meshtastic.device == "/dev/custom"
        assert config.meshtastic.tcp_host == "host.local"
        assert config.meshtastic.tcp_port == 1234
