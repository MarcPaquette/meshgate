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

        assert "folder1/" in response.message or "file1.txt" in response.message

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

        assert folder_num is not None, "folder1/ not found in menu listing"
        response = await plugin.handle(folder_num, context, {"current_path": str(temp_gopher_dir)})
        assert "/folder1" in response.message
        assert "nested.txt" in response.message

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

        assert file_num is not None, "file1.txt not found in menu listing"
        response = await plugin.handle(file_num, context, {"current_path": str(temp_gopher_dir)})
        assert "Content of file 1" in response.message

    @pytest.mark.asyncio
    async def test_back_command(
        self, plugin: GopherPlugin, context: NodeContext, temp_gopher_dir: Path
    ) -> None:
        """Test !back navigates to parent directory."""
        subfolder = temp_gopher_dir / "folder1"
        response = await plugin.handle("!back", context, {"current_path": str(subfolder)})

        assert "folder1/" in response.message or "file1.txt" in response.message

    @pytest.mark.asyncio
    async def test_back_at_root(
        self, plugin: GopherPlugin, context: NodeContext, temp_gopher_dir: Path
    ) -> None:
        """Test !back at root stays at root."""
        response = await plugin.handle("!back", context, {"current_path": str(temp_gopher_dir)})

        current = response.plugin_state.get("current_path", str(temp_gopher_dir))
        assert current == str(temp_gopher_dir)

    @pytest.mark.asyncio
    async def test_home_command(
        self, plugin: GopherPlugin, context: NodeContext, temp_gopher_dir: Path
    ) -> None:
        """Test !home returns to root."""
        subfolder = temp_gopher_dir / "folder1"
        response = await plugin.handle("!home", context, {"current_path": str(subfolder)})

        assert "folder1/" in response.message or "file1.txt" in response.message

    @pytest.mark.asyncio
    async def test_invalid_selection(
        self, plugin: GopherPlugin, context: NodeContext, temp_gopher_dir: Path
    ) -> None:
        """Test invalid number selection."""
        response = await plugin.handle("99", context, {"current_path": str(temp_gopher_dir)})

        assert "Invalid" in response.message

    @pytest.mark.asyncio
    async def test_non_number_input(
        self, plugin: GopherPlugin, context: NodeContext, temp_gopher_dir: Path
    ) -> None:
        """Test non-number input."""
        response = await plugin.handle(
            "notanumber", context, {"current_path": str(temp_gopher_dir)}
        )

        assert "Invalid" in response.message

    @pytest.mark.asyncio
    async def test_empty_directory(self, plugin: GopherPlugin, context: NodeContext) -> None:
        """Test listing empty directory."""
        with tempfile.TemporaryDirectory() as tmpdir:
            empty_plugin = GopherPlugin(root_directory=tmpdir)
            response = await empty_plugin.handle("!home", context, {})

            assert "(empty)" in response.message


class TestRootContainment:
    """Selections are indexes into the directory listing, which includes
    symlinks, so containment must be checked before serving them."""

    @pytest.fixture
    def rooted(self, tmp_path):
        """A gopher root containing a symlink that escapes it."""
        root = tmp_path / "content"
        root.mkdir()
        (root / "inside.txt").write_text("safe content")

        outside = tmp_path / "outside"
        outside.mkdir()
        (outside / "secret.txt").write_text("SECRET")

        (root / "escape.txt").symlink_to(outside / "secret.txt")
        (root / "escape_dir").symlink_to(outside)

        return GopherPlugin(root_directory=str(root))

    @pytest.mark.asyncio
    async def test_symlinked_file_is_not_read(
        self, rooted: GopherPlugin, context: NodeContext
    ) -> None:
        """Regression: the escaping file was served before the check ran."""
        listing = await rooted.handle("!home", context, {})
        items = [line.split(". ", 1)[1] for line in listing.message.splitlines() if ". " in line]
        index = items.index("escape.txt") + 1

        response = await rooted.handle(str(index), context, listing.plugin_state)

        assert "SECRET" not in response.message
        assert "Access denied" in response.message

    @pytest.mark.asyncio
    async def test_symlinked_directory_is_not_entered(
        self, rooted: GopherPlugin, context: NodeContext
    ) -> None:
        listing = await rooted.handle("!home", context, {})
        items = [
            line.split(". ", 1)[1].rstrip("/")
            for line in listing.message.splitlines()
            if ". " in line
        ]
        index = items.index("escape_dir") + 1

        response = await rooted.handle(str(index), context, listing.plugin_state)

        assert "secret.txt" not in response.message
        assert "Access denied" in response.message

    @pytest.mark.asyncio
    async def test_normal_file_still_readable(
        self, rooted: GopherPlugin, context: NodeContext
    ) -> None:
        """The containment check must not block legitimate content."""
        listing = await rooted.handle("!home", context, {})
        items = [line.split(". ", 1)[1] for line in listing.message.splitlines() if ". " in line]
        index = items.index("inside.txt") + 1

        response = await rooted.handle(str(index), context, listing.plugin_state)

        assert "safe content" in response.message


class TestBoundedFileRead:
    """Files are read up to the limit, not loaded whole and then trimmed."""

    @pytest.mark.asyncio
    async def test_large_file_is_truncated(self, context: NodeContext, tmp_path) -> None:
        root = tmp_path / "content"
        root.mkdir()
        (root / "big.txt").write_text("A" * 100_000)
        plugin = GopherPlugin(root_directory=str(root))

        listing = await plugin.handle("!home", context, {})
        response = await plugin.handle("1", context, listing.plugin_state)

        assert "[truncated]" in response.message
        assert len(response.message) < 1000

    def test_read_stops_at_the_limit(self, tmp_path) -> None:
        """Only max_chars+1 characters should be pulled off disk."""
        path = tmp_path / "big.txt"
        path.write_text("B" * 50_000)
        plugin = GopherPlugin(root_directory=str(tmp_path))

        content = plugin._read_file(path, max_chars=100)

        assert content.startswith("B" * 100)
        assert "[truncated]" in content
        assert len(content) < 150
