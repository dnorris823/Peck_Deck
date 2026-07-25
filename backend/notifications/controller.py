"""Web push subscription endpoints — FLEDGE Phase 7.

Three routes, all user-authenticated:

* ``GET /push/config`` — the VAPID public key the browser must subscribe with,
  and whether the server has keys at all.
* ``POST /push/subscriptions`` — store the subscription the browser just made.
* ``DELETE /push/subscriptions?endpoint=…`` — forget it again.

The endpoint travels as a query parameter rather than a request body because
DELETE bodies are optional in HTTP and get dropped by some proxies. It is the
subscription's identifier, and deletion is always scoped to the caller — a user
can never unsubscribe someone else's browser by guessing its endpoint.
"""
import logging
from urllib.parse import urlsplit

from litestar import Controller, Request, delete, get, post
from litestar.di import NamedDependency
from litestar.exceptions import HTTPException, NotFoundException
from litestar.params import FromQuery
from sqlalchemy.ext.asyncio import AsyncSession

from ..auth.guards import user_guard
from ..database.models import PushSubscription
from .push import delete_subscription, list_subscriptions, upsert_subscription
from .push_sender import b64url_decode, push_enabled, vapid_public_key
from .schemas import PushConfigResponse, SubscribeRequest, SubscriptionResponse

logger = logging.getLogger(__name__)

# A P-256 uncompressed point is 65 bytes; the auth secret is 16 (RFC 8291 §3.2).
_P256DH_BYTES = 65
_AUTH_BYTES = 16
# Browsers send their full UA string; store a label, not a fingerprint dossier.
_MAX_LABEL = 200


def _endpoint_hint(endpoint: str) -> str:
    parts = urlsplit(endpoint)
    tail = parts.path.rstrip("/")[-8:]
    return f"{parts.netloc}/…{tail}" if tail else parts.netloc


def _to_response(sub: PushSubscription) -> SubscriptionResponse:
    return SubscriptionResponse(
        id=sub.id,
        created_at=sub.created_at.isoformat(),
        user_agent=sub.user_agent,
        endpoint_hint=_endpoint_hint(sub.endpoint),
    )


def _validate_keys(p256dh: str, auth: str) -> None:
    """Reject a subscription we could never encrypt for.

    Without this a malformed key is stored happily and then fails on every
    single notification, where the only symptom is a log line — far from the
    request that caused it.
    """
    try:
        p256dh_len = len(b64url_decode(p256dh))
        auth_len = len(b64url_decode(auth))
    except Exception:
        raise HTTPException(status_code=400, detail="keys must be base64url-encoded")
    if p256dh_len != _P256DH_BYTES:
        raise HTTPException(
            status_code=400,
            detail=f"keys.p256dh must decode to {_P256DH_BYTES} bytes, got {p256dh_len}",
        )
    if auth_len != _AUTH_BYTES:
        raise HTTPException(
            status_code=400,
            detail=f"keys.auth must decode to {_AUTH_BYTES} bytes, got {auth_len}",
        )


class PushController(Controller):
    path = "/push"
    guards = [user_guard]
    tags = ["notifications"]

    @get("/config")
    async def config(self) -> PushConfigResponse:
        """Advertise the VAPID public key (or that push is unavailable here)."""
        return PushConfigResponse(enabled=push_enabled(), public_key=vapid_public_key())

    @get("/subscriptions")
    async def list_mine(
        self, request: Request, db: NamedDependency[AsyncSession]
    ) -> list[SubscriptionResponse]:
        subs = await list_subscriptions(db, request.state.user_id)
        return [_to_response(s) for s in subs]

    @post("/subscriptions", status_code=201)
    async def subscribe(
        self, data: SubscribeRequest, request: Request, db: NamedDependency[AsyncSession]
    ) -> SubscriptionResponse:
        endpoint = data.endpoint.strip()
        if not endpoint.startswith("https://"):
            # Push services are always HTTPS. Anything else is either a mistake
            # or an attempt to make the server POST payloads somewhere internal.
            raise HTTPException(
                status_code=400, detail="endpoint must be an https:// URL"
            )
        _validate_keys(data.keys.p256dh, data.keys.auth)

        label = (data.user_agent or request.headers.get("user-agent") or "").strip()
        sub = await upsert_subscription(
            db,
            user_id=request.state.user_id,
            endpoint=endpoint,
            p256dh=data.keys.p256dh,
            auth=data.keys.auth,
            user_agent=label[:_MAX_LABEL] or None,
        )
        logger.info(
            "push subscription stored for user %d (%s)",
            request.state.user_id, _endpoint_hint(endpoint),
        )
        return _to_response(sub)

    @delete("/subscriptions", status_code=204)
    async def unsubscribe(
        self,
        request: Request,
        db: NamedDependency[AsyncSession],
        endpoint: FromQuery[str],
    ) -> None:
        removed = await delete_subscription(
            db, user_id=request.state.user_id, endpoint=endpoint.strip()
        )
        if not removed:
            raise NotFoundException(detail="No such subscription for this user")
