"""Request guards for the dashboard.

Binding to loopback does not by itself make a control plane private:

- Any page the operator visits can send a cross-origin form POST to
  127.0.0.1 with no CORS preflight, and disable plugins or delete sessions.
- DNS rebinding can point an attacker-controlled hostname at loopback and
  read responses back, including chat transcripts.

These guards close both holes without requiring any configuration. No CORS
middleware is installed anywhere, so cross-origin reads stay blocked by
default.
"""

from collections.abc import Awaitable, Callable

from fastapi import Request, Response
from fastapi.responses import JSONResponse

# Required on state-changing requests. A cross-origin <form> POST cannot set a
# custom header, and adding one forces a CORS preflight the browser will block,
# so requiring it defeats drive-by CSRF.
CSRF_HEADER = "x-meshgate"

MUTATING_METHODS = frozenset({"POST", "PUT", "PATCH", "DELETE"})

# Hostnames that legitimately reach a loopback-bound server.
_LOCAL_HOSTS = frozenset({"localhost", "127.0.0.1", "[::1]", "::1"})


def _host_is_local(host_header: str) -> bool:
    """Check whether a Host header names this machine.

    Args:
        host_header: Raw Host header value, possibly including a port

    Returns:
        True if the host portion is a loopback name
    """
    if not host_header:
        # No Host at all: HTTP/1.1 requires one, and a browser always sends it.
        return False

    host = host_header.strip().lower()

    # Strip the port. Bracketed IPv6 keeps only the bracketed part; a bare
    # host with a single colon has a port; a bare host with several colons is
    # an unbracketed IPv6 literal, where splitting on the last colon would
    # mangle the address ("::1" -> ":").
    if host.startswith("["):
        closing = host.find("]")
        if closing != -1:
            host = host[: closing + 1]
    elif host.count(":") == 1:
        host = host.rsplit(":", 1)[0]

    return host in _LOCAL_HOSTS


async def guard_request(
    request: Request, call_next: Callable[[Request], Awaitable[Response]]
) -> Response:
    """Reject requests that a browser should not have been able to make.

    Args:
        request: The incoming request
        call_next: The next handler in the middleware chain

    Returns:
        The handler's response, or an error response if a guard failed
    """
    if not _host_is_local(request.headers.get("host", "")):
        # Defeats DNS rebinding: an attacker-controlled hostname resolving to
        # loopback carries its own name in Host, not ours.
        return JSONResponse(
            status_code=421,
            content={"detail": "Unrecognized Host header"},
        )

    if request.method.upper() in MUTATING_METHODS:
        if CSRF_HEADER not in request.headers:
            return JSONResponse(
                status_code=403,
                content={"detail": f"Missing required {CSRF_HEADER} header"},
            )

    return await call_next(request)
