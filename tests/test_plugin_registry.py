"""Tests for plugin registry."""

import pytest

from meshtastic_handler.core.plugin_registry import PluginRegistry
from tests.mocks import MockPlugin


class TestPluginRegistry:
    """Tests for PluginRegistry class."""

    def test_register_plugin(self, plugin_registry: PluginRegistry) -> None:
        """Test registering a plugin."""
        plugin = MockPlugin(name="Test", menu_number=1)
        plugin_registry.register(plugin)

        assert plugin_registry.plugin_count == 1
        assert "Test" in plugin_registry

    def test_register_multiple_plugins(self, plugin_registry: PluginRegistry) -> None:
        """Test registering multiple plugins."""
        plugin1 = MockPlugin(name="Plugin 1", menu_number=1)
        plugin2 = MockPlugin(name="Plugin 2", menu_number=2)

        plugin_registry.register(plugin1)
        plugin_registry.register(plugin2)

        assert plugin_registry.plugin_count == 2

    def test_register_duplicate_name(self, plugin_registry: PluginRegistry) -> None:
        """Test that duplicate names raise error."""
        plugin1 = MockPlugin(name="Same Name", menu_number=1)
        plugin2 = MockPlugin(name="Same Name", menu_number=2)

        plugin_registry.register(plugin1)
        with pytest.raises(ValueError, match="already registered"):
            plugin_registry.register(plugin2)

    def test_register_duplicate_menu_number(self, plugin_registry: PluginRegistry) -> None:
        """Test that duplicate menu numbers raise error."""
        plugin1 = MockPlugin(name="Plugin 1", menu_number=1)
        plugin2 = MockPlugin(name="Plugin 2", menu_number=1)

        plugin_registry.register(plugin1)
        with pytest.raises(ValueError, match="Menu number 1 is already used"):
            plugin_registry.register(plugin2)

    def test_get_by_name(self, plugin_registry: PluginRegistry) -> None:
        """Test getting plugin by name."""
        plugin = MockPlugin(name="Test Plugin", menu_number=1)
        plugin_registry.register(plugin)

        result = plugin_registry.get_by_name("Test Plugin")
        assert result is plugin

    def test_get_by_name_not_found(self, plugin_registry: PluginRegistry) -> None:
        """Test getting non-existent plugin by name."""
        result = plugin_registry.get_by_name("Nonexistent")
        assert result is None

    def test_get_by_menu_number(self, plugin_registry: PluginRegistry) -> None:
        """Test getting plugin by menu number."""
        plugin = MockPlugin(name="Test Plugin", menu_number=5)
        plugin_registry.register(plugin)

        result = plugin_registry.get_by_menu_number(5)
        assert result is plugin

    def test_get_by_menu_number_not_found(self, plugin_registry: PluginRegistry) -> None:
        """Test getting non-existent plugin by menu number."""
        result = plugin_registry.get_by_menu_number(99)
        assert result is None

    def test_get_all_plugins_sorted(self, plugin_registry: PluginRegistry) -> None:
        """Test that get_all_plugins returns sorted by menu number."""
        plugin3 = MockPlugin(name="Plugin C", menu_number=3)
        plugin1 = MockPlugin(name="Plugin A", menu_number=1)
        plugin2 = MockPlugin(name="Plugin B", menu_number=2)

        plugin_registry.register(plugin3)
        plugin_registry.register(plugin1)
        plugin_registry.register(plugin2)

        plugins = plugin_registry.get_all_plugins()
        assert len(plugins) == 3
        assert plugins[0].metadata.menu_number == 1
        assert plugins[1].metadata.menu_number == 2
        assert plugins[2].metadata.menu_number == 3

    def test_get_menu_numbers(self, plugin_registry: PluginRegistry) -> None:
        """Test getting sorted list of menu numbers."""
        plugin_registry.register(MockPlugin(name="P3", menu_number=3))
        plugin_registry.register(MockPlugin(name="P1", menu_number=1))

        numbers = plugin_registry.get_menu_numbers()
        assert numbers == [1, 3]

    def test_unregister(self, plugin_registry: PluginRegistry) -> None:
        """Test unregistering a plugin."""
        plugin = MockPlugin(name="Test", menu_number=1)
        plugin_registry.register(plugin)

        result = plugin_registry.unregister("Test")
        assert result is True
        assert plugin_registry.plugin_count == 0
        assert "Test" not in plugin_registry

    def test_unregister_not_found(self, plugin_registry: PluginRegistry) -> None:
        """Test unregistering non-existent plugin."""
        result = plugin_registry.unregister("Nonexistent")
        assert result is False

    def test_contains(self, plugin_registry: PluginRegistry) -> None:
        """Test __contains__ method."""
        plugin = MockPlugin(name="Test", menu_number=1)
        plugin_registry.register(plugin)

        assert "Test" in plugin_registry
        assert "Other" not in plugin_registry
