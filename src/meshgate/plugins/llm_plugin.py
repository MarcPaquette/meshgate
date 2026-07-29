"""LLM plugin - Ollama integration for AI assistant functionality."""

import logging
from typing import Any

from meshgate.interfaces.node_context import NodeContext
from meshgate.interfaces.plugin import PluginMetadata, PluginResponse
from meshgate.plugins.base import HTTPPluginBase

logger = logging.getLogger(__name__)


class LLMPlugin(HTTPPluginBase):
    """LLM Assistant plugin using Ollama.

    Connects to a local Ollama instance to provide AI assistant functionality.
    Optimized for short responses suitable for Meshtastic.

    Commands:
        !model - Show current model
        !clear - Clear conversation history
        !help - Show help
        !exit - Return to main menu
    """

    # Maximum tokens for LLM response (keeps responses concise for radio)
    MAX_TOKENS = 150

    # Maximum conversation history messages (4 exchanges = 8 messages)
    MAX_HISTORY_MESSAGES = 8

    SYSTEM_PROMPT = (
        "You are a helpful assistant responding via a low-bandwidth radio network. "
        "Keep responses very brief and concise (under 200 characters when possible). "
        "Avoid markdown formatting, bullet points, and long explanations. "
        "Be direct and informative."
    )

    def __init__(
        self,
        ollama_url: str = "http://localhost:11434",
        model: str = "llama3.2",
        max_response_length: int = 400,
        timeout: float = 30.0,
    ) -> None:
        """Initialize the LLM plugin.

        Args:
            ollama_url: URL of the Ollama API
            model: Default model to use
            max_response_length: Maximum response length in characters
            timeout: Request timeout in seconds
        """
        super().__init__(timeout=timeout, service_name="Ollama")
        self._ollama_url = ollama_url.rstrip("/")
        self._default_model = model
        self._max_response_length = max_response_length

    @property
    def metadata(self) -> PluginMetadata:
        """Return plugin metadata."""
        return PluginMetadata(
            name="LLM Assistant",
            description="Ask AI questions",
            menu_number=2,
            commands=("!model", "!clear", "!help", "!exit"),
        )

    def get_welcome_message(self) -> str:
        """Message shown when user enters this plugin."""
        return (
            f"LLM Assistant (model: {self._default_model})\n"
            "Send your question or !help for commands."
        )

    def get_help_text(self) -> str:
        """Help text showing plugin-specific commands."""
        return (
            "LLM Commands:\n"
            "[message] - Ask a question\n"
            "!model - Show current model\n"
            "!clear - Clear history\n"
            "!help - Show this help\n"
            "!exit - Return to menu"
        )

    async def handle(
        self, message: str, context: NodeContext, plugin_state: dict[str, Any]
    ) -> PluginResponse:
        """Handle a message while user is in this plugin."""
        message = message.strip()

        history = plugin_state.get("history", [])

        # Handle commands
        if message.lower() == "!clear":
            return self._handle_clear()

        if message.lower() == "!model":
            return PluginResponse(
                message=f"Current model: {self._default_model}",
                plugin_state={"history": history},
            )

        # Regular message - send to LLM
        return await self._handle_prompt(message, history)

    def _handle_clear(self) -> PluginResponse:
        """Handle the !clear command."""
        return PluginResponse(
            message="Conversation cleared.",
            plugin_state={"history": []},
        )

    async def _handle_prompt(self, prompt: str, history: list[dict[str, str]]) -> PluginResponse:
        """Send prompt to Ollama and return response."""
        # Build messages with history
        messages = [{"role": "system", "content": self.SYSTEM_PROMPT}]
        messages.extend(history)
        messages.append({"role": "user", "content": prompt})

        result = await self._post_json(
            f"{self._ollama_url}/api/chat",
            json_data={
                "model": self._default_model,
                "messages": messages,
                "stream": False,
                "options": {
                    "num_predict": self.MAX_TOKENS,
                },
            },
        )

        if isinstance(result, PluginResponse):
            return PluginResponse(
                message=result.message,
                plugin_state={"history": history},
            )

        assistant_message = result.get("message", {}).get("content", "")
        if not assistant_message:
            return PluginResponse(
                message="No response from model.",
                plugin_state={"history": history},
            )

        assistant_message = self._truncate(assistant_message, self._max_response_length)

        # Update history (keep last 4 exchanges to manage context)
        new_history = history.copy()
        new_history.append({"role": "user", "content": prompt})
        new_history.append({"role": "assistant", "content": assistant_message})
        if len(new_history) > self.MAX_HISTORY_MESSAGES:
            new_history = new_history[-self.MAX_HISTORY_MESSAGES :]

        return PluginResponse(
            message=assistant_message,
            plugin_state={"history": new_history},
        )
