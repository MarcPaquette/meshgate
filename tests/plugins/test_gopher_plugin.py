"""Tests for Gopher plugin."""

import tempfile
from pathlib import Path

import pytest

from meshgate.interfaces.node_context import NodeContext
from meshgate.plugins.gopher_plugin import GopherPlugin


class TestGopherPlugin:
    """Tests for GopherPlugin class."""

    @pytest.fixture
    def temp_gopher_dir(self) -> Path:
        """Create a temporary directory with test content."""
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)

            # Create test structure
            (root / "folder1").mkdir()
            (root / "folder2").mkdir()
            (root / "file1.txt").write_text("Content of file 1")
            (root / "file2.txt").write_text("Content of file 2")
            (root / "folder1" / "nested.txt").write_text("Nested content")

            yield root

    @pytest.fixture
    def plugin(self, temp_gopher_dir: Path) -> GopherPlugin:
        """Create a GopherPlugin with temp directory."""
        return GopherPlugin(root_directory=str(temp_gopher_dir))

    def test_welcome_message(self, plugin: GopherPlugin) -> None:
        """Test welcome message shows directory listing."""
        welcome = plugin.get_welcome_message()
        assert "Gopher Server" in welcome
        assert "folder1/" in welcome or "folder2/" in welcome

    def test_help_text(self, plugin: GopherPlugin) -> None:
        """Test help text includes commands."""
        help_text = plugin.get_help_text()
        assert "!back" in help_text
        assert "!home" in help_text
        assert "!exit" in help_text

    @pytest.mark.asyncio
    async def test_list_root_directory(self, plugin: GopherPlugin, context: NodeContext) -> None:
        """Test listing root directory."""
        response = await plugin.handle("!home", context, {})

        assert "[/]" in response.message
        # Should have numbered items
        assert "1." in response.message or "2." in response.message

    @pytest.mark.asyncio
    async def test_select_folder(
        self, plugin: GopherPlugin, context: NodeContext, temp_gopher_dir: Path
    ) -> None:
        """Test selecting a folder navigates into it."""
        # Get initial listing to find folder position
        response = await plugin.handle("!home", context, {})

        # Find the number for folder1
        lines = response.message.split("\n")
        folder_num = None
        for line in lines:
            if "folder1/" in line:
                folder_num = line.split(".")[0].strip()
                break

        if folder_num:
            response = await plugin.handle(
                folder_num, context, {"current_path": str(temp_gopher_dir)}
            )
            assert "/folder1" in response.message or "nested.txt" in response.message

    @pytest.mark.asyncio
    async def test_select_file(
        self, plugin: GopherPlugin, context: NodeContext, temp_gopher_dir: Path
    ) -> None:
        """Test selecting a file shows content."""
        # First get listing
        response = await plugin.handle("!home", context, {})

        # Find a text file
        lines = response.message.split("\n")
        file_num = None
        for line in lines:
            if "file1.txt" in line:
                file_num = line.split(".")[0].strip()
                break

        if file_num:
            response = await plugin.handle(
                file_num, context, {"current_path": str(temp_gopher_dir)}
            )
            assert "Content of file 1" in response.message

    @pytest.mark.asyncio
    async def test_back_command(
        self, plugin: GopherPlugin, context: NodeContext, temp_gopher_dir: Path
    ) -> None:
        """Test !back navigates to parent directory."""
        subfolder = temp_gopher_dir / "folder1"
        response = await plugin.handle("!back", context, {"current_path": str(subfolder)})

        assert "[/]" in response.message

    @pytest.mark.asyncio
    async def test_back_at_root(
        self, plugin: GopherPlugin, context: NodeContext, temp_gopher_dir: Path
    ) -> None:
        """Test !back at root stays at root."""
        response = await plugin.handle("!back", context, {"current_path": str(temp_gopher_dir)})

        assert "Already at root" in response.message

    @pytest.mark.asyncio
    async def test_home_command(
        self, plugin: GopherPlugin, context: NodeContext, temp_gopher_dir: Path
    ) -> None:
        """Test !home returns to root."""
        subfolder = temp_gopher_dir / "folder1"
        response = await plugin.handle("!home", context, {"current_path": str(subfolder)})

        assert "[/]" in response.message

    @pytest.mark.asyncio
    async def test_invalid_selection(
        self, plugin: GopherPlugin, context: NodeContext, temp_gopher_dir: Path
    ) -> None:
        """Test invalid number selection."""
        response = await plugin.handle("99", context, {"current_path": str(temp_gopher_dir)})

        assert "Invalid selection" in response.message

    @pytest.mark.asyncio
    async def test_non_number_input(
        self, plugin: GopherPlugin, context: NodeContext, temp_gopher_dir: Path
    ) -> None:
        """Test non-number input."""
        response = await plugin.handle(
            "notanumber", context, {"current_path": str(temp_gopher_dir)}
        )

        assert "Invalid input" in response.message

    @pytest.mark.asyncio
    async def test_empty_directory(self, plugin: GopherPlugin, context: NodeContext) -> None:
        """Test listing empty directory."""
        with tempfile.TemporaryDirectory() as tmpdir:
            empty_plugin = GopherPlugin(root_directory=tmpdir)
            response = await empty_plugin.handle("!home", context, {})

            assert "(empty)" in response.message
