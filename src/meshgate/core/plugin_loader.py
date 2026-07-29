"""Plugin discovery and loading utilities."""

import hashlib
import importlib
import importlib.util
import inspect
import logging
import sys
from pathlib import Path

from meshgate.interfaces.plugin import Plugin

logger = logging.getLogger(__name__)


class PluginLoadError(Exception):
    """Raised when a plugin fails to load."""


class PluginLoader:
    """Discovers and loads plugins dynamically.

    Supports loading plugins from:
    - Python module paths (e.g., "my_package.plugins.custom_plugin")
    - File paths (e.g., "/path/to/custom_plugin.py")
    - Directory scanning for plugin files

    Example usage:
        loader = PluginLoader()

        # Load from module path
        plugin = loader.load_plugin("my_plugins.weather")

        # Load from file
        plugin = loader.load_plugin_from_file("/path/to/plugin.py")

        # Discover all plugins in a directory
        plugins = loader.discover_plugins("/path/to/plugins/")
    """

    def load_plugin(self, module_path: str) -> Plugin:
        """Load a plugin from a Python module path.

        Args:
            module_path: Dotted module path (e.g., "my_package.plugins.weather")

        Returns:
            Instantiated Plugin object

        Raises:
            PluginLoadError: If plugin cannot be loaded
        """
        try:
            module = importlib.import_module(module_path)
            return self._find_and_instantiate_plugin(module, module_path)
        except ImportError as e:
            raise PluginLoadError(f"Failed to import module '{module_path}': {e}") from e
        except Exception as e:
            raise PluginLoadError(f"Failed to load plugin from '{module_path}': {e}") from e

    def load_plugin_from_file(self, file_path: str | Path) -> Plugin:
        """Load a plugin from a Python file.

        Args:
            file_path: Path to the Python file containing the plugin

        Returns:
            Instantiated Plugin object

        Raises:
            PluginLoadError: If plugin cannot be loaded
        """
        file_path = Path(file_path)
        if not file_path.exists():
            raise PluginLoadError(f"Plugin file not found: {file_path}")

        if not file_path.suffix == ".py":
            raise PluginLoadError(f"Plugin file must be a .py file: {file_path}")

        # Derive the module name from the full path so two plugin files with
        # the same stem in different directories don't collide.
        resolved = file_path.resolve()
        digest = hashlib.sha256(str(resolved).encode()).hexdigest()[:8]
        module_name = f"_plugin_{resolved.stem}_{digest}"

        try:
            spec = importlib.util.spec_from_file_location(module_name, resolved)
            if spec is None or spec.loader is None:
                raise PluginLoadError(f"Could not load spec for: {file_path}")

            module = importlib.util.module_from_spec(spec)
            # Register before executing: dataclasses and get_type_hints resolve
            # annotations by looking the module up in sys.modules.
            sys.modules[module_name] = module
            try:
                spec.loader.exec_module(module)
            except BaseException:
                sys.modules.pop(module_name, None)
                raise

            return self._find_and_instantiate_plugin(module, str(file_path))
        except PluginLoadError:
            raise
        except Exception as e:
            raise PluginLoadError(f"Failed to load plugin from '{file_path}': {e}") from e

    def discover_plugins(self, directory: str | Path) -> list[Plugin]:
        """Discover and load all plugins in a directory.

        Scans the directory for Python files that contain Plugin subclasses.
        Files starting with underscore are skipped.

        Args:
            directory: Path to directory containing plugin files

        Returns:
            List of instantiated Plugin objects
        """
        directory = Path(directory)
        if not directory.exists():
            logger.warning(f"Plugin directory does not exist: {directory}")
            return []

        if not directory.is_dir():
            raise PluginLoadError(f"Not a directory: {directory}")

        plugins: list[Plugin] = []
        for file_path in sorted(directory.glob("*.py")):
            # Skip private/internal files
            if file_path.name.startswith("_"):
                continue

            try:
                plugin = self.load_plugin_from_file(file_path)
                plugins.append(plugin)
                logger.info(f"Loaded plugin '{plugin.metadata.name}' from {file_path}")
            except PluginLoadError as e:
                logger.warning(f"Skipping {file_path}: {e}")

        return plugins

    def _find_and_instantiate_plugin(self, module: object, source: str) -> Plugin:
        """Find a Plugin subclass in a module and instantiate it.

        Args:
            module: The loaded Python module
            source: Source description for error messages

        Returns:
            Instantiated Plugin object

        Raises:
            PluginLoadError: If no valid plugin class is found
        """
        plugin_classes: list[type[Plugin]] = []

        for name in dir(module):
            obj = getattr(module, name)
            if (
                isinstance(obj, type)
                and issubclass(obj, Plugin)
                and obj is not Plugin
                and not inspect.isabstract(obj)
                # dir() also lists imported names, so a plugin that imports
                # another plugin would otherwise offer two candidates and be
                # resolved by guesswork.
                and obj.__module__ == module.__name__
            ):
                plugin_classes.append(obj)

        if not plugin_classes:
            raise PluginLoadError(f"No Plugin subclass found in '{source}'")

        if len(plugin_classes) > 1:
            plugin_class = plugin_classes[0]
            logger.warning(
                f"Multiple Plugin classes found in '{source}' "
                f"({', '.join(c.__name__ for c in plugin_classes)}), "
                f"using {plugin_class.__name__}"
            )
        else:
            plugin_class = plugin_classes[0]

        try:
            return plugin_class()
        except Exception as e:
            raise PluginLoadError(
                f"Failed to instantiate {plugin_class.__name__} from '{source}': {e}"
            ) from e
