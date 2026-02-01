"""Tests for Wikipedia plugin."""

import pytest
import respx
from httpx import Response

from meshgate.interfaces.node_context import NodeContext
from meshgate.plugins.wikipedia_plugin import WikipediaPlugin


class TestWikipediaPlugin:
    """Tests for WikipediaPlugin class."""

    @pytest.fixture
    def plugin(self) -> WikipediaPlugin:
        """Create a WikipediaPlugin."""
        return WikipediaPlugin(
            language="en",
            max_summary_length=400,
            timeout=5.0,
        )

    def test_welcome_message(self, plugin: WikipediaPlugin) -> None:
        """Test welcome message."""
        welcome = plugin.get_welcome_message()
        assert "Wikipedia" in welcome

    def test_help_text(self, plugin: WikipediaPlugin) -> None:
        """Test help text includes commands."""
        help_text = plugin.get_help_text()
        assert "!search" in help_text
        assert "!random" in help_text
        assert "!exit" in help_text

    @pytest.mark.asyncio
    @respx.mock
    async def test_search_multiple_results(
        self, plugin: WikipediaPlugin, context: NodeContext
    ) -> None:
        """Test search with multiple results."""
        respx.get("https://en.wikipedia.org/w/api.php").mock(
            return_value=Response(
                200,
                json=[
                    "python",
                    ["Python (programming language)", "Python (snake)", "Monty Python"],
                    [],
                    [],
                ],
            )
        )

        response = await plugin.handle("python", context, {})

        assert "Results" in response.message
        assert "Python (programming language)" in response.message
        assert "1." in response.message
        assert response.plugin_state["last_results"] is not None

    @pytest.mark.asyncio
    @respx.mock
    async def test_search_single_result(
        self, plugin: WikipediaPlugin, context: NodeContext
    ) -> None:
        """Test search with single result goes directly to summary."""
        respx.get("https://en.wikipedia.org/w/api.php").mock(
            return_value=Response(
                200,
                json=["specific term", ["Specific Article"], [], []],
            )
        )
        respx.get("https://en.wikipedia.org/api/rest_v1/page/summary/Specific_Article").mock(
            return_value=Response(
                200,
                json={
                    "title": "Specific Article",
                    "extract": "This is the article summary.",
                },
            )
        )

        response = await plugin.handle("specific term", context, {})

        assert "Specific Article" in response.message
        assert "article summary" in response.message

    @pytest.mark.asyncio
    @respx.mock
    async def test_search_no_results(self, plugin: WikipediaPlugin, context: NodeContext) -> None:
        """Test search with no results."""
        respx.get("https://en.wikipedia.org/w/api.php").mock(
            return_value=Response(200, json=["query", [], [], []])
        )

        response = await plugin.handle("nonexistentterm12345", context, {})

        assert "No results" in response.message

    @pytest.mark.asyncio
    @respx.mock
    async def test_search_command(self, plugin: WikipediaPlugin, context: NodeContext) -> None:
        """Test !search command."""
        respx.get("https://en.wikipedia.org/w/api.php").mock(
            return_value=Response(200, json=["test", ["Test Article"], [], []])
        )
        respx.get("https://en.wikipedia.org/api/rest_v1/page/summary/Test_Article").mock(
            return_value=Response(
                200,
                json={"title": "Test Article", "extract": "Test content"},
            )
        )

        response = await plugin.handle("!search test", context, {})

        assert "Test Article" in response.message

    @pytest.mark.asyncio
    @respx.mock
    async def test_random_article(self, plugin: WikipediaPlugin, context: NodeContext) -> None:
        """Test !random command."""
        respx.get("https://en.wikipedia.org/api/rest_v1/page/random/summary").mock(
            return_value=Response(
                200,
                json={
                    "title": "Random Article",
                    "extract": "This is a random article about something.",
                },
            )
        )

        response = await plugin.handle("!random", context, {})

        assert "Random Article" in response.message
        assert "random article about something" in response.message

    @pytest.mark.asyncio
    @respx.mock
    async def test_select_from_results(self, plugin: WikipediaPlugin, context: NodeContext) -> None:
        """Test selecting numbered result."""
        respx.get("https://en.wikipedia.org/api/rest_v1/page/summary/Second_Article").mock(
            return_value=Response(
                200,
                json={
                    "title": "Second Article",
                    "extract": "Content of second article.",
                },
            )
        )

        state = {"last_results": ["First Article", "Second Article", "Third Article"]}
        response = await plugin.handle("2", context, state)

        assert "Second Article" in response.message

    @pytest.mark.asyncio
    @respx.mock
    async def test_summary_truncation(self, plugin: WikipediaPlugin, context: NodeContext) -> None:
        """Test that long summaries are truncated."""
        long_text = "x" * 500
        respx.get("https://en.wikipedia.org/api/rest_v1/page/random/summary").mock(
            return_value=Response(
                200,
                json={"title": "Article", "extract": long_text},
            )
        )

        response = await plugin.handle("!random", context, {})

        assert len(response.message) <= 450  # Title + newlines + truncated text
        assert "..." in response.message

    @pytest.mark.asyncio
    async def test_empty_search_query(self, plugin: WikipediaPlugin, context: NodeContext) -> None:
        """Test empty search query."""
        response = await plugin.handle("!search ", context, {})

        assert "Usage" in response.message

    @pytest.mark.asyncio
    async def test_empty_message_prompts_search(
        self, plugin: WikipediaPlugin, context: NodeContext
    ) -> None:
        """Test empty message prompts for search."""
        response = await plugin.handle("", context, {})

        assert "Send a topic" in response.message

    @pytest.mark.asyncio
    @respx.mock
    async def test_malformed_search_response(
        self, plugin: WikipediaPlugin, context: NodeContext
    ) -> None:
        """Test handling of malformed search response."""
        respx.get("https://en.wikipedia.org/w/api.php").mock(
            return_value=Response(
                200,
                json={"unexpected": "format"},
            )
        )

        response = await plugin.handle("test", context, {})

        # Should handle gracefully
        assert response.message

    @pytest.mark.asyncio
    @respx.mock
    async def test_invalid_selection_number(
        self, plugin: WikipediaPlugin, context: NodeContext
    ) -> None:
        """Test selecting invalid number from results."""
        state = {"last_results": ["Article 1", "Article 2"]}

        response = await plugin.handle("99", context, state)

        assert response.message  # Should provide feedback
