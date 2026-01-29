"""Gopher plugin - Directory-based content navigation."""

from pathlib import Path
from typing import Any

from meshtastic_handler.interfaces.node_context import NodeContext
from meshtastic_handler.interfaces.plugin import Plugin, PluginMetadata, PluginResponse


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
            return PluginResponse(
                message=f"Invalid input. Send a number or command.\n\n{listing}",
                plugin_state={"current_path": str(current)},
            )

    def _handle_back(self, current: Path) -> PluginResponse:
        """Handle the !back command."""
        parent = current.parent
        if self._is_within_root(parent):
            listing = self._list_directory(parent)
            return PluginResponse(message=listing, plugin_state={"current_path": str(parent)})
        else:
            listing = self._list_directory(self._root)
            return PluginResponse(
                message=f"Already at root.\n\n{listing}",
                plugin_state={"current_path": str(self._root)},
            )

    def _handle_home(self) -> PluginResponse:
        """Handle the !home command."""
        listing = self._list_directory(self._root)
        return PluginResponse(message=listing, plugin_state={"current_path": str(self._root)})

    def _handle_selection(self, current: Path, selection: int) -> PluginResponse:
        """Handle numeric selection."""
        items = self._get_items(current)

        if selection < 1 or selection > len(items):
            listing = self._list_directory(current)
            return PluginResponse(
                message=f"Invalid selection. Choose 1-{len(items)}.\n\n{listing}",
                plugin_state={"current_path": str(current)},
            )

        selected = items[selection - 1]
        selected_path = current / selected

        if selected_path.is_dir():
            # Navigate into directory
            listing = self._list_directory(selected_path)
            return PluginResponse(
                message=listing, plugin_state={"current_path": str(selected_path)}
            )
        else:
            # Read file content
            content = self._read_file(selected_path)
            return PluginResponse(
                message=f"{selected}:\n{content}",
                plugin_state={"current_path": str(current)},
            )

    def _is_within_root(self, path: Path) -> bool:
        """Check if path is within root directory."""
        try:
            path.resolve().relative_to(self._root)
            return True
        except ValueError:
            return False

    def _get_items(self, directory: Path) -> list[str]:
        """Get sorted list of items in directory."""
        if not directory.is_dir():
            return []

        items = []
        try:
            for entry in sorted(directory.iterdir()):
                # Skip hidden files
                if entry.name.startswith("."):
                    continue
                items.append(entry.name)
        except PermissionError:
            pass
        return items

    def _list_directory(self, directory: Path) -> str:
        """Generate directory listing."""
        items = self._get_items(directory)

        if not items:
            rel_path = self._get_relative_path(directory)
            return f"[{rel_path}]\n(empty)"

        lines = [f"[{self._get_relative_path(directory)}]"]
        for i, item in enumerate(items, 1):
            item_path = directory / item
            suffix = "/" if item_path.is_dir() else ""
            lines.append(f"{i}. {item}{suffix}")

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
            content = file_path.read_text(encoding="utf-8", errors="replace")
            if len(content) > max_chars:
                content = content[:max_chars] + "...[truncated]"
            return content.strip()
        except Exception as e:
            return f"Error reading file: {e}"
