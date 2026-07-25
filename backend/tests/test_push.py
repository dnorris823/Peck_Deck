"""Web push tests — FLEDGE Phase 7.

Three layers, deliberately separated:

* **Crypto** — the RFC 8291 body is decrypted back with the receiver's private
  key, which is the only check that actually proves a real browser could read
  it. A test that merely asserted "some bytes came out" would pass on a payload
  no push service could deliver.
* **Routes** — subscription storage, validation, and ownership scoping.
* **Dispatch** — that a stored subscription becomes a push, and that a dead
  endpoint prunes itself.

No network anywhere: the HTTP POST to the push service is faked, and the
notification service's ``send_push`` is monkeypatched the same way the existing
email/SMS tests fake theirs.
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

from backend.config import settings
from backend.database.connection import get_session_factory
from backend.database.models import Device, PushSubscription, Sighting, Species, User
from backend.notifications import push_sender
from backend.notifications import service as notif_module
from backend.notifications.push_sender import (
    PushResult,
    PushTarget,
    b64url_decode,
    b64url_encode,
    encrypt_payload,
    public_key_bytes,
    push_enabled,
    reset_keypair_cache,
    send_push,
    vapid_public_key,
)
from backend.notifications.service import NotificationService

# A throwaway VAPID keypair. Generated once here rather than per test so the
# derived-public-key assertions have something stable to compare against.
_VAPID_PRIVATE = ec.generate_private_key(ec.SECP256R1())
_VAPID_PRIVATE_B64 = b64url_encode(
    _VAPID_PRIVATE.private_numbers().private_value.to_bytes(32, "big")
)
_VAPID_PUBLIC_B64 = b64url_encode(public_key_bytes(_VAPID_PRIVATE.public_key()))


# ── Helpers ──────────────────────────────────────────────────────────────────
def _fake_browser() -> tuple[ec.EllipticCurvePrivateKey, str, bytes, str]:
    """Stand in for a browser's subscription keys.

    Returns (private key, base64url public point, auth secret, base64url auth).
    """
    private = ec.generate_private_key(ec.SECP256R1())
    p256dh = b64url_encode(public_key_bytes(private.public_key()))
    auth = secrets.token_bytes(16)
    return private, p256dh, auth, b64url_encode(auth)


def _browser_decrypt(body: bytes, ua_private: ec.EllipticCurvePrivateKey,
                     auth_secret: bytes) -> bytes:
    """The receiver half of RFC 8291 — what the browser does with the body."""
    salt = body[:16]
    record_size = struct.unpack("!I", body[16:20])[0]
    key_id_len = body[20]
    as_public_bytes = body[21:21 + key_id_len]
    ciphertext = body[21 + key_id_len:]
    assert record_size == 4096
    assert key_id_len == 65

    shared = ua_private.exchange(
        ec.ECDH(),
        ec.EllipticCurvePublicKey.from_encoded_point(ec.SECP256R1(), as_public_bytes),
    )
    ua_public_bytes = public_key_bytes(ua_private.public_key())
    ikm = HKDF(
        algorithm=hashes.SHA256(), length=32, salt=auth_secret,
        info=b"WebPush: info\x00" + ua_public_bytes + as_public_bytes,
    ).derive(shared)
    key = HKDF(
        algorithm=hashes.SHA256(), length=16, salt=salt,
        info=b"Content-Encoding: aes128gcm\x00",
    ).derive(ikm)
    nonce = HKDF(
        algorithm=hashes.SHA256(), length=12, salt=salt,
        info=b"Content-Encoding: nonce\x00",
    ).derive(ikm)

    plaintext = AESGCM(key).decrypt(nonce, ciphertext, None)
    # Strip the padding delimiter (0x02 marks the final record).
    return plaintext.rstrip(b"\x00")[:-1]


@pytest.fixture
def vapid_configured(monkeypatch):
    """Configure a VAPID keypair for the duration of one test."""
    monkeypatch.setattr(settings, "VAPID_PRIVATE_KEY", _VAPID_PRIVATE_B64)
    monkeypatch.setattr(settings, "VAPID_PUBLIC_KEY", _VAPID_PUBLIC_B64)
    monkeypatch.setattr(settings, "VAPID_SUBJECT", "mailto:test@peckdeck.local")
    reset_keypair_cache()
    yield
    reset_keypair_cache()


class _FakeResponse:
    def __init__(self, status: int, text: str = ""):
        self.status = status
        self._text = text

    async def text(self):
        return self._text

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False


class _FakeSession:
    """Minimal aiohttp.ClientSession stand-in that records the one POST made."""

    calls: list[dict] = []
    status = 201

    def __init__(self, *a, **kw):
        pass

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    def post(self, url, *, data=None, headers=None, timeout=None):
        type(self).calls.append({"url": url, "data": data, "headers": headers})
        return _FakeResponse(type(self).status)


@pytest.fixture
def fake_http(monkeypatch):
    _FakeSession.calls = []
    _FakeSession.status = 201
    monkeypatch.setattr(push_sender.aiohttp, "ClientSession", _FakeSession)
    return _FakeSession


# ── base64url ────────────────────────────────────────────────────────────────
def test_b64url_round_trip_is_unpadded():
    raw = secrets.token_bytes(65)
    encoded = b64url_encode(raw)
    assert "=" not in encoded
    assert b64url_decode(encoded) == raw


def test_b64url_decode_accepts_padded_and_standard_alphabet():
    raw = secrets.token_bytes(32)
    import base64
    assert b64url_decode(base64.urlsafe_b64encode(raw).decode()) == raw
    assert b64url_decode(base64.b64encode(raw).decode()) == raw


# ── RFC 8291 encryption ──────────────────────────────────────────────────────
def test_encrypted_payload_is_readable_by_the_subscribed_browser():
    ua_private, p256dh, auth_secret, auth_b64 = _fake_browser()
    payload = json.dumps({"title": "Blue Jay", "body": "94% confident"}).encode()

    body = encrypt_payload(payload, p256dh, auth_b64)

    assert _browser_decrypt(body, ua_private, auth_secret) == payload


def test_each_encryption_uses_a_fresh_salt_and_ephemeral_key():
    """Reusing either would let two pushes share a content key (RFC 8291 §2)."""
    _, p256dh, _, auth_b64 = _fake_browser()
    a = encrypt_payload(b"same", p256dh, auth_b64)
    b = encrypt_payload(b"same", p256dh, auth_b64)

    assert a[:16] != b[:16]          # salt
    assert a[21:86] != b[21:86]      # ephemeral server public key
    assert a != b


def test_encrypt_rejects_a_key_that_is_not_a_p256_point():
    with pytest.raises(ValueError, match="uncompressed point"):
        encrypt_payload(b"x", b64url_encode(b"too short"), b64url_encode(b"0" * 16))


# ── VAPID ────────────────────────────────────────────────────────────────────
def test_push_is_disabled_without_a_private_key(monkeypatch):
    monkeypatch.setattr(settings, "VAPID_PRIVATE_KEY", "")
    reset_keypair_cache()
    try:
        assert push_enabled() is False
        assert vapid_public_key() is None
    finally:
        reset_keypair_cache()


def test_public_key_is_derived_from_the_private_key(vapid_configured):
    assert vapid_public_key() == _VAPID_PUBLIC_B64


def test_mismatched_configured_public_key_loses_to_the_derived_one(monkeypatch):
    """A wrong VAPID_PUBLIC_KEY must not be handed to browsers.

    If it were, every browser would subscribe with a key the server can't sign
    for, and the failure would only appear later as a 403 from the push service
    on every single notification.
    """
    other = ec.generate_private_key(ec.SECP256R1())
    monkeypatch.setattr(settings, "VAPID_PRIVATE_KEY", _VAPID_PRIVATE_B64)
    monkeypatch.setattr(
        settings, "VAPID_PUBLIC_KEY", b64url_encode(public_key_bytes(other.public_key()))
    )
    reset_keypair_cache()
    try:
        assert vapid_public_key() == _VAPID_PUBLIC_B64
    finally:
        reset_keypair_cache()


def test_unparseable_private_key_disables_push_instead_of_raising(monkeypatch):
    monkeypatch.setattr(settings, "VAPID_PRIVATE_KEY", "not-a-key!!!")
    reset_keypair_cache()
    try:
        assert push_enabled() is False
    finally:
        reset_keypair_cache()


def test_vapid_token_audience_is_the_origin_only(vapid_configured, fake_http):
    """The endpoint path identifies the recipient — it must not leak into `aud`."""
    _, p256dh, _, auth_b64 = _fake_browser()
    target = PushTarget(
        endpoint="https://fcm.googleapis.com/fcm/send/secret-user-token",
        p256dh=p256dh, auth=auth_b64,
    )

    result = asyncio.run(send_push(target, {"title": "hi"}))
    assert result.ok

    auth_header = fake_http.calls[0]["headers"]["Authorization"]
    assert auth_header.startswith("vapid t=")
    token = auth_header.removeprefix("vapid t=").split(",")[0]
    claims = jwt.decode(
        token, _VAPID_PRIVATE.public_key(), algorithms=["ES256"],
        audience="https://fcm.googleapis.com",
    )
    assert claims["aud"] == "https://fcm.googleapis.com"
    assert claims["sub"] == "mailto:test@peckdeck.local"
    assert "secret-user-token" not in token


def test_send_push_sets_the_aes128gcm_content_headers(vapid_configured, fake_http):
    _, p256dh, _, auth_b64 = _fake_browser()
    asyncio.run(send_push(PushTarget("https://push.example/x", p256dh, auth_b64), {"a": 1}))

    headers = fake_http.calls[0]["headers"]
    assert headers["Content-Encoding"] == "aes128gcm"
    assert headers["Content-Type"] == "application/octet-stream"
    assert headers["TTL"] == str(settings.PUSH_TTL_SECONDS)


# ── send_push outcomes ───────────────────────────────────────────────────────
def test_send_push_without_keys_reports_not_configured(monkeypatch):
    monkeypatch.setattr(settings, "VAPID_PRIVATE_KEY", "")
    reset_keypair_cache()
    try:
        result = asyncio.run(
            send_push(PushTarget("https://push.example/x", "k", "a"), {"t": 1})
        )
        assert result == PushResult(ok=False, error="not_configured")
    finally:
        reset_keypair_cache()


@pytest.mark.parametrize("status", [404, 410])
def test_dead_endpoint_statuses_report_gone(vapid_configured, fake_http, status):
    fake_http.status = status
    _, p256dh, _, auth_b64 = _fake_browser()

    result = asyncio.run(
        send_push(PushTarget("https://push.example/x", p256dh, auth_b64), {"t": 1})
    )
    assert (result.ok, result.gone, result.status) == (False, True, status)


def test_transient_failure_is_not_reported_as_gone(vapid_configured, fake_http):
    """A 429/500 must leave the subscription alone — it will work again later."""
    fake_http.status = 429
    _, p256dh, _, auth_b64 = _fake_browser()

    result = asyncio.run(
        send_push(PushTarget("https://push.example/x", p256dh, auth_b64), {"t": 1})
    )
    assert (result.ok, result.gone) == (False, False)


def test_unencryptable_subscription_is_treated_as_gone(vapid_configured, fake_http):
    """A malformed key can never succeed, so retrying it forever is pointless."""
    result = asyncio.run(
        send_push(PushTarget("https://push.example/x", b64url_encode(b"short"), "AAAA"), {})
    )
    assert (result.ok, result.gone) == (False, True)
    assert fake_http.calls == []  # never even attempted the request


# ── Routes ───────────────────────────────────────────────────────────────────
def _subscription_body(endpoint: str | None = None) -> dict:
    _, p256dh, _, auth_b64 = _fake_browser()
    return {
        "endpoint": endpoint or f"https://push.example.com/send/{secrets.token_hex(8)}",
        "keys": {"p256dh": p256dh, "auth": auth_b64},
        "user_agent": "Pytest Browser",
    }


def test_push_config_reports_disabled_when_the_server_has_no_keys(
    client, owner_headers, monkeypatch
):
    """The frontend hides the opt-in on this answer, rather than failing later."""
    monkeypatch.setattr(settings, "VAPID_PRIVATE_KEY", "")
    reset_keypair_cache()
    try:
        res = client.get("/push/config", headers=owner_headers)
        assert res.status_code == 200
        assert res.json() == {"enabled": False, "public_key": None}
    finally:
        reset_keypair_cache()


def test_push_config_publishes_the_key_when_configured(
    client, owner_headers, vapid_configured
):
    res = client.get("/push/config", headers=owner_headers)
    assert res.json() == {"enabled": True, "public_key": _VAPID_PUBLIC_B64}


def test_push_routes_require_a_user_token(client):
    assert client.get("/push/config").status_code == 401
    assert client.post("/push/subscriptions", json=_subscription_body()).status_code == 401


def test_subscribe_then_list_and_unsubscribe(client, owner_headers):
    body = _subscription_body()
    res = client.post("/push/subscriptions", json=body, headers=owner_headers)
    assert res.status_code == 201
    created = res.json()
    assert created["user_agent"] == "Pytest Browser"
    # The hint identifies the browser without echoing the capability URL.
    assert created["endpoint_hint"].startswith("push.example.com/…")
    assert body["endpoint"] not in created["endpoint_hint"]

    listed = client.get("/push/subscriptions", headers=owner_headers).json()
    assert body["endpoint"] not in json.dumps(listed)
    assert created["id"] in [s["id"] for s in listed]

    res = client.delete(
        "/push/subscriptions", params={"endpoint": body["endpoint"]}, headers=owner_headers
    )
    assert res.status_code == 204
    remaining = client.get("/push/subscriptions", headers=owner_headers).json()
    assert created["id"] not in [s["id"] for s in remaining]


def test_resubscribing_the_same_endpoint_replaces_the_row(client, owner_headers):
    """Otherwise the browser would receive every alert once per stale row."""
    body = _subscription_body()
    first = client.post("/push/subscriptions", json=body, headers=owner_headers).json()

    body2 = _subscription_body(endpoint=body["endpoint"])
    body2["user_agent"] = "Renamed Browser"
    second = client.post("/push/subscriptions", json=body2, headers=owner_headers).json()

    assert second["id"] == first["id"]
    assert second["user_agent"] == "Renamed Browser"
    hits = [
        s for s in client.get("/push/subscriptions", headers=owner_headers).json()
        if s["id"] == first["id"]
    ]
    assert len(hits) == 1

    client.delete("/push/subscriptions", params={"endpoint": body["endpoint"]},
                  headers=owner_headers)


def test_subscribe_rejects_a_non_https_endpoint(client, owner_headers):
    body = _subscription_body(endpoint="http://internal.local/admin")
    res = client.post("/push/subscriptions", json=body, headers=owner_headers)
    assert res.status_code == 400
    assert "https" in res.json()["detail"]


@pytest.mark.parametrize("field,value", [
    ("p256dh", b64url_encode(b"too short")),
    ("auth", b64url_encode(b"not sixteen bytes")),
    ("p256dh", "!!! not base64 !!!"),
])
def test_subscribe_rejects_malformed_keys(client, owner_headers, field, value):
    """Stored bad keys would fail silently on every future notification."""
    body = _subscription_body()
    body["keys"][field] = value
    res = client.post("/push/subscriptions", json=body, headers=owner_headers)
    assert res.status_code == 400


def test_unsubscribe_is_scoped_to_the_caller(client, owner_headers, viewer_headers):
    body = _subscription_body()
    client.post("/push/subscriptions", json=body, headers=owner_headers)

    # The viewer knows the endpoint but does not own it.
    res = client.delete(
        "/push/subscriptions", params={"endpoint": body["endpoint"]}, headers=viewer_headers
    )
    assert res.status_code == 404
    still_there = client.get("/push/subscriptions", headers=owner_headers).json()
    assert body["endpoint"][-8:] in json.dumps(still_there)

    client.delete("/push/subscriptions", params={"endpoint": body["endpoint"]},
                  headers=owner_headers)


def test_unsubscribe_unknown_endpoint_is_404(client, owner_headers):
    res = client.delete(
        "/push/subscriptions", params={"endpoint": "https://push.example.com/nope"},
        headers=owner_headers,
    )
    assert res.status_code == 404


def test_list_shows_only_the_callers_subscriptions(client, owner_headers, viewer_headers):
    mine = _subscription_body()
    theirs = _subscription_body()
    client.post("/push/subscriptions", json=mine, headers=owner_headers)
    client.post("/push/subscriptions", json=theirs, headers=viewer_headers)

    hints = [
        s["endpoint_hint"]
        for s in client.get("/push/subscriptions", headers=viewer_headers).json()
    ]
    assert any(h.endswith(theirs["endpoint"][-8:]) for h in hints)
    assert not any(h.endswith(mine["endpoint"][-8:]) for h in hints)

    client.delete("/push/subscriptions", params={"endpoint": mine["endpoint"]},
                  headers=owner_headers)
    client.delete("/push/subscriptions", params={"endpoint": theirs["endpoint"]},
                  headers=viewer_headers)


# ── Dispatch integration ─────────────────────────────────────────────────────
async def _mk_recipient_with_subscription(n_subs: int = 1):
    """A user with a device, a species, a sighting and n push subscriptions."""
    async with get_session_factory()() as db:
        async with db.begin():
            u = User(
                name="Push User", email=f"push_{secrets.token_hex(4)}@test.dev",
                password_hash="x", role="owner", notify_email=False, notify_sms=False,
            )
            db.add(u)
            await db.flush()
            d = Device(
                name="Push Feeder", owner_id=u.id, city="Ithaca", state="NY",
                classification_tier="auto", token=secrets.token_urlsafe(12),
            )
            sp = Species(
                common_name=f"PushBird {secrets.token_hex(3)}",
                genus="Genus", species_name="species",
            )
            db.add_all([d, sp])
            await db.flush()
            s = Sighting(
                species_id=sp.id, device_id=d.id, datetime=datetime.now(timezone.utc),
                confidence_score=0.91, classification_tier_used="gpu", delayed=False,
            )
            db.add(s)
            endpoints = []
            for _ in range(n_subs):
                _, p256dh, _, auth_b64 = _fake_browser()
                endpoint = f"https://push.example.com/send/{secrets.token_hex(8)}"
                endpoints.append(endpoint)
                db.add(PushSubscription(
                    user_id=u.id, endpoint=endpoint, p256dh=p256dh, auth=auth_b64,
                    user_agent="Pytest", created_at=datetime.now(timezone.utc),
                ))
            await db.flush()
            return s.id, d.id, endpoints


async def _endpoint_exists(endpoint: str) -> bool:
    from sqlalchemy import select
    async with get_session_factory()() as db:
        row = (await db.execute(
            select(PushSubscription).where(PushSubscription.endpoint == endpoint)
        )).scalar_one_or_none()
        return row is not None


def _patch_push(monkeypatch, *, gone: bool = False):
    sent: list[tuple[str, dict]] = []

    async def fake_send_push(target, payload):
        sent.append((target.endpoint, payload))
        return PushResult(ok=not gone, gone=gone, status=410 if gone else 201)

    monkeypatch.setattr(notif_module, "send_push", fake_send_push)
    monkeypatch.setattr(notif_module, "push_enabled", lambda: True)
    return sent


def test_dispatch_pushes_to_every_subscription_of_a_recipient(client, monkeypatch):
    sent = _patch_push(monkeypatch)
    sid, did, endpoints = asyncio.run(_mk_recipient_with_subscription(n_subs=2))

    asyncio.run(NotificationService().dispatch(sid, did))

    assert sorted(e for e, _ in sent) == sorted(endpoints)
    payload = sent[0][1]
    assert "PushBird" in payload["title"] and "Push Feeder" in payload["title"]
    assert "91% confident" in payload["body"]
    assert "Ithaca — NY" in payload["body"]
    # The worker has no session and cannot look anything up, so ids ride along.
    assert payload["data"]["sighting_id"] == sid
    assert payload["tag"] == f"peckdeck-device-{did}"


def test_dispatch_sends_nothing_when_push_is_not_configured(client, monkeypatch):
    sent = _patch_push(monkeypatch)
    monkeypatch.setattr(notif_module, "push_enabled", lambda: False)
    sid, did, _ = asyncio.run(_mk_recipient_with_subscription())

    asyncio.run(NotificationService().dispatch(sid, did))
    assert sent == []


def test_dispatch_prunes_a_subscription_the_push_service_calls_gone(client, monkeypatch):
    _patch_push(monkeypatch, gone=True)
    sid, did, endpoints = asyncio.run(_mk_recipient_with_subscription())
    assert asyncio.run(_endpoint_exists(endpoints[0])) is True

    asyncio.run(NotificationService().dispatch(sid, did))

    assert asyncio.run(_endpoint_exists(endpoints[0])) is False


def test_push_is_independent_of_the_email_and_sms_flags(client, monkeypatch):
    """A stored subscription *is* the opt-in — notify_email/sms don't gate it."""
    sent = _patch_push(monkeypatch)
    sid, did, endpoints = asyncio.run(_mk_recipient_with_subscription())
    # The recipient was created with notify_email=False, notify_sms=False.
    asyncio.run(NotificationService().dispatch(sid, did))
    assert [e for e, _ in sent] == endpoints
