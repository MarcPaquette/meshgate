"""Tests for plugin interface and metadata."""

import pytest

from meshgate.interfaces.node_context import GPSLocation, NodeContext
from meshgate.interfaces.plugin import PluginMetadata, PluginResponse
from meshgate.plugins.gopher_plugin import GopherPlugin
from meshgate.plugins.llm_plugin import LLMPlugin
from meshgate.plugins.weather_plugin import WeatherPlugin
from meshgate.plugins.wikipedia_plugin import WikipediaPlugin


class TestGPSLocation:
    """Tests for GPSLocation dataclass."""

    def test_valid_location(self) -> None:
        """Test creating valid GPS location."""
        loc = GPSLocation(latitude=40.7128, longitude=-74.0060, altitude=10.0)
        assert loc.latitude == 40.7128
        assert loc.longitude == -74.0060
        assert loc.altitude == 10.0

    def test_location_without_altitude(self) -> None:
        """Test creating location without altitude."""
        loc = GPSLocation(latitude=0.0, longitude=0.0)
        assert loc.altitude is None

    def test_invalid_latitude_high(self) -> None:
        """Test that latitude > 90 raises error."""
        with pytest.raises(ValueError, match="Latitude must be between"):
            GPSLocation(latitude=91.0, longitude=0.0)

    def test_invalid_latitude_low(self) -> None:
        """Test that latitude < -90 raises error."""
        with pytest.raises(ValueError, match="Latitude must be between"):
            GPSLocation(latitude=-91.0, longitude=0.0)

    def test_invalid_longitude_high(self) -> None:
        """Test that longitude > 180 raises error."""
        with pytest.raises(ValueError, match="Longitude must be between"):
            GPSLocation(latitude=0.0, longitude=181.0)

    def test_invalid_longitude_low(self) -> None:
        """Test that longitude < -180 raises error."""
        with pytest.raises(ValueError, match="Longitude must be between"):
            GPSLocation(latitude=0.0, longitude=-181.0)

    def test_boundary_values(self) -> None:
        """Test boundary values are valid."""
        loc = GPSLocation(latitude=90.0, longitude=180.0)
        assert loc.latitude == 90.0
        assert loc.longitude == 180.0

        loc2 = GPSLocation(latitude=-90.0, longitude=-180.0)
        assert loc2.latitude == -90.0
        assert loc2.longitude == -180.0


class TestNodeContext:
    """Tests for NodeContext dataclass."""

    def test_minimal_context(self) -> None:
        """Test creating context with just node_id."""
        ctx = NodeContext(node_id="!abc123")
        assert ctx.node_id == "!abc123"
        assert ctx.node_name is None
        assert ctx.location is None

    def test_full_context(self) -> None:
        """Test creating context with all fields."""
        loc = GPSLocation(latitude=40.0, longitude=-74.0)
        ctx = NodeContext(node_id="!abc123", node_name="Test Node", location=loc)
        assert ctx.node_id == "!abc123"
        assert ctx.node_name == "Test Node"
        assert ctx.location == loc

    def test_empty_node_id(self) -> None:
        """Test that empty node_id raises error."""
        with pytest.raises(ValueError, match="node_id cannot be empty"):
            NodeContext(node_id="")


class TestPluginMetadata:
    """Tests for PluginMetadata dataclass."""

    def test_minimal_metadata(self) -> None:
        """Test creating metadata with required fields."""
        meta = PluginMetadata(
            name="Test Plugin",
            description="A test plugin",
            menu_number=1,
        )
        assert meta.name == "Test Plugin"
        assert meta.description == "A test plugin"
        assert meta.menu_number == 1
        assert meta.commands == ()

    def test_metadata_with_commands(self) -> None:
        """Test creating metadata with commands."""
        meta = PluginMetadata(
            name="Test Plugin",
            description="A test plugin",
            menu_number=1,
            commands=("!cmd1", "!cmd2"),
        )
        assert meta.commands == ("!cmd1", "!cmd2")

    def test_empty_name(self) -> None:
        """Test that empty name raises error."""
        with pytest.raises(ValueError, match="Plugin name cannot be empty"):
            PluginMetadata(name="", description="test", menu_number=1)

    def test_invalid_menu_number(self) -> None:
        """Test that menu_number < 1 raises error."""
        with pytest.raises(ValueError, match="Menu number must be >= 1"):
            PluginMetadata(name="Test", description="test", menu_number=0)


class TestPluginResponse:
    """Tests for PluginResponse dataclass."""

    def test_minimal_response(self) -> None:
        """Test creating response with just message."""
        resp = PluginResponse(message="Hello")
        assert resp.message == "Hello"
        assert resp.plugin_state is None
        assert resp.exit_plugin is False

    def test_response_with_state(self) -> None:
        """Test creating response with state."""
        resp = PluginResponse(
            message="Hello",
            plugin_state={"key": "value"},
        )
        assert resp.plugin_state == {"key": "value"}

    def test_response_with_exit(self) -> None:
        """Test creating response with exit flag."""
        resp = PluginResponse(
            message="Goodbye",
            exit_plugin=True,
        )
        assert resp.exit_plugin is True


class TestBuiltinPluginMetadata:
    """Parametrized tests for all built-in plugin metadata."""

    @pytest.mark.parametrize(
        "plugin_class,expected_name,expected_menu,expected_commands",
        [
            (GopherPlugin, "Gopher Server", 1, ("!back", "!home")),
            (LLMPlugin, "LLM Assistant", 2, ("!model", "!clear")),
            (WeatherPlugin, "Weather", 3, ("!forecast", "!refresh")),
            (WikipediaPlugin, "Wikipedia", 4, ("!search", "!random")),
        ],
    )
    def test_builtin_plugin_metadata(
        self,
        plugin_class: type,
        expected_name: str,
        expected_menu: int,
        expected_commands: tuple[str, ...],
    ) -> None:
        """Test that built-in plugins have correct metadata."""
        plugin = plugin_class()
        meta = plugin.metadata

        assert meta.name == expected_name
        assert meta.menu_number == expected_menu
        for cmd in expected_commands:
            assert cmd in meta.commands, f"Expected command {cmd} not found"

    @pytest.mark.parametrize(
        "plugin_class",
        [GopherPlugin, LLMPlugin, WeatherPlugin, WikipediaPlugin],
    )
    def test_builtin_plugin_has_welcome_message(self, plugin_class: type) -> None:
        """Test that all built-in plugins have non-empty welcome messages."""
        plugin = plugin_class()
        assert plugin.get_welcome_message()

    @pytest.mark.parametrize(
        "plugin_class",
        [GopherPlugin, LLMPlugin, WeatherPlugin, WikipediaPlugin],
    )
    def test_builtin_plugin_has_help_text(self, plugin_class: type) -> None:
        """Test that all built-in plugins have non-empty help text."""
        plugin = plugin_class()
        help_text = plugin.get_help_text()
        assert help_text
        assert "!exit" in help_text  # All plugins should mention exit command
