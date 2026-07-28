"""Gopher plugin - Directory-based content navigation."""

import logging
import os
from pathlib import Path
from typing import Any

from meshgate.interfaces.node_context import NodeContext
from meshgate.interfaces.plugin import Plugin, PluginMetadata, PluginResponse

logger = logging.getLogger(__name__)


class GopherPlugin(Plugin):
    """Directory-based content navigation plugin.

    Allows users to browse a filesystem directory structure and read text files.
    Uses numbered navigation for easy selection on Meshtastic devices.

    Commands:
        !back - Go to parent directory
        !home - Return to root directory
        !help - Show help
        !exit - Return to main menu
    """

    # Maximum characters to read from a file before truncating
    MAX_FILE_CHARS = 500

    def __init__(self, root_directory: str = "./gopher_content") -> None:
        """Initialize the Gopher plugin.

        Args:
            root_directory: Root directory for content (default: ./gopher_content)
        """
        self._root = Path(root_directory).resolve()
        # Create root if it doesn't exist
        self._root.mkdir(parents=True, exist_ok=True)

    @property
    def metadata(self) -> PluginMetadata:
        """Return plugin metadata."""
        return PluginMetadata(
            name="Gopher Server",
            description="Browse files and directories",
            menu_number=1,
            commands=("!back", "!home", "!help", "!exit"),
        )

    def get_welcome_message(self) -> str:
        """Message shown when user enters this plugin."""
        listing = self._list_directory(self._root)
        return f"Gopher Server\n{listing}\nSend number to select, !help for commands"

    def get_help_text(self) -> str:
        """Help text showing plugin-specific commands."""
        return (
            "Gopher Commands:\n"
            "[number] - Select item\n"
            "!back - Parent directory\n"
            "!home - Root directory\n"
            "!help - Show this help\n"
            "!exit - Return to menu"
        )

    async def handle(
        self, message: str, context: NodeContext, plugin_state: dict[str, Any]
    ) -> PluginResponse:
        """Handle a message while user is in this plugin."""
        message = message.strip().lower()

        # Get current path from state, default to root
        current_path = plugin_state.get("current_path", str(self._root))
        current = Path(current_path)

        # Ensure current path is valid and within root
        if not current.exists() or not self._is_within_root(current):
            current = self._root
            current_path = str(self._root)

        # Handle commands
        if message == "!back":
            return self._handle_back(current)
        elif message == "!home":
            return self._handle_home()

        # Handle number selection
        try:
            selection = int(message)
            return self._handle_selection(current, selection)
        except ValueError:
            listing = self._list_directory(current)
            return self._path_response(
                f"Invalid input. Send a number or command.\n\n{listing}", current
            )

    def _handle_back(self, current: Path) -> PluginResponse:
        """Handle the !back command."""
        parent = current.parent
        if self._is_within_root(parent):
            return self._path_response(self._list_directory(parent), parent)
        listing = self._list_directory(self._root)
        return self._path_response(f"Already at root.\n\n{listing}", self._root)

    def _handle_home(self) -> PluginResponse:
        """Handle the !home command."""
        return self._path_response(self._list_directory(self._root), self._root)

    def _handle_selection(self, current: Path, selection: int) -> PluginResponse:
        """Handle numeric selection."""
        items = self._get_items(current)

        if selection < 1 or selection > len(items):
            # Reuse the entries already read rather than scanning again.
            listing = self._render_listing(current, items)
            return self._path_response(
                f"Invalid selection. Choose 1-{len(items)}.\n\n{listing}", current
            )

        selected, is_dir = items[selection - 1]
        selected_path = current / selected

        # Entries are listed straight from the directory, so a symlink pointing
        # outside the root would otherwise be served before the containment
        # check on the following request ever ran.
        if not self._is_within_root(selected_path):
            logger.warning("Blocked access outside gopher root: %s", selected_path)
            return self._path_response(
                f"Access denied.\n\n{self._render_listing(current, items)}", current
            )

        if is_dir:
            # Navigate into directory
            return self._path_response(self._list_directory(selected_path), selected_path)
        # Read file content
        content = self._read_file(selected_path)
        return self._path_response(f"{selected}:\n{content}", current)

    def _path_response(self, message: str, path: Path) -> PluginResponse:
        """Create a response that preserves the current path in state."""
        return PluginResponse(message=message, plugin_state={"current_path": str(path)})

    def _is_within_root(self, path: Path) -> bool:
        """Check if path is within root directory."""
        try:
            path.resolve().relative_to(self._root)
            return True
        except ValueError:
            return False

    def _get_items(self, directory: Path) -> list[tuple[str, bool]]:
        """Get sorted directory entries as (name, is_dir) pairs.

        Uses os.scandir so the directory type comes from the dirent that the
        scan already returned, rather than a separate stat() per entry.
        """
        if not directory.is_dir():
            return []

        items = []
        try:
            with os.scandir(directory) as entries:
                for entry in entries:
                    # Skip hidden files
                    if entry.name.startswith("."):
                        continue
                    try:
                        is_dir = entry.is_dir()
                    except OSError:
                        is_dir = False
                    items.append((entry.name, is_dir))
        except (PermissionError, OSError):
            pass
        return sorted(items)

    def _list_directory(self, directory: Path) -> str:
        """Generate directory listing."""
        return self._render_listing(directory, self._get_items(directory))

    def _render_listing(self, directory: Path, items: list[tuple[str, bool]]) -> str:
        """Render a listing from entries already read, avoiding a re-scan."""
        if not items:
            rel_path = self._get_relative_path(directory)
            return f"[{rel_path}]\n(empty)"

        lines = [f"[{self._get_relative_path(directory)}]"]
        for i, (name, is_dir) in enumerate(items, 1):
            suffix = "/" if is_dir else ""
            lines.append(f"{i}. {name}{suffix}")

        return "\n".join(lines)

    def _get_relative_path(self, path: Path) -> str:
        """Get path relative to root, or '/' for root."""
        try:
            rel = path.resolve().relative_to(self._root)
            return f"/{rel}" if str(rel) != "." else "/"
        except ValueError:
            return "/"

    def _read_file(self, file_path: Path, max_chars: int | None = None) -> str:
        """Read file content, truncated to max_chars."""
        if max_chars is None:
            max_chars = self.MAX_FILE_CHARS
        try:
            # Read only what is needed, plus one character to detect overflow.
            # read_text() would pull an arbitrarily large file fully into
            # memory just to discard all but the first few hundred characters.
            with open(file_path, encoding="utf-8", errors="replace") as f:
                content = f.read(max_chars + 1)
            if len(content) > max_chars:
                content = content[:max_chars] + "...[truncated]"
            return content.strip()
        except Exception as e:
            logger.warning("Error reading %s: %s", file_path, e)
            return "Error reading file."
