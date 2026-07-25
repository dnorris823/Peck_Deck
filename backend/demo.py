"""Demo mode — FLEDGE Phase 5.

Turns a running stack into something a reviewer can be handed a URL to: with
``DEMO_MODE=1`` the app seeds itself on first boot and then refuses every
user-authenticated write, so the instance stays clickable but unspoilable.

Two deliberate asymmetries:

* **Device writes stay open.** ``POST /sightings``, the device heartbeat and the
  Tier 3 ``POST /classify`` relay are all device-token routes, and blocking them
  would freeze the demo into the same static snapshot ``backend/seed.py`` already
  produces. Leaving them open is what lets ``backend.simulator`` drive a *live*
  feed through the real pipeline.
* **Login stays open.** A read-only demo you can't sign into isn't a demo.

The block is enforced by path+method rather than by inspecting the caller's
credentials, because it runs as ASGI middleware — before any guard has resolved
who is calling. That makes the allowlist below the whole security surface of the
feature, so it is written out explicitly rather than derived.
"""
import json
import logging
import re

from litestar.status_codes import HTTP_403_FORBIDDEN
from litestar.types import ASGIApp, Receive, Scope, Send

from .config import settings
from .observability import get_request_id

logger = logging.getLogger("peckdeck.demo")

_WRITE_METHODS = frozenset({"POST", "PUT", "PATCH", "DELETE"})

# Routes that keep working in demo mode. Every entry is either device-token
# authenticated (the Pi / the simulator) or unauthenticated by design (login).
_ALLOWED_WRITES: tuple[re.Pattern[str], ...] = (
    re.compile(r"^/login/?$"),                       # sign in as the demo user
    re.compile(r"^/sightings/?$"),                   # device_guard — Pi upload
    re.compile(r"^/classify/?$"),                    # device_guard — Tier 3 relay
    re.compile(r"^/devices/\d+/heartbeat/?$"),       # device_guard — telemetry
)

DEMO_BLOCK_DETAIL = (
    "This is a read-only demo instance — sign-in and browsing work, but changes "
    "are not saved."
)


def is_write_allowed(method: str, path: str) -> bool:
    """Would demo mode permit this request? (Pure — the unit tests drive this.)"""
    if method.upper() not in _WRITE_METHODS:
        return True
    return any(pattern.match(path) for pattern in _ALLOWED_WRITES)


def demo_readonly_middleware(app: ASGIApp) -> ASGIApp:
    """Reject user-facing writes with 403 while ``DEMO_MODE`` is on.

    ``settings.DEMO_MODE`` is read per request rather than captured at
    construction so the flag can be flipped in tests without rebuilding the app.
    """

    async def middleware(scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] == "http" and settings.DEMO_MODE:
            method = scope.get("method", "GET")
            path = scope.get("path", "")
            if not is_write_allowed(method, path):
                logger.info("demo mode blocked %s %s", method, path)
                await _forbidden(scope, send, method, path)
                return
        await app(scope, receive, send)

    return middleware


async def _forbidden(scope: Scope, send: Send, method: str, path: str) -> None:
    """Emit the same error envelope backend/errors.py produces, by hand.

    The exception handlers live inside the app this middleware wraps, so raising
    here would escape them — the response has to be written directly. It is
    mounted *inside* ``RequestContextMiddleware``, so the request id is already
    bound and the access log still sees the 403.
    """
    body = json.dumps({
        "status_code": HTTP_403_FORBIDDEN,
        "type": "Forbidden",
        "detail": DEMO_BLOCK_DETAIL,
        "request_id": get_request_id(),
        "extra": {"demo_mode": True, "method": method, "path": path},
    }).encode()

    await send({
        "type": "http.response.start",
        "status": HTTP_403_FORBIDDEN,
        "headers": [
            (b"content-type", b"application/json"),
            (b"content-length", str(len(body)).encode()),
        ],
    })
    await send({"type": "http.response.body", "body": body})


async def maybe_seed_demo() -> None:
    """Populate an empty database at boot so a fresh clone lands on real content.

    No-ops unless ``DEMO_MODE`` is on, and never touches a database that already
    has the demo owner in it — re-running ``docker compose up`` must not stack a
    second copy of the dataset on top of the first.

    Schema creation is *not* done here: it belongs to Alembic, which
    ``entrypoint.sh`` runs before the app starts.
    """
    if not settings.DEMO_MODE:
        return

    from .database.connection import get_session_factory
    from .seed import DEMO_PASSWORD, USERS, owner_exists, seed_demo_data

    try:
        async with get_session_factory()() as db:
            async with db.begin():
                if await owner_exists(db):
                    logger.info("demo mode: database already seeded, leaving it alone")
                    return
                total = await seed_demo_data(db)
    except Exception:
        # A demo seed is a convenience, not a precondition for serving. Failing
        # the whole boot over it would take down an instance that is otherwise
        # perfectly able to answer requests.
        logger.exception("demo mode: seeding failed; starting with an empty database")
        return

    logger.info(
        "demo mode: seeded %d sightings — sign in as %s / %s",
        total, USERS[0]["email"], DEMO_PASSWORD,
    )
