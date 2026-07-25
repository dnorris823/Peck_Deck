"""Web push seam — FLEDGE Phase 7, verified on the wire.

The unit tests in ``backend/tests/test_push.py`` prove the crypto by decrypting a
body in-process. This proves the *transport*: a real ``aiohttp`` POST from the
real notification dispatcher to a real HTTP server standing in for a browser push
service, over a real socket, with a real Postgres row driving it.

What that catches which the unit tests cannot: a wrong header name, a body the
HTTP layer mangles, a VAPID token signed with a key that doesn't match the one
advertised in ``k=``, and the pruning of a dead subscription actually committing
to the database.

The stand-in service is HTTP rather than HTTPS (no local TLS). Real endpoints are
always HTTPS — ``POST /push/subscriptions`` rejects anything else — but nothing
in the transport depends on the scheme.
"""
import asyncio
import json
import secrets
import struct
from datetime import datetime, timezone

import jwt
import pytest
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.hkdf import HKDF
from sqlalchemy import select

from backend.config import settings
from backend.database.connection import dispose_db, get_session_factory, init_db
from backend.database.models import Device, PushSubscription, Sighting, Species, User
from backend.notifications.push_sender import (
    b64url_decode,
    b64url_encode,
    public_key_bytes,
    reset_keypair_cache,
)
from backend.notifications.service import NotificationService

from ._live import run_server

_VAPID_PRIVATE = ec.generate_private_key(ec.SECP256R1())
_VAPID_PRIVATE_B64 = b64url_encode(
    _VAPID_PRIVATE.private_numbers().private_value.to_bytes(32, "big")
)


class FakePushService:
    """Minimal ASGI app that records the pushes sent to it.

    Answers every POST with ``status``, so a test can make the service claim the
    subscription is gone and watch the dispatcher clean up.
    """

    def __init__(self, status: int = 201):
        self.status = status
        self.received: list[dict] = []

    async def __call__(self, scope, receive, send):
        if scope["type"] == "lifespan":
            # uvicorn runs with lifespan="on"; a plain callable that ignores the
            # protocol makes it abort startup rather than serve.
            while True:
                message = await receive()
                if message["type"] == "lifespan.startup":
                    await send({"type": "lifespan.startup.complete"})
                elif message["type"] == "lifespan.shutdown":
                    await send({"type": "lifespan.shutdown.complete"})
                    return
        assert scope["type"] == "http"
        body = b""
        while True:
            message = await receive()
            body += message.get("body", b"")
            if not message.get("more_body"):
                break

        self.received.append({
            "path": scope["path"],
            "headers": {k.decode(): v.decode() for k, v in scope["headers"]},
            "body": body,
        })
        await send({"type": "http.response.start", "status": self.status,
                    "headers": [(b"content-type", b"text/plain")]})
        await send({"type": "http.response.body", "body": b""})


def _browser_keys() -> tuple[ec.EllipticCurvePrivateKey, str, bytes, str]:
    private = ec.generate_private_key(ec.SECP256R1())
    auth = secrets.token_bytes(16)
    return private, b64url_encode(public_key_bytes(private.public_key())), auth, b64url_encode(auth)


def _decrypt(body: bytes, ua_private, auth_secret: bytes) -> bytes:
    """The receiving half of RFC 8291 — exactly what a browser does."""
    salt, ciphertext = body[:16], body[21 + body[20]:]
    assert struct.unpack("!I", body[16:20])[0] == 4096
    as_public = body[21:21 + body[20]]

    shared = ua_private.exchange(
        ec.ECDH(),
        ec.EllipticCurvePublicKey.from_encoded_point(ec.SECP256R1(), as_public),
    )
    ua_public = public_key_bytes(ua_private.public_key())
    ikm = HKDF(algorithm=hashes.SHA256(), length=32, salt=auth_secret,
               info=b"WebPush: info\x00" + ua_public + as_public).derive(shared)
    key = HKDF(algorithm=hashes.SHA256(), length=16, salt=salt,
               info=b"Content-Encoding: aes128gcm\x00").derive(ikm)
    nonce = HKDF(algorithm=hashes.SHA256(), length=12, salt=salt,
                 info=b"Content-Encoding: nonce\x00").derive(ikm)
    return AESGCM(key).decrypt(nonce, ciphertext, None)[:-1]


@pytest.fixture
def vapid(monkeypatch):
    monkeypatch.setattr(settings, "VAPID_PRIVATE_KEY", _VAPID_PRIVATE_B64)
    monkeypatch.setattr(settings, "VAPID_PUBLIC_KEY", "")
    monkeypatch.setattr(settings, "VAPID_SUBJECT", "mailto:ops@peckdeck.test")
    reset_keypair_cache()
    yield
    reset_keypair_cache()


