"""Interfaces module - Abstract base classes and dataclasses."""

from meshgate.interfaces.message_transport import (
    IncomingMessage,
    MessageHandler,
    MessageTransport,
)
from meshgate.interfaces.node_context import GPSLocation, NodeContext
from meshgate.interfaces.plugin import Plugin, PluginMetadata, PluginResponse

__all__ = [
    "GPSLocation",
    "IncomingMessage",
    "MessageHandler",
    "MessageTransport",
    "NodeContext",
    "Plugin",
    "PluginMetadata",
    "PluginResponse",
]
