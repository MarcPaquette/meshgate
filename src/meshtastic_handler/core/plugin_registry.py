"""Plugin registry for plugin discovery and registration."""

from meshtastic_handler.interfaces.plugin import Plugin


class PluginRegistry:
    """Registry for plugin discovery and management.

    Plugins are registered with a unique name and can be looked up
    by name or menu number.
    """

    def __init__(self) -> None:
        """Initialize the plugin registry."""
        self._plugins: dict[str, Plugin] = {}
        self._menu_index: dict[int, str] = {}

    def register(self, plugin: Plugin) -> None:
        """Register a plugin.

        Args:
            plugin: The plugin instance to register

        Raises:
            ValueError: If plugin name or menu number is already registered
        """
        name = plugin.metadata.name
        menu_number = plugin.metadata.menu_number

        if name in self._plugins:
            raise ValueError(f"Plugin '{name}' is already registered")
        if menu_number in self._menu_index:
            existing = self._menu_index[menu_number]
            raise ValueError(f"Menu number {menu_number} is already used by '{existing}'")

        self._plugins[name] = plugin
        self._menu_index[menu_number] = name

    def unregister(self, name: str) -> bool:
        """Unregister a plugin by name.

        Args:
            name: The plugin name to unregister

        Returns:
            True if plugin was unregistered, False if it wasn't registered
        """
        if name not in self._plugins:
            return False

        plugin = self._plugins[name]
        del self._menu_index[plugin.metadata.menu_number]
        del self._plugins[name]
        return True

    def get_by_name(self, name: str) -> Plugin | None:
        """Get a plugin by its name.

        Args:
            name: The plugin name

        Returns:
            The plugin instance, or None if not found
        """
        return self._plugins.get(name)

    def get_by_menu_number(self, menu_number: int) -> Plugin | None:
        """Get a plugin by its menu number.

        Args:
            menu_number: The menu number (1, 2, 3, etc.)

        Returns:
            The plugin instance, or None if not found
        """
        name = self._menu_index.get(menu_number)
        if name is None:
            return None
        return self._plugins.get(name)

    def get_all_plugins(self) -> list[Plugin]:
        """Get all registered plugins, sorted by menu number.

        Returns:
            List of plugins sorted by menu number
        """
        return sorted(self._plugins.values(), key=lambda p: p.metadata.menu_number)

    def get_menu_numbers(self) -> list[int]:
        """Get all registered menu numbers, sorted.

        Returns:
            Sorted list of menu numbers
        """
        return sorted(self._menu_index.keys())

    @property
    def plugin_count(self) -> int:
        """Get the number of registered plugins."""
        return len(self._plugins)

    def __contains__(self, name: str) -> bool:
        """Check if a plugin is registered by name."""
        return name in self._plugins
