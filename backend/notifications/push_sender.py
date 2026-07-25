"""Web push transport — FLEDGE Phase 7.

The fourth notification channel, alongside SendGrid email and Twilio SMS. Unlike
those two there is no vendor: a browser hands out a push-service URL of its own
choosing, and this module speaks the two IETF specs that make such a URL usable:

* **RFC 8291** — message encryption. The payload is encrypted *for the browser*
  with keys only the browser holds, so the push service (Google, Mozilla, Apple)
  relays ciphertext it cannot read. Content encoding ``aes128gcm``.
* **RFC 8292** — VAPID. A short-lived ES256 JWT identifies this server to the
  push service, which is what lets the service rate-limit and contact an abusive
  sender instead of accepting anonymous traffic.

Implemented directly on ``cryptography`` + ``aiohttp`` rather than via
``pywebpush``, which is synchronous (``requests``) and would need a thread per
send. The crypto here is ~30 lines and keeps the channel async like every other
I/O path in the backend.

Configuration is a single VAPID keypair (``scripts/generate_vapid_keys.py``).
With no private key configured this module reports itself disabled and sends
nothing — the same "not configured, skip quietly" contract as email and SMS.
"""
import base64
import json
import logging
import os
import struct
import time
from dataclasses import dataclass
from functools import lru_cache
from urllib.parse import urlsplit

import aiohttp
import jwt
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.hkdf import HKDF

from ..config import settings

logger = logging.getLogger(__name__)

# Fixed strings from RFC 8291 §3.3 / RFC 8188 §2.3.
_KEY_INFO_PREFIX = b"WebPush: info\x00"
_CEK_INFO = b"Content-Encoding: aes128gcm\x00"
_NONCE_INFO = b"Content-Encoding: nonce\x00"
# Record size written into the aes128gcm header. One record is always enough for
# a notification payload; 4096 is the size every push service is required to
# accept.
_RECORD_SIZE = 4096
# Uncompressed P-256 point: 0x04 || X(32) || Y(32).
_P256_POINT_LEN = 65
# A VAPID token may not be valid for more than 24h (RFC 8292 §2). Half that
# leaves room for clock skew on either side.
_VAPID_TTL_SECONDS = 12 * 60 * 60


@dataclass(frozen=True)
class PushTarget:
    """The three fields a browser's PushSubscription gives us."""

    endpoint: str
    p256dh: str  # base64url, uncompressed P-256 point
    auth: str  # base64url, 16-byte shared secret


@dataclass(frozen=True)
class PushResult:
    ok: bool
    status: int | None = None
    # True when the push service says this endpoint is permanently dead (404
    # unknown / 410 gone), which is the signal to delete the subscription row.
    gone: bool = False
    error: str | None = None


