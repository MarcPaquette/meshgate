"""Plugin registry for plugin discovery and registration."""

from meshgate.interfaces.plugin import Plugin


class PluginRegistry:
    """Registry for plugin discovery and management.

    Plugins are registered with a unique name and can be looked up
    by name or menu number.
    """

    def __init__(self) -> None:
        """Initialize the plugin registry."""
        self._plugins: dict[str, Plugin] = {}
        self._menu_index: dict[int, str] = {}
        # Menu number recorded at registration time. plugin.metadata rebuilds a
        # dataclass on every access, so re-reading it during unregister could
        # desynchronize the two indexes if it ever changed.
        self._name_to_menu: dict[str, int] = {}
        # Plugins that have been disabled at runtime. The instance is kept so
        # re-enabling does not reconstruct it - construction can have side
        # effects (GopherPlugin creates its root directory).
        self._disabled: dict[str, Plugin] = {}
        self._sorted_cache: list[Plugin] | None = None
        # Bumped on every change so dependents can cache derived values.
        self._version = 0

    def register(self, plugin: Plugin) -> None:
        """Register a plugin.

        Args:
            plugin: The plugin instance to register

        Raises:
            ValueError: If plugin name or menu number is already registered
        """
        name = plugin.metadata.name
        menu_number = plugin.metadata.menu_number

        if name in self._plugins or name in self._disabled:
            raise ValueError(f"Plugin '{name}' is already registered")
        if menu_number in self._menu_index:
            existing = self._menu_index[menu_number]
            raise ValueError(f"Menu number {menu_number} is already used by '{existing}'")

        self._plugins[name] = plugin
        self._menu_index[menu_number] = name
        self._name_to_menu[name] = menu_number
        self._invalidate()

    def unregister(self, name: str) -> bool:
        """Unregister a plugin by name, whether it is enabled or disabled.

        Args:
            name: The plugin name to unregister

        Returns:
            True if plugin was unregistered, False if it wasn't registered
        """
        if name not in self._plugins and name not in self._disabled:
            return False

        self._plugins.pop(name, None)
        self._disabled.pop(name, None)
        menu_number = self._name_to_menu.pop(name, None)
        if menu_number is not None:
            self._menu_index.pop(menu_number, None)
        self._invalidate()
        return True

    def disable(self, name: str) -> bool:
        """Disable a registered plugin without discarding it.

        The plugin stops appearing in the menu and stops being routable, but
        its menu number stays reserved so nothing else can claim it and
        re-enabling cannot collide.

        Args:
            name: The plugin name to disable

        Returns:
            True if the plugin was disabled, False if it wasn't enabled
        """
        plugin = self._plugins.pop(name, None)
        if plugin is None:
            return False

        self._disabled[name] = plugin
        self._invalidate()
        return True

    def enable(self, name: str) -> bool:
        """Re-enable a previously disabled plugin.

        Args:
            name: The plugin name to enable

        Returns:
            True if the plugin was enabled, False if it wasn't disabled
        """
        plugin = self._disabled.pop(name, None)
        if plugin is None:
            return False

        self._plugins[name] = plugin
        self._invalidate()
        return True

    def is_disabled(self, name: str) -> bool:
        """Check whether a plugin is registered but disabled."""
        return name in self._disabled

    def list_all(self) -> list[tuple[Plugin, bool]]:
        """Get every known plugin with its enabled state.

        Returns:
            List of (plugin, enabled) sorted by menu number
        """
        combined = [(p, True) for p in self._plugins.values()]
        combined += [(p, False) for p in self._disabled.values()]
        return sorted(combined, key=lambda pair: self._name_to_menu[pair[0].metadata.name])

    def _invalidate(self) -> None:
        """Drop cached derived state after a change."""
        self._sorted_cache = None
        self._version += 1

    @property
    def version(self) -> int:
        """A counter that changes whenever the set of plugins changes."""
        return self._version

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
        # Cached: the sort key reads plugin.metadata, which builds and
        # validates a fresh dataclass on every access, and this runs on the
        # per-message path via the menu.
        if self._sorted_cache is None:
            self._sorted_cache = sorted(
                self._plugins.values(), key=lambda p: self._name_to_menu[p.metadata.name]
            )
        return list(self._sorted_cache)

    @property
    def plugin_count(self) -> int:
        """Get the number of enabled plugins."""
        return len(self._plugins)

    @property
    def disabled_count(self) -> int:
        """Get the number of registered but disabled plugins."""
        return len(self._disabled)

    def __contains__(self, name: str) -> bool:
        """Check if a plugin is registered and enabled by name."""
        return name in self._plugins
