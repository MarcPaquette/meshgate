"""Base classes for plugins with common functionality."""

import logging
from abc import ABC
from typing import Any

import httpx

from meshgate.interfaces.plugin import Plugin, PluginResponse

logger = logging.getLogger(__name__)


class HTTPPluginBase(Plugin, ABC):
    """Base class for plugins that make HTTP requests.

    Provides common HTTP error handling, retry logic, and timeout management.
    Subclasses should use the protected methods for making HTTP requests.

    Example usage:
        class MyAPIPlugin(HTTPPluginBase):
            def __init__(self):
                super().__init__(timeout=10.0, service_name="My API")

            async def handle(self, message, context, plugin_state):
                async with self._create_client() as client:
                    result = await self._safe_request(
                        client.get, "https://api.example.com/data"
                    )
                    if isinstance(result, PluginResponse):
                        return result  # Error occurred
                    return PluginResponse(message=result.text)
    """

    DEFAULT_TIMEOUT = 10.0

    def __init__(
        self,
        timeout: float | None = None,
        service_name: str = "service",
    ) -> None:
        """Initialize HTTP plugin base.

        Args:
            timeout: Request timeout in seconds (default: 10.0)
            service_name: Human-readable service name for error messages
        """
        self.timeout = timeout if timeout is not None else self.DEFAULT_TIMEOUT
        self.service_name = service_name

    def _create_client(self) -> httpx.AsyncClient:
        """Create an HTTP client with configured timeout.

        Returns:
            Configured httpx.AsyncClient for use with async context manager
        """
        return httpx.AsyncClient(timeout=self.timeout)

    async def _safe_request(
        self,
        request_func: Any,
        *args: Any,
        **kwargs: Any,
    ) -> httpx.Response | PluginResponse:
        """Execute an HTTP request with error handling.

        Args:
            request_func: The HTTP method to call (e.g., client.get)
            *args: Positional arguments for the request
            **kwargs: Keyword arguments for the request

        Returns:
            httpx.Response on success, or PluginResponse with error message
        """
        try:
            response = await request_func(*args, **kwargs)
            response.raise_for_status()
            return response
        except httpx.ConnectError:
            return PluginResponse(message=f"Cannot connect to {self.service_name}.")
        except httpx.TimeoutException:
            return PluginResponse(message=f"Request to {self.service_name} timed out.")
        except httpx.HTTPStatusError as e:
            logger.error(f"{self.service_name} HTTP error: {e.response.status_code}")
            return PluginResponse(
                message=f"{self.service_name} error: HTTP {e.response.status_code}"
            )
        except Exception as e:
            logger.error(f"{self.service_name} error: {e}")
            return PluginResponse(message=f"{self.service_name} error: {e}")

    async def _request_json(
        self,
        method: str,
        url: str,
        **kwargs: Any,
    ) -> dict[str, Any] | PluginResponse:
        """Make an HTTP request and parse the JSON response.

        Args:
            method: HTTP method name ("get" or "post")
            url: The URL to request
            **kwargs: Arguments passed to the httpx method (params, headers, json, etc.)

        Returns:
            Parsed JSON dict on success, or PluginResponse with error message
        """
        try:
            async with self._create_client() as client:
                request_func = getattr(client, method)
                response = await self._safe_request(request_func, url, **kwargs)
                if isinstance(response, PluginResponse):
                    return response
                return response.json()
        except Exception as e:
            logger.error(f"JSON parsing error from {self.service_name}: {e}")
            return PluginResponse(message=f"Invalid response from {self.service_name}")

    async def _fetch_json(
        self,
        url: str,
        params: dict[str, Any] | None = None,
        headers: dict[str, str] | None = None,
    ) -> dict[str, Any] | PluginResponse:
        """Fetch JSON data from a URL with error handling.

        Args:
            url: The URL to fetch
            params: Optional query parameters
            headers: Optional headers

        Returns:
            Parsed JSON dict on success, or PluginResponse with error message
        """
        return await self._request_json("get", url, params=params, headers=headers)

    async def _post_json(
        self,
        url: str,
        json_data: dict[str, Any],
        headers: dict[str, str] | None = None,
    ) -> dict[str, Any] | PluginResponse:
        """POST JSON data to a URL with error handling.

        Args:
            url: The URL to POST to
            json_data: JSON data to send
            headers: Optional headers

        Returns:
            Parsed JSON response on success, or PluginResponse with error message
        """
        return await self._request_json("post", url, json=json_data, headers=headers)

    @staticmethod
    def _truncate(text: str, max_length: int, suffix: str = "...") -> str:
        """Truncate text to a maximum length with a suffix.

        Args:
            text: Text to truncate
            max_length: Maximum length including suffix
            suffix: Suffix to add when truncating (default: "...")

        Returns:
            Truncated text with suffix, or original if within limit
        """
        if len(text) <= max_length:
            return text
        return text[: max_length - len(suffix)] + suffix
