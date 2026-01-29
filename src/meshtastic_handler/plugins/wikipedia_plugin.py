"""Wikipedia plugin - Search and read Wikipedia articles."""

import logging
from typing import Any

import httpx

from meshtastic_handler.interfaces.node_context import NodeContext
from meshtastic_handler.interfaces.plugin import Plugin, PluginMetadata, PluginResponse

logger = logging.getLogger(__name__)


class WikipediaPlugin(Plugin):
    """Wikipedia search and summary plugin.

    Search Wikipedia and get article summaries optimized for Meshtastic.

    Commands:
        !search <query> - Search Wikipedia
        !random - Get a random article
        !help - Show help
        !exit - Return to main menu

    Any other text is treated as a search query.
    """

    # Required by Wikipedia API policy
    USER_AGENT = "MeshtasticHandlerServer/1.0 (https://github.com/meshtastic-handler-server)"

    def __init__(
        self,
        language: str = "en",
        max_summary_length: int = 400,
        timeout: float = 10.0,
    ) -> None:
        """Initialize the Wikipedia plugin.

        Args:
            language: Wikipedia language code (e.g., "en", "de", "fr")
            max_summary_length: Maximum summary length in characters
            timeout: Request timeout in seconds
        """
        self._language = language
        self._max_summary_length = max_summary_length
        self._timeout = timeout
        self._base_url = f"https://{language}.wikipedia.org/api/rest_v1"
        self._headers = {"User-Agent": self.USER_AGENT}

    @property
    def metadata(self) -> PluginMetadata:
        """Return plugin metadata."""
        return PluginMetadata(
            name="Wikipedia",
            description="Search Wikipedia",
            menu_number=4,
            commands=("!search", "!random", "!help", "!exit"),
        )

    def get_welcome_message(self) -> str:
        """Message shown when user enters this plugin."""
        return (
            "Wikipedia Search\n"
            "Send a topic to search or !help for commands."
        )

    def get_help_text(self) -> str:
        """Help text showing plugin-specific commands."""
        return (
            "Wikipedia Commands:\n"
            "[topic] - Search for topic\n"
            "!search <query> - Search\n"
            "!random - Random article\n"
            "!help - Show this help\n"
            "!exit - Return to menu"
        )

    async def handle(
        self, message: str, context: NodeContext, plugin_state: dict[str, Any]
    ) -> PluginResponse:
        """Handle a message while user is in this plugin."""
        message = message.strip()
        message_lower = message.lower()

        # Handle commands
        if message_lower == "!random":
            return await self._handle_random()

        if message_lower == "!search" or message_lower.startswith("!search "):
            query = message[7:].strip() if len(message) > 7 else ""
            if query:
                return await self._handle_search(query)
            return PluginResponse(
                message="Usage: !search <query>", plugin_state=plugin_state
            )

        # Check if there's a last search with numbered results
        last_results = plugin_state.get("last_results", [])
        if last_results:
            try:
                selection = int(message)
                if 1 <= selection <= len(last_results):
                    title = last_results[selection - 1]
                    return await self._get_summary(title)
            except ValueError:
                pass

        # Treat as search query
        if message:
            return await self._handle_search(message)

        return PluginResponse(
            message="Send a topic to search.", plugin_state=plugin_state
        )

    async def _handle_search(self, query: str) -> PluginResponse:
        """Search Wikipedia for articles matching query."""
        try:
            async with httpx.AsyncClient(
                timeout=self._timeout, headers=self._headers
            ) as client:
                # Use Wikipedia search API
                response = await client.get(
                    f"https://{self._language}.wikipedia.org/w/api.php",
                    params={
                        "action": "opensearch",
                        "search": query,
                        "limit": 5,
                        "namespace": 0,
                        "format": "json",
                    },
                )
                response.raise_for_status()
                data = response.json()

            # opensearch returns: [query, [titles], [descriptions], [urls]]
            titles = data[1] if len(data) > 1 else []

            if not titles:
                return PluginResponse(
                    message=f"No results for '{query}'.",
                    plugin_state={"last_results": []},
                )

            # If only one result, show summary directly
            if len(titles) == 1:
                return await self._get_summary(titles[0])

            # Multiple results - show numbered list
            lines = [f"Results for '{query}':"]
            for i, title in enumerate(titles, 1):
                lines.append(f"{i}. {title}")
            lines.append("\nSend number to select")

            return PluginResponse(
                message="\n".join(lines),
                plugin_state={"last_results": titles, "last_query": query},
            )

        except httpx.ConnectError:
            return PluginResponse(message="Cannot connect to Wikipedia.")
        except httpx.TimeoutException:
            return PluginResponse(message="Search timed out.")
        except Exception as e:
            logger.error(f"Wikipedia search error: {e}")
            return PluginResponse(message=f"Search error: {e}")

    async def _handle_random(self) -> PluginResponse:
        """Get a random Wikipedia article summary."""
        try:
            async with httpx.AsyncClient(
                timeout=self._timeout, headers=self._headers
            ) as client:
                response = await client.get(
                    f"{self._base_url}/page/random/summary",
                    follow_redirects=True,
                )
                response.raise_for_status()
                data = response.json()

            title = data.get("title", "Unknown")
            extract = data.get("extract", "No content available.")

            # Truncate if needed
            if len(extract) > self._max_summary_length:
                extract = extract[: self._max_summary_length - 3] + "..."

            return PluginResponse(
                message=f"{title}\n\n{extract}",
                plugin_state={"last_title": title},
            )

        except httpx.ConnectError:
            return PluginResponse(message="Cannot connect to Wikipedia.")
        except httpx.TimeoutException:
            return PluginResponse(message="Request timed out.")
        except Exception as e:
            logger.error(f"Wikipedia random error: {e}")
            return PluginResponse(message=f"Error: {e}")

    async def _get_summary(self, title: str) -> PluginResponse:
        """Get summary for a specific article title."""
        try:
            # URL-encode the title
            encoded_title = title.replace(" ", "_")

            async with httpx.AsyncClient(
                timeout=self._timeout, headers=self._headers
            ) as client:
                response = await client.get(
                    f"{self._base_url}/page/summary/{encoded_title}",
                    follow_redirects=True,
                )
                response.raise_for_status()
                data = response.json()

            display_title = data.get("title", title)
            extract = data.get("extract", "No content available.")

            # Truncate if needed
            if len(extract) > self._max_summary_length:
                extract = extract[: self._max_summary_length - 3] + "..."

            return PluginResponse(
                message=f"{display_title}\n\n{extract}",
                plugin_state={"last_title": display_title, "last_results": []},
            )

        except httpx.HTTPStatusError as e:
            if e.response.status_code == 404:
                return PluginResponse(
                    message=f"Article '{title}' not found.",
                    plugin_state={"last_results": []},
                )
            raise
        except httpx.ConnectError:
            return PluginResponse(message="Cannot connect to Wikipedia.")
        except httpx.TimeoutException:
            return PluginResponse(message="Request timed out.")
        except Exception as e:
            logger.error(f"Wikipedia summary error: {e}")
            return PluginResponse(message=f"Error: {e}")
