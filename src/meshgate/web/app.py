"""FastAPI application for the dashboard."""

import asyncio
import logging
from contextlib import suppress
from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from meshgate.server import HandlerServer
from meshgate.web.routes import router
from meshgate.web.security import guard_request

logger = logging.getLogger(__name__)

STATIC_DIR = Path(__file__).parent / "static"


def create_app(server: HandlerServer) -> FastAPI:
    """Build the dashboard application.

    Args:
        server: The running gateway, read by the API handlers

    Returns:
        Configured FastAPI app
    """
    app = FastAPI(
        title="Meshgate Dashboard",
        description="Plugins, sessions, logs and chat transcripts for a Meshgate gateway",
        version="1.0.0",
    )

    # Handlers reach the gateway through app.state rather than a global.
    app.state.server = server

    # Deliberately no CORS middleware: cross-origin reads should stay blocked.
    app.middleware("http")(guard_request)

    app.include_router(router)

    if STATIC_DIR.is_dir():
        app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")

        @app.get("/", include_in_schema=False)
        async def index() -> FileResponse:
            """Serve the dashboard page."""
            return FileResponse(STATIC_DIR / "index.html")

    return app


async def serve(server: HandlerServer) -> None:
    """Run the dashboard until cancelled.

    Args:
        server: The running gateway
    """
    import uvicorn

    web = server.config.web
    app = create_app(server)

    config = uvicorn.Config(
        app,
        host=web.host,
        port=web.port,
        # The gateway already configured logging; let uvicorn use it rather
        # than installing its own handlers, so its records also reach the
        # dashboard's log buffer.
        log_config=None,
        access_log=False,
        # Shares the gateway's loop - required, since the API reads unlocked
        # structures that the message path mutates.
        loop="none",
        lifespan="off",
    )
    uvicorn_server = uvicorn.Server(config)

    if web.host not in ("127.0.0.1", "localhost", "::1"):
        logger.warning(
            "SECURITY: dashboard bound to %s, not loopback. It exposes session "
            "content and allows plugin and session changes with no "
            "authentication.",
            web.host,
        )

    logger.info(f"Dashboard listening on http://{web.host}:{web.port}")
    try:
        await uvicorn_server.serve()
    except asyncio.CancelledError:
        # uvicorn does not close its listening socket when serve() is
        # cancelled, which would leave the port bound. Ask it to shut down
        # explicitly, shielded so this cleanup is not itself cancelled.
        uvicorn_server.should_exit = True
        with suppress(Exception):
            await asyncio.shield(uvicorn_server.shutdown())
        raise
    finally:
        logger.info("Dashboard stopped")
