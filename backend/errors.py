"""Uniform error envelope for every failure response.

All errors — expected ``HTTPException``s (including Litestar validation errors,
which are 400 ``HTTPException`` subclasses carrying an ``extra`` payload) and
unexpected exceptions alike — are serialized to a single shape::

    {
      "status_code": 404,
      "type": "NotFoundException",
      "detail": "...",           # kept for frontend compatibility (api.js reads it)
      "request_id": "a1b2c3d4",  # correlate with the access log / X-Request-Id
      "extra": [...]             # only present for validation errors
    }

``detail`` is preserved verbatim so the existing frontend keeps working; the
other fields are additive.
"""
import logging
from typing import Any

from litestar import Request, Response
from litestar.exceptions import HTTPException

from .observability import get_request_id

logger = logging.getLogger("peckdeck.error")


def _envelope(status_code: int, exc_type: str, detail: Any, extra: Any = None) -> dict:
    body: dict = {
        "status_code": status_code,
        "type": exc_type,
        "detail": detail,
        "request_id": get_request_id(),
    }
    if extra is not None:
        body["extra"] = extra
    return body


def http_exception_handler(request: Request, exc: HTTPException) -> Response:
    """Render any HTTPException (4xx/5xx, incl. validation) as the envelope."""
    return Response(
        content=_envelope(
            exc.status_code,
            exc.__class__.__name__,
            exc.detail,
            getattr(exc, "extra", None),
        ),
        status_code=exc.status_code,
    )


def unhandled_exception_handler(request: Request, exc: Exception) -> Response:
    """Catch-all: log with the request id and return a 500 envelope (no internals leaked)."""
    logger.exception("Unhandled exception on %s %s", request.method, request.url.path)
    return Response(
        content=_envelope(500, "InternalServerError", "Internal server error"),
        status_code=500,
    )
