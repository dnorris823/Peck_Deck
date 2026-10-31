import os
from dataclasses import dataclass

from dotenv import load_dotenv

load_dotenv()

# Read once at module scope.
_ENVIRONMENT = os.getenv("ENVIRONMENT", "development")


@dataclass
class Settings:
    # ── Database ──────────────────────────────────────────────────────────────
    DATABASE_URL: str = os.getenv(
        "DATABASE_URL",
        "postgresql+asyncpg://peck_deck:changeme@localhost:5432/peck_deck",
    )

    # ── Auth ──────────────────────────────────────────────────────────────────
    JWT_SECRET: str = os.getenv("JWT_SECRET", "change_this_in_production")
    JWT_ALGORITHM: str = "HS256"
    JWT_EXPIRE_HOURS: int = int(os.getenv("JWT_EXPIRE_HOURS", "24"))

    # ── CORS ──────────────────────────────────────────────────────────────────
    # Comma-separated origins allowed to call the API from a browser. Defaults
    # to the Vite dev server. Credentials are sent, so "*" is NOT permitted —
    # a wildcard plus credentials would let any site drive the API as the
    # logged-in user.
    CORS_ALLOW_ORIGINS: str = os.getenv(
        "CORS_ALLOW_ORIGINS", "http://localhost:5173,http://127.0.0.1:5173"
    )

    # ── Upload limits ─────────────────────────────────────────────────────────
    # Cap on a single sighting upload. The Pi sends ~300 KB JPEGs at 1920x1080;
    # 15 MB leaves headroom for full 4608x2592 frames while stopping an
    # unbounded body from exhausting memory (images are buffered as bytea).
    MAX_UPLOAD_BYTES: int = int(os.getenv("MAX_UPLOAD_BYTES", str(15 * 1024 * 1024)))

    # ── Retention ─────────────────────────────────────────────────────────────
    # Delete "Unknown" sightings older than this many days, once a day. 0 turns
    # the rule off, and 0 is the default. See backend/retention.py.
    RETENTION_UNKNOWN_DAYS: int = int(os.getenv("RETENTION_UNKNOWN_DAYS", "0"))

    # ── Environment ───────────────────────────────────────────────────────────
    # "development" | "production". Production refuses to start on insecure
    # defaults (see backend/main.py).
    ENVIRONMENT: str = _ENVIRONMENT

    # ── Email (SendGrid) ──────────────────────────────────────────────────────
    SENDGRID_API_KEY: str = os.getenv("SENDGRID_API_KEY", "")
    NOTIFICATION_FROM_EMAIL: str = os.getenv(
        "NOTIFICATION_FROM_EMAIL", "notifications@peckdeck.local"
    )

    # ── Notifications ─────────────────────────────────────────────────────────
    NOTIFICATION_MIN_INTERVAL_SECONDS: int = int(
        os.getenv("NOTIFICATION_MIN_INTERVAL_SECONDS", "60")
    )

    # ── Web push (FLEDGE Phase 7) ─────────────────────────────────────────────
    # VAPID identifies *this server* to the browser's push service (RFC 8292).
    # The private key is base64url-encoded raw 32 bytes (what `web-push
    # generate-vapid-keys` emits) or a PEM block; generate a pair with
    # `python scripts/generate_vapid_keys.py`. The public key the browser
    # subscribes with is derived from the private key, so it can never drift —
    # VAPID_PUBLIC_KEY is only cross-checked, never trusted over the derivation.
    # With no private key configured, push is simply off: subscriptions are
    # still accepted, nothing is sent.
    VAPID_PRIVATE_KEY: str = os.getenv("VAPID_PRIVATE_KEY", "")
    VAPID_PUBLIC_KEY: str = os.getenv("VAPID_PUBLIC_KEY", "")
    # Contact for the push service operator to reach if this server misbehaves.
    # Must be a mailto: or https: URL.
    VAPID_SUBJECT: str = os.getenv("VAPID_SUBJECT", "mailto:admin@peckdeck.local")
    # How long a push service should hold an undelivered message, in seconds.
    PUSH_TTL_SECONDS: int = int(os.getenv("PUSH_TTL_SECONDS", "86400"))

    # ── Live video (WHEP relay) ───────────────────────────────────────────────
    # The read user in the Pi's MediaMTX config. The backend sends these as
    # Basic auth when it relays a browser's offer. The browser never sees them.
    # Empty means MediaMTX takes unauthenticated reads. See docs/live-video.md.
    LIVE_READ_USER: str = os.getenv("LIVE_READ_USER", "")
    LIVE_READ_PASSWORD: str = os.getenv("LIVE_READ_PASSWORD", "")
    # MediaMTX's HLS port on the Pi. The relay takes the host from the stored
    # live_url and swaps in this port.
    LIVE_HLS_PORT: int = int(os.getenv("LIVE_HLS_PORT", "8888"))

    # ── Cloud classification (Tier 3 — Claude API, M6) ────────────────────────
    ANTHROPIC_API_KEY: str = os.getenv("ANTHROPIC_API_KEY", "")
    ANTHROPIC_MODEL: str = os.getenv("ANTHROPIC_MODEL", "claude-opus-4-8")


settings = Settings()
