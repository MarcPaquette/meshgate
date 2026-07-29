"""Web dashboard for Meshgate.

Optional: requires the `web` extra (``uv sync --extra web``). Nothing in the
core gateway imports this package unless the dashboard is enabled.
"""

from meshgate.web.app import create_app, serve

__all__ = ["create_app", "serve"]
