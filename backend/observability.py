"""Request-scoped logging context and structured log configuration.

Every HTTP request is tagged with a short **request id** (taken from an inbound
``X-Request-Id`` header when present, otherwise generated). The id is:

* stored in a :class:`~contextvars.ContextVar` so any log record emitted while
  handling the request carries it (see :class:`RequestIdFilter`),
* echoed back on the response as ``X-Request-Id`` so a client/log line can be
  correlated with the server,
* included in the uniform error envelope (see :mod:`backend.errors`).

:class:`RequestContextMiddleware` also emits one structured access-log line per
request with method, path, status, and duration.
"""
import logging
import time
import uuid
from contextvars import ContextVar

from litestar.types import ASGIApp, Message, Receive, Scope, Send

# "-" when no request is in flight (e.g. startup logs, background tasks that
# don't set it). Access logs and the error envelope read this.
request_id_ctx: ContextVar[str] = ContextVar("request_id", default="-")

access_logger = logging.getLogger("peckdeck.access")


def get_request_id() -> str:
    return request_id_ctx.get()


class RequestIdFilter(logging.Filter):
    """Attach the current request id to every log record as ``request_id``."""

    def filter(self, record: logging.LogRecord) -> bool:
        record.request_id = request_id_ctx.get()
        return True


def configure_logging(level: int = logging.INFO) -> None:
    """Install a single stream handler with a request-id-aware formatter.

    Idempotent: re-running replaces the root handler rather than stacking a new
    one (important under test runners / reloaders that import the app twice).
    """
    handler = logging.StreamHandler()
    handler.addFilter(RequestIdFilter())
    handler.setFormatter(
        logging.Formatter(
            "%(asctime)s %(levelname)s %(name)s [req=%(request_id)s] %(message)s"
        )
    )
    root = logging.getLogger()
    root.handlers = [handler]
    root.setLevel(level)


class RequestContextMiddleware:
    """ASGI middleware: set the request-id context, echo the header, access-log."""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        headers = dict(scope.get("headers") or [])
        inbound = headers.get(b"x-request-id")
        request_id = inbound.decode("latin-1") if inbound else uuid.uuid4().hex[:16]
        token = request_id_ctx.set(request_id)
        started = time.monotonic()
        status_code = 0

        async def send_wrapper(message: Message) -> None:
            nonlocal status_code
            if message["type"] == "http.response.start":
                status_code = message["status"]
                message.setdefault("headers", [])
                message["headers"].append((b"x-request-id", request_id.encode("latin-1")))
            await send(message)

        try:
            await self.app(scope, receive, send_wrapper)
        finally:
            duration_ms = (time.monotonic() - started) * 1000
            access_logger.info(
                "%s %s -> %d (%.1fms)",
                scope.get("method", "-"),
                scope.get("path", "-"),
                status_code,
                duration_ms,
            )
            request_id_ctx.reset(token)
