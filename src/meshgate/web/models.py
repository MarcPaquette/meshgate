"""Response models for the dashboard API.

Session and plugin objects held by the running server are live and mutable, so
they are converted into these models immediately rather than being held across
an await.
"""

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field

from meshgate.core.log_buffer import LogEntry
from meshgate.core.session import Session
from meshgate.core.transcript import TranscriptEntry
from meshgate.interfaces.plugin import Plugin


class PluginInfo(BaseModel):
    """A registered plugin and whether it is currently enabled."""

    name: str
    description: str
    menu_number: int
    commands: list[str]
    enabled: bool

    @classmethod
    def from_plugin(cls, plugin: Plugin, enabled: bool) -> "PluginInfo":
        """Build from a live plugin.

        plugin.metadata rebuilds a dataclass on each access, so it is read once.
        """
        meta = plugin.metadata
        return cls(
            name=meta.name,
            description=meta.description,
            menu_number=meta.menu_number,
            commands=list(meta.commands),
            enabled=enabled,
        )


class SessionInfo(BaseModel):
    """Summary of a node's session."""

    node_id: str
    active_plugin: str | None
    at_menu: bool
    last_activity: datetime
    idle_seconds: float

    @classmethod
    def from_session(cls, session: Session) -> "SessionInfo":
        """Snapshot a live, mutable Session."""
        return cls(
            node_id=session.node_id,
            active_plugin=session.active_plugin,
            at_menu=session.is_at_menu,
            last_activity=session.last_activity,
            idle_seconds=round(session.idle_seconds(), 1),
        )


class SessionDetail(SessionInfo):
    """A session plus its plugin state."""

    plugin_state: dict[str, Any]

    @classmethod
    def from_session(cls, session: Session) -> "SessionDetail":
        """Snapshot a live session including a copy of its plugin state."""
        return cls(
            node_id=session.node_id,
            active_plugin=session.active_plugin,
            at_menu=session.is_at_menu,
            last_activity=session.last_activity,
            idle_seconds=round(session.idle_seconds(), 1),
            # Copied: the live dict is mutated by plugins as messages arrive.
            plugin_state=dict(session.plugin_state),
        )


class TranscriptMessage(BaseModel):
    """One recorded message."""

    timestamp: datetime
    direction: str
    text: str

    @classmethod
    def from_entry(cls, entry: TranscriptEntry) -> "TranscriptMessage":
        """Build from a recorded entry."""
        return cls(
            timestamp=entry.timestamp,
            direction=entry.direction.value,
            text=entry.text,
        )


class TranscriptResponse(BaseModel):
    """A node's chat transcript."""

    node_id: str
    messages: list[TranscriptMessage]


class LogRecord(BaseModel):
    """One captured log record."""

    seq: int
    timestamp: datetime
    level: str
    logger: str
    message: str

    @classmethod
    def from_entry(cls, entry: LogEntry) -> "LogRecord":
        """Build from a buffered entry."""
        return cls(
            seq=entry.seq,
            timestamp=entry.timestamp,
            level=entry.level,
            logger=entry.logger_name,
            message=entry.message,
        )


class LogResponse(BaseModel):
    """A page of log records plus the cursor to poll from next."""

    records: list[LogRecord]
    latest_seq: int
    # False when log retention is not enabled, so the UI can say so rather
    # than showing a permanently empty panel.
    available: bool = True


class RateLimitStatus(BaseModel):
    """Rate limiter configuration and current tracking."""

    enabled: bool
    max_messages: int
    window_seconds: int
    tracked_nodes: int


class StatusResponse(BaseModel):
    """Overall server status."""

    running: bool
    transport_connected: bool
    active_sessions: int
    enabled_plugins: int
    disabled_plugins: int
    transcripts_enabled: bool
    logs_available: bool
    rate_limit: RateLimitStatus


class ActionResponse(BaseModel):
    """Result of a state-changing request."""

    ok: bool
    detail: str = Field(default="")
