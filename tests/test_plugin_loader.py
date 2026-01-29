"""Tests for plugin loader."""

import tempfile
from pathlib import Path

import pytest

from meshgate.core.plugin_loader import PluginLoader, PluginLoadError


class TestPluginLoader:
    """Tests for PluginLoader class."""

    @pytest.fixture
    def loader(self) -> PluginLoader:
        """Create a PluginLoader."""
        return PluginLoader()

    def test_load_builtin_plugin(self, loader: PluginLoader) -> None:
        """Test loading a built-in plugin by module path."""
        plugin = loader.load_plugin("meshgate.plugins.weather_plugin")
        assert plugin.metadata.name == "Weather"

    def test_load_nonexistent_module(self, loader: PluginLoader) -> None:
        """Test loading nonexistent module raises error."""
        with pytest.raises(PluginLoadError, match="Failed to import"):
            loader.load_plugin("nonexistent.module.plugin")

    def test_load_plugin_from_file(self, loader: PluginLoader) -> None:
        """Test loading plugin from a Python file."""
        plugin_code = """
from typing import Any
from meshgate.interfaces.plugin import Plugin, PluginMetadata, PluginResponse
from meshgate.interfaces.node_context import NodeContext

class TestFilePlugin(Plugin):
    @property
    def metadata(self) -> PluginMetadata:
        return PluginMetadata(
            name="Test File Plugin",
            description="Loaded from file",
            menu_number=99,
        )

    def get_welcome_message(self) -> str:
        return "Welcome from file"

    def get_help_text(self) -> str:
        return "Help from file"

    async def handle(
        self, message: str, context: NodeContext, plugin_state: dict[str, Any]
    ) -> PluginResponse:
        return PluginResponse(message="Response from file")
"""
        with tempfile.NamedTemporaryFile(mode="w", suffix=".py", delete=False) as f:
            f.write(plugin_code)
            plugin_path = f.name

        try:
            plugin = loader.load_plugin_from_file(plugin_path)
            assert plugin.metadata.name == "Test File Plugin"
            assert plugin.get_welcome_message() == "Welcome from file"
        finally:
            Path(plugin_path).unlink()

    def test_load_from_nonexistent_file(self, loader: PluginLoader) -> None:
        """Test loading from nonexistent file raises error."""
        with pytest.raises(PluginLoadError, match="not found"):
            loader.load_plugin_from_file("/nonexistent/path/plugin.py")

    def test_load_from_non_python_file(self, loader: PluginLoader) -> None:
        """Test loading from non-.py file raises error."""
        with tempfile.NamedTemporaryFile(mode="w", suffix=".txt", delete=False) as f:
            f.write("not python")
            file_path = f.name

        try:
            with pytest.raises(PluginLoadError, match="must be a .py file"):
                loader.load_plugin_from_file(file_path)
        finally:
            Path(file_path).unlink()

    def test_load_file_without_plugin_class(self, loader: PluginLoader) -> None:
        """Test loading file without Plugin subclass raises error."""
        with tempfile.NamedTemporaryFile(mode="w", suffix=".py", delete=False) as f:
            f.write("class NotAPlugin:\n    pass\n")
            file_path = f.name

        try:
            with pytest.raises(PluginLoadError, match="No Plugin subclass"):
                loader.load_plugin_from_file(file_path)
        finally:
            Path(file_path).unlink()

    def test_discover_plugins_empty_directory(self, loader: PluginLoader) -> None:
        """Test discovering plugins in empty directory."""
        with tempfile.TemporaryDirectory() as tmpdir:
            plugins = loader.discover_plugins(tmpdir)
            assert plugins == []

    def test_discover_plugins_nonexistent_directory(self, loader: PluginLoader) -> None:
        """Test discovering plugins in nonexistent directory returns empty."""
        plugins = loader.discover_plugins("/nonexistent/directory")
        assert plugins == []

    def test_discover_plugins_skips_private_files(self, loader: PluginLoader) -> None:
        """Test that files starting with underscore are skipped."""
        plugin_code = """
from typing import Any
from meshgate.interfaces.plugin import Plugin, PluginMetadata, PluginResponse
from meshgate.interfaces.node_context import NodeContext

class PrivatePlugin(Plugin):
    @property
    def metadata(self) -> PluginMetadata:
        return PluginMetadata(name="Private", description="", menu_number=1)

    def get_welcome_message(self) -> str:
        return ""

    def get_help_text(self) -> str:
        return ""

    async def handle(
        self, message: str, context: NodeContext, plugin_state: dict[str, Any]
    ) -> PluginResponse:
        return PluginResponse(message="")
"""
        with tempfile.TemporaryDirectory() as tmpdir:
            # Create a private file that should be skipped
            private_file = Path(tmpdir) / "_private_plugin.py"
            private_file.write_text(plugin_code)

            plugins = loader.discover_plugins(tmpdir)
            assert plugins == []
