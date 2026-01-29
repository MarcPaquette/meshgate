"""Tests for LLM plugin."""

import pytest
import respx
from httpx import Response

from meshgate.interfaces.node_context import NodeContext
from meshgate.plugins.llm_plugin import LLMPlugin


class TestLLMPlugin:
    """Tests for LLMPlugin class."""

    @pytest.fixture
    def plugin(self) -> LLMPlugin:
        """Create an LLMPlugin."""
        return LLMPlugin(
            ollama_url="http://localhost:11434",
            model="test-model",
            max_response_length=400,
            timeout=5.0,
        )

    def test_metadata(self, plugin: LLMPlugin) -> None:
        """Test plugin metadata."""
        meta = plugin.metadata
        assert meta.name == "LLM Assistant"
        assert meta.menu_number == 2
        assert "!model" in meta.commands
        assert "!clear" in meta.commands

    def test_welcome_message(self, plugin: LLMPlugin) -> None:
        """Test welcome message shows model name."""
        welcome = plugin.get_welcome_message()
        assert "LLM Assistant" in welcome
        assert "test-model" in welcome

    def test_help_text(self, plugin: LLMPlugin) -> None:
        """Test help text includes commands."""
        help_text = plugin.get_help_text()
        assert "!model" in help_text
        assert "!clear" in help_text
        assert "!exit" in help_text

    @pytest.mark.asyncio
    async def test_clear_command(self, plugin: LLMPlugin, context: NodeContext) -> None:
        """Test !clear clears history."""
        state = {"model": "test-model", "history": [{"role": "user", "content": "hi"}]}
        response = await plugin.handle("!clear", context, state)

        assert "cleared" in response.message.lower()
        assert response.plugin_state["history"] == []

    @pytest.mark.asyncio
    @respx.mock
    async def test_list_models(self, plugin: LLMPlugin, context: NodeContext) -> None:
        """Test !models lists available models."""
        respx.get("http://localhost:11434/api/tags").mock(
            return_value=Response(
                200,
                json={
                    "models": [
                        {"name": "llama3.2"},
                        {"name": "mistral"},
                    ]
                },
            )
        )

        response = await plugin.handle("!models", context, {})

        assert "llama3.2" in response.message
        assert "mistral" in response.message

    @pytest.mark.asyncio
    @respx.mock
    async def test_switch_model(self, plugin: LLMPlugin, context: NodeContext) -> None:
        """Test !model switches to specified model."""
        respx.get("http://localhost:11434/api/tags").mock(
            return_value=Response(
                200,
                json={"models": [{"name": "mistral"}]},
            )
        )

        response = await plugin.handle("!model mistral", context, {})

        assert "Switched to mistral" in response.message
        assert response.plugin_state["model"] == "mistral"

    @pytest.mark.asyncio
    @respx.mock
    async def test_switch_model_not_found(self, plugin: LLMPlugin, context: NodeContext) -> None:
        """Test switching to non-existent model."""
        respx.get("http://localhost:11434/api/tags").mock(
            return_value=Response(
                200,
                json={"models": [{"name": "llama3.2"}]},
            )
        )

        response = await plugin.handle("!model nonexistent", context, {})

        assert "not found" in response.message.lower()

    @pytest.mark.asyncio
    @respx.mock
    async def test_prompt_response(self, plugin: LLMPlugin, context: NodeContext) -> None:
        """Test sending a prompt and receiving response."""
        respx.post("http://localhost:11434/api/chat").mock(
            return_value=Response(
                200,
                json={
                    "message": {
                        "role": "assistant",
                        "content": "Test response from LLM",
                    }
                },
            )
        )

        response = await plugin.handle("Hello", context, {"model": "test-model", "history": []})

        assert "Test response from LLM" in response.message
        assert len(response.plugin_state["history"]) == 2

    @pytest.mark.asyncio
    @respx.mock
    async def test_response_truncation(self, plugin: LLMPlugin, context: NodeContext) -> None:
        """Test that long responses are truncated."""
        long_response = "x" * 500
        respx.post("http://localhost:11434/api/chat").mock(
            return_value=Response(
                200,
                json={
                    "message": {
                        "role": "assistant",
                        "content": long_response,
                    }
                },
            )
        )

        response = await plugin.handle("Hello", context, {"model": "test-model", "history": []})

        assert len(response.message) <= 400
        assert response.message.endswith("...")

    @pytest.mark.asyncio
    @respx.mock
    async def test_connection_error(self, plugin: LLMPlugin, context: NodeContext) -> None:
        """Test handling connection error."""
        respx.post("http://localhost:11434/api/chat").mock(
            side_effect=Exception("Connection refused")
        )

        response = await plugin.handle("Hello", context, {"model": "test-model", "history": []})

        # Should return error message, not crash
        assert "error" in response.message.lower() or "connect" in response.message.lower()

    @pytest.mark.asyncio
    @respx.mock
    async def test_history_limited(self, plugin: LLMPlugin, context: NodeContext) -> None:
        """Test that history is limited in size."""
        respx.post("http://localhost:11434/api/chat").mock(
            return_value=Response(
                200,
                json={
                    "message": {
                        "role": "assistant",
                        "content": "Response",
                    }
                },
            )
        )

        # Start with long history
        long_history = [{"role": "user", "content": f"msg{i}"} for i in range(20)]
        response = await plugin.handle(
            "New message", context, {"model": "test-model", "history": long_history}
        )

        # History should be trimmed
        assert len(response.plugin_state["history"]) <= 8
