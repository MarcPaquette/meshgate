"""Base classes for plugins with common functionality."""

import logging
from abc import ABC
from collections.abc import Callable, Coroutine
from typing import Any, TypeVar

import httpx

from meshgate.interfaces.plugin import Plugin, PluginResponse

logger = logging.getLogger(__name__)

T = TypeVar("T")


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
        self._timeout = timeout if timeout is not None else self.DEFAULT_TIMEOUT
        self._service_name = service_name

    @property
    def timeout(self) -> float:
        """Get the configured timeout."""
        return self._timeout

    @property
    def service_name(self) -> str:
        """Get the service name for error messages."""
        return self._service_name

    def _create_client(self) -> httpx.AsyncClient:
        """Create an HTTP client with configured timeout.

        Returns:
            Configured httpx.AsyncClient for use with async context manager
        """
        return httpx.AsyncClient(timeout=self._timeout)

    async def _safe_request(
        self,
        request_func: Callable[..., Coroutine[Any, Any, httpx.Response]],
        *args: Any,
        **kwargs: Any,
    ) -> httpx.Response | PluginResponse:
        """Execute an HTTP request with error handling.

        Wraps the request in try/except and returns appropriate error
        responses for common HTTP errors.

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
            return self._error_response(f"Cannot connect to {self._service_name}.")
        except httpx.TimeoutException:
            return self._error_response(f"Request to {self._service_name} timed out.")
        except httpx.HTTPStatusError as e:
            logger.error(f"{self._service_name} HTTP error: {e.response.status_code}")
            return self._error_response(
                f"{self._service_name} error: HTTP {e.response.status_code}"
            )
        except Exception as e:
            logger.error(f"{self._service_name} error: {e}")
            return self._error_response(f"{self._service_name} error: {e}")

    async def _fetch_json(
        self,
        url: str,
        params: dict[str, Any] | None = None,
        headers: dict[str, str] | None = None,
    ) -> dict[str, Any] | PluginResponse:
        """Fetch JSON data from a URL with error handling.

        Convenience method that combines client creation, request, and JSON parsing.

        Args:
            url: The URL to fetch
            params: Optional query parameters
            headers: Optional headers

        Returns:
            Parsed JSON dict on success, or PluginResponse with error message
        """
        try:
            async with self._create_client() as client:
                response = await self._safe_request(client.get, url, params=params, headers=headers)
                if isinstance(response, PluginResponse):
                    return response
                return response.json()
        except Exception as e:
            logger.error(f"JSON parsing error from {self._service_name}: {e}")
            return self._error_response(f"Invalid response from {self._service_name}")

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
        try:
            async with self._create_client() as client:
                response = await self._safe_request(
                    client.post, url, json=json_data, headers=headers
                )
                if isinstance(response, PluginResponse):
                    return response
                return response.json()
        except Exception as e:
            logger.error(f"POST error to {self._service_name}: {e}")
            return self._error_response(f"Request to {self._service_name} failed")

    def _error_response(
        self,
        message: str,
        plugin_state: dict[str, Any] | None = None,
    ) -> PluginResponse:
        """Create an error response.

        Args:
            message: Error message to display
            plugin_state: Optional state to preserve

        Returns:
            PluginResponse with error message
        """
        return PluginResponse(message=message, plugin_state=plugin_state)

    def _success_response(
        self,
        message: str,
        plugin_state: dict[str, Any] | None = None,
        exit_plugin: bool = False,
    ) -> PluginResponse:
        """Create a success response.

        Args:
            message: Message to display
            plugin_state: Optional state update
            exit_plugin: Whether to exit to menu

        Returns:
            PluginResponse with message
        """
        return PluginResponse(
            message=message,
            plugin_state=plugin_state,
            exit_plugin=exit_plugin,
        )