# ── base64url without padding (what the Push API and VAPID both use) ─────────
def b64url_encode(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode()


def b64url_decode(value: str) -> bytes:
    """Decode base64url, tolerating missing padding and standard-alphabet input.

    Browsers emit unpadded base64url, but subscription JSON gets copied around
    by hand often enough that accepting `+`/`/` too costs nothing.
    """
    text = value.strip().replace("-", "+").replace("_", "/")
    return base64.b64decode(text + "=" * (-len(text) % 4))


# ── VAPID keypair ────────────────────────────────────────────────────────────
def _load_private_key(raw: str) -> ec.EllipticCurvePrivateKey:
    """Load a VAPID private key from a PEM block or a base64url 32-byte scalar."""
    text = raw.strip()
    if "BEGIN" in text:
        key = serialization.load_pem_private_key(text.encode(), password=None)
        if not isinstance(key, ec.EllipticCurvePrivateKey):
            raise ValueError("VAPID_PRIVATE_KEY is not an EC private key")
        return key
    scalar = b64url_decode(text)
    if len(scalar) != 32:
        raise ValueError(
            f"VAPID_PRIVATE_KEY must decode to 32 bytes, got {len(scalar)}"
        )
    return ec.derive_private_key(int.from_bytes(scalar, "big"), ec.SECP256R1())


def public_key_bytes(key: ec.EllipticCurvePublicKey) -> bytes:
    return key.public_bytes(
        serialization.Encoding.X962, serialization.PublicFormat.UncompressedPoint
    )


@lru_cache(maxsize=1)
def _keypair() -> tuple[ec.EllipticCurvePrivateKey, str] | None:
    """The configured VAPID keypair as (private key, base64url public key).

    The public key is *derived* rather than read from ``VAPID_PUBLIC_KEY``. The
    browser bakes whatever key it subscribed with into the subscription, and the
    push service rejects a token signed by a different key — so a config where
    the two halves don't match would fail only at delivery time, on every send.
    Deriving makes that impossible; a mismatched ``VAPID_PUBLIC_KEY`` is loudly
    logged instead.

    Cached because ``derive_private_key`` is not free and this runs per send.
    """
    if not settings.VAPID_PRIVATE_KEY.strip():
        return None
    try:
        private = _load_private_key(settings.VAPID_PRIVATE_KEY)
    except Exception:
        logger.exception("VAPID_PRIVATE_KEY could not be parsed — push disabled")
        return None

    derived = b64url_encode(public_key_bytes(private.public_key()))
    configured = settings.VAPID_PUBLIC_KEY.strip()
    if configured and b64url_decode(configured) != b64url_decode(derived):
        logger.error(
            "VAPID_PUBLIC_KEY does not match VAPID_PRIVATE_KEY — using the key "
            "derived from the private key. Fix the config: browsers that "
            "subscribed with the mismatched key will never receive a push."
        )
    return private, derived


def reset_keypair_cache() -> None:
    """Drop the cached keypair — for tests that swap the configured keys."""
    _keypair.cache_clear()


def push_enabled() -> bool:
    return _keypair() is not None


def vapid_public_key() -> str | None:
    """The ``applicationServerKey`` the frontend must subscribe with."""
    pair = _keypair()
    return pair[1] if pair else None


def _vapid_headers(endpoint: str) -> dict[str, str]:
    pair = _keypair()
    if pair is None:  # pragma: no cover — callers check push_enabled() first
        raise RuntimeError("VAPID keys are not configured")
    private, public = pair
    parts = urlsplit(endpoint)
    token = jwt.encode(
        {
            # Audience is the push service *origin* only — including the path
            # would leak which endpoint (i.e. which user) is being pushed to.
            "aud": f"{parts.scheme}://{parts.netloc}",
            "exp": int(time.time()) + _VAPID_TTL_SECONDS,
            "sub": settings.VAPID_SUBJECT,
        },
        private,
        algorithm="ES256",
    )
    return {"Authorization": f"vapid t={token},k={public}"}


# ── RFC 8291 message encryption ──────────────────────────────────────────────
def encrypt_payload(
    payload: bytes, p256dh: str, auth: str, *, salt: bytes | None = None,
    server_key: ec.EllipticCurvePrivateKey | None = None,
) -> bytes:
    """Encrypt ``payload`` for one subscription, returning an aes128gcm body.

    ``salt`` and ``server_key`` exist only so tests can pin the randomness and
    check the wire format byte for byte; production always generates fresh ones,
    which RFC 8291 requires (the ephemeral key is what stops two pushes to the
    same browser from sharing a content key).
    """
    ua_public_bytes = b64url_decode(p256dh)
    if len(ua_public_bytes) != _P256_POINT_LEN:
        raise ValueError(
            f"p256dh must be a {_P256_POINT_LEN}-byte uncompressed point, "
            f"got {len(ua_public_bytes)}"
        )
    auth_secret = b64url_decode(auth)

    ua_public = ec.EllipticCurvePublicKey.from_encoded_point(
        ec.SECP256R1(), ua_public_bytes
    )
    server_private = server_key or ec.generate_private_key(ec.SECP256R1())
    as_public_bytes = public_key_bytes(server_private.public_key())
    salt = salt if salt is not None else os.urandom(16)

    shared = server_private.exchange(ec.ECDH(), ua_public)

    # Two-stage HKDF: the auth secret mixes the browser's identity into the
    # input key material, then the per-message salt derives the content key.
    ikm = HKDF(
        algorithm=hashes.SHA256(),
        length=32,
        salt=auth_secret,
        info=_KEY_INFO_PREFIX + ua_public_bytes + as_public_bytes,
    ).derive(shared)
    content_key = HKDF(
        algorithm=hashes.SHA256(), length=16, salt=salt, info=_CEK_INFO
    ).derive(ikm)
    nonce = HKDF(
        algorithm=hashes.SHA256(), length=12, salt=salt, info=_NONCE_INFO
    ).derive(ikm)

    # 0x02 is the padding delimiter marking this as the final record. Anything
    # after it would be zero padding; we send none.
    ciphertext = AESGCM(content_key).encrypt(nonce, payload + b"\x02", None)

    # Header per RFC 8188 §2.1: salt | record size | key id length | key id.
    return (
        salt
        + struct.pack("!I", _RECORD_SIZE)
        + struct.pack("!B", len(as_public_bytes))
        + as_public_bytes
        + ciphertext
    )


# ── Send ─────────────────────────────────────────────────────────────────────
async def send_push(target: PushTarget, payload: dict) -> PushResult:
    """Deliver one notification. Never raises — mirrors send_email/send_sms."""
    if not push_enabled():
        logger.debug("VAPID not configured — skipping push")
        return PushResult(ok=False, error="not_configured")

    try:
        body = encrypt_payload(json.dumps(payload).encode(), target.p256dh, target.auth)
        headers = {
            **_vapid_headers(target.endpoint),
            "Content-Encoding": "aes128gcm",
            "Content-Type": "application/octet-stream",
            "TTL": str(settings.PUSH_TTL_SECONDS),
            # Replace an undelivered alert rather than stacking them up on a
            # phone that has been offline.
            "Urgency": "normal",
        }
    except Exception as exc:
        # A malformed subscription (truncated key, wrong curve) can't be fixed by
        # retrying, so it is reported like a dead endpoint rather than an outage.
        logger.warning("Could not encrypt push for %s: %s", _redact(target.endpoint), exc)
        return PushResult(ok=False, gone=True, error=str(exc))

    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(
                target.endpoint,
                data=body,
                headers=headers,
                timeout=aiohttp.ClientTimeout(total=15),
            ) as resp:
                if resp.status in (200, 201, 202):
                    return PushResult(ok=True, status=resp.status)
                text = (await resp.text())[:200]
                # 404/410 mean the browser is gone for good — the caller deletes
                # the row so a stale subscription isn't retried forever.
                gone = resp.status in (404, 410)
                logger.warning(
                    "Push %d for %s%s: %s",
                    resp.status,
                    _redact(target.endpoint),
                    " (subscription gone)" if gone else "",
                    text,
                )
                return PushResult(ok=False, status=resp.status, gone=gone, error=text)
    except Exception as exc:
        logger.warning("Push request failed for %s: %s", _redact(target.endpoint), exc)
        return PushResult(ok=False, error=str(exc))


def _redact(endpoint: str) -> str:
    """Endpoint URLs are bearer-ish secrets — log the origin, not the path."""
    parts = urlsplit(endpoint)
    return f"{parts.scheme}://{parts.netloc}/…"