async def _seed_subscriber(endpoint: str, p256dh: str, auth: str) -> tuple[int, int, str]:
    """A recipient with email/SMS off and one push subscription."""
    async with get_session_factory()() as db:
        async with db.begin():
            user = User(
                name="Push Contract", email=f"pc_{secrets.token_hex(4)}@test.dev",
                password_hash="x", role="owner", notify_email=False, notify_sms=False,
            )
            db.add(user)
            await db.flush()
            device = Device(
                name="Wire Feeder", owner_id=user.id, city="Burlington", state="VT",
                classification_tier="auto", token=secrets.token_urlsafe(12),
            )
            species = Species(
                common_name=f"WireBird {secrets.token_hex(3)}",
                genus="Testus", species_name="wireus",
            )
            db.add_all([device, species])
            await db.flush()
            sighting = Sighting(
                species_id=species.id, device_id=device.id,
                datetime=datetime.now(timezone.utc), confidence_score=0.88,
                classification_tier_used="local", delayed=False,
            )
            db.add(sighting)
            db.add(PushSubscription(
                user_id=user.id, endpoint=endpoint, p256dh=p256dh, auth=auth,
                user_agent="Contract Browser", created_at=datetime.now(timezone.utc),
            ))
            await db.flush()
            return sighting.id, device.id, species.common_name


async def _subscription_count(endpoint: str) -> int:
    async with get_session_factory()() as db:
        rows = (await db.execute(
            select(PushSubscription).where(PushSubscription.endpoint == endpoint)
        )).scalars().all()
        return len(rows)


def run_scenario(endpoint: str, p256dh: str, auth_b64: str) -> dict:
    """Seed, dispatch and re-count in a **single** event loop.

    asyncpg connections belong to the loop that opened them, so splitting this
    across several ``asyncio.run`` calls hands the second loop a dead pool — the
    dispatch then fails inside its own try/except and the test sees "no push
    sent" with no explanation. One loop per scenario, with a fresh engine bound
    to it, keeps that impossible.
    """
    async def scenario() -> dict:
        init_db(settings.DATABASE_URL)
        try:
            sighting_id, device_id, common_name = await _seed_subscriber(
                endpoint, p256dh, auth_b64
            )
            await NotificationService().dispatch(sighting_id, device_id)
            return {
                "sighting_id": sighting_id,
                "device_id": device_id,
                "common_name": common_name,
                "subscriptions_left": await _subscription_count(endpoint),
            }
        finally:
            await dispose_db()

    return asyncio.run(scenario())


def test_dispatch_delivers_a_decryptable_push_over_a_real_socket(ids, vapid):
    service = FakePushService()
    ua_private, p256dh, auth_secret, auth_b64 = _browser_keys()

    with run_server(service) as base_url:
        result = run_scenario(f"{base_url}/push/send/contract-token", p256dh, auth_b64)

    assert len(service.received) == 1, "the dispatcher never reached the push service"
    request = service.received[0]

    assert request["headers"]["content-encoding"] == "aes128gcm"
    assert request["headers"]["content-type"] == "application/octet-stream"
    assert request["headers"]["ttl"] == str(settings.PUSH_TTL_SECONDS)

    payload = json.loads(_decrypt(request["body"], ua_private, auth_secret))
    assert result["common_name"] in payload["title"]
    assert "Wire Feeder" in payload["title"]
    assert "88% confident" in payload["body"]
    assert payload["data"]["sighting_id"] == result["sighting_id"]


def test_the_vapid_token_verifies_against_the_key_it_advertises(ids, vapid):
    """A token signed by a key other than `k=` is rejected by every real service."""
    service = FakePushService()
    _, p256dh, _, auth_b64 = _browser_keys()

    with run_server(service) as base_url:
        run_scenario(f"{base_url}/push/send/vapid-check", p256dh, auth_b64)
        origin = base_url

    authorization = service.received[0]["headers"]["authorization"]
    token, advertised = (
        part.split("=", 1)[1] for part in authorization.removeprefix("vapid ").split(",")
    )

    advertised_key = ec.EllipticCurvePublicKey.from_encoded_point(
        ec.SECP256R1(), b64url_decode(advertised)
    )
    claims = jwt.decode(token, advertised_key, algorithms=["ES256"], audience=origin)
    assert claims["aud"] == origin  # origin only — never the endpoint path
    assert claims["sub"] == "mailto:ops@peckdeck.test"


def test_a_gone_endpoint_is_pruned_from_the_database(ids, vapid):
    """410 means the browser is gone for good; the row must not survive it."""
    service = FakePushService(status=410)
    _, p256dh, _, auth_b64 = _browser_keys()

    with run_server(service) as base_url:
        result = run_scenario(f"{base_url}/push/send/dead-token", p256dh, auth_b64)

    assert len(service.received) == 1
    assert result["subscriptions_left"] == 0


def test_a_transient_failure_keeps_the_subscription(ids, vapid):
    """503 is an outage, not a dead browser — deleting the row would lose it."""
    service = FakePushService(status=503)
    _, p256dh, _, auth_b64 = _browser_keys()

    with run_server(service) as base_url:
        result = run_scenario(f"{base_url}/push/send/flaky-token", p256dh, auth_b64)

    assert len(service.received) == 1
    assert result["subscriptions_left"] == 1
