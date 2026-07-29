"""Dashboard API routes.

All handlers are async and run on the gateway's own event loop. That is a
requirement, not a convenience: SessionManager and PluginRegistry hold plain
unlocked dicts, and Session is mutable, so touching them from another thread
would race the message path.

Read paths must also avoid the mutating accessors. SessionManager.get_session()
creates a session, refreshes its activity, and reorders the LRU, so a dashboard
calling it would invent sessions merely by rendering. RateLimiter.check()
likewise records a request. Only get_existing_session(), list_sessions(), and
the read-only properties are used here.
"""

import logging

from fastapi import APIRouter, HTTPException, Query, Request, Response

from meshgate.core.log_buffer import get_active_buffer
from meshgate.server import HandlerServer
from meshgate.web.models import (
    ActionResponse,
    LogRecord,
    LogResponse,
    PluginInfo,
    RateLimitStatus,
    SessionDetail,
    SessionInfo,
    StatusResponse,
    TranscriptMessage,
    TranscriptResponse,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api")


def _server(request: Request) -> HandlerServer:
    """Get the running server from application state."""
    return request.app.state.server


@router.get("/status", response_model=StatusResponse)
async def get_status(request: Request) -> StatusResponse:
    """Overall gateway status."""
    server = _server(request)
    limiter = server.rate_limiter

    return StatusResponse(
        running=server.is_running,
        transport_connected=server.transport.is_connected,
        active_sessions=server.session_manager.active_session_count,
        enabled_plugins=server.registry.plugin_count,
        disabled_plugins=server.registry.disabled_count,
        transcripts_enabled=server.transcript.enabled,
        logs_available=get_active_buffer() is not None,
        rate_limit=RateLimitStatus(
            enabled=limiter.enabled,
            max_messages=limiter.max_messages,
            window_seconds=limiter.window_seconds,
            tracked_nodes=limiter.tracked_node_count,
        ),
    )


@router.get("/plugins", response_model=list[PluginInfo])
async def list_plugins(request: Request, response: Response) -> list[PluginInfo]:
    """All known plugins with their enabled state."""
    server = _server(request)
    # The registry version changes only when the plugin set changes, so the
    # client can treat this as an ETag and skip most polls.
    response.headers["ETag"] = f'W/"plugins-{server.registry.version}"'
    return [
        PluginInfo.from_plugin(plugin, enabled) for plugin, enabled in server.registry.list_all()
    ]


@router.post("/plugins/{name}/enable", response_model=ActionResponse)
async def enable_plugin(request: Request, name: str) -> ActionResponse:
    """Enable a disabled plugin."""
    server = _server(request)

    if server.registry.enable(name):
        logger.info(f"Plugin '{name}' enabled via dashboard")
        return ActionResponse(ok=True, detail=f"Enabled '{name}'")

    if name in server.registry:
        return ActionResponse(ok=True, detail=f"'{name}' was already enabled")

    raise HTTPException(status_code=404, detail=f"Unknown plugin '{name}'")


@router.post("/plugins/{name}/disable", response_model=ActionResponse)
async def disable_plugin(request: Request, name: str) -> ActionResponse:
    """Disable an enabled plugin.

    Its menu number stays reserved, so the remaining plugins are not
    renumbered and it can be switched back on.
    """
    server = _server(request)

    if server.registry.disable(name):
        logger.info(f"Plugin '{name}' disabled via dashboard")
        return ActionResponse(ok=True, detail=f"Disabled '{name}'")

    if server.registry.is_disabled(name):
        return ActionResponse(ok=True, detail=f"'{name}' was already disabled")

    raise HTTPException(status_code=404, detail=f"Unknown plugin '{name}'")


@router.get("/sessions", response_model=list[SessionInfo])
async def list_sessions(request: Request) -> list[SessionInfo]:
    """Active sessions, most recently active first."""
    server = _server(request)
    # list_sessions() returns live objects ordered oldest-first; snapshot them
    # straight away rather than holding references.
    sessions = [SessionInfo.from_session(s) for s in server.session_manager.list_sessions()]
    sessions.reverse()
    return sessions


@router.get("/sessions/{node_id}", response_model=SessionDetail)
async def get_session(request: Request, node_id: str) -> SessionDetail:
    """One session, including its plugin state."""
    server = _server(request)
    # get_existing_session, never get_session: the latter would create one.
    session = server.session_manager.get_existing_session(node_id)
    if session is None:
        raise HTTPException(status_code=404, detail=f"No session for '{node_id}'")
    return SessionDetail.from_session(session)


@router.delete("/sessions/{node_id}", response_model=ActionResponse)
async def end_session(request: Request, node_id: str) -> ActionResponse:
    """End a session, discarding its plugin state."""
    server = _server(request)

    if not server.session_manager.remove_session(node_id):
        raise HTTPException(status_code=404, detail=f"No session for '{node_id}'")

    server.transcript.discard(node_id)
    logger.info(f"Session for {node_id} ended via dashboard")
    return ActionResponse(ok=True, detail=f"Ended session for '{node_id}'")


@router.get("/sessions/{node_id}/transcript", response_model=TranscriptResponse)
async def get_transcript(request: Request, node_id: str) -> TranscriptResponse:
    """A node's recorded chat transcript."""
    server = _server(request)

    if not server.transcript.enabled:
        raise HTTPException(
            status_code=404,
            detail="Transcript recording is disabled (set web.transcript_enabled)",
        )

    return TranscriptResponse(
        node_id=node_id,
        messages=[TranscriptMessage.from_entry(e) for e in server.transcript.get(node_id)],
    )


@router.get("/logs", response_model=LogResponse)
async def get_logs(
    since: int = Query(default=0, ge=0, description="Return records newer than this seq"),
    limit: int = Query(default=200, ge=1, le=2000),
) -> LogResponse:
    """Recent log records after a cursor."""
    buffer = get_active_buffer()
    if buffer is None:
        return LogResponse(records=[], latest_seq=0, available=False)

    entries = buffer.entries(since=since, limit=limit)
    return LogResponse(
        records=[LogRecord.from_entry(e) for e in entries],
        latest_seq=buffer.latest_seq,
    )
