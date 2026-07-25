import os
from dataclasses import dataclass

from dotenv import load_dotenv

load_dotenv()


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

    # ── Environment ───────────────────────────────────────────────────────────
    # "development" | "production". Production refuses to start on insecure
    # defaults (see backend/main.py).
    ENVIRONMENT: str = os.getenv("ENVIRONMENT", "development")

    # ── Demo mode (FLEDGE Phase 5) ────────────────────────────────────────────
    # When on, the app seeds the demo dataset at boot if the database is empty
    # and refuses every user-authenticated write, so a public/shared instance
    # can be clicked through without being edited. Device writes (the Pi and the
    # simulator) still work — that's what keeps the demo *live* rather than a
    # frozen snapshot. Advertised to the frontend via GET /meta.
    DEMO_MODE: bool = os.getenv("DEMO_MODE", "").strip().lower() in {"1", "true", "yes", "on"}

    # ── Email (SendGrid) ──────────────────────────────────────────────────────
    SENDGRID_API_KEY: str = os.getenv("SENDGRID_API_KEY", "")
    NOTIFICATION_FROM_EMAIL: str = os.getenv(
        "NOTIFICATION_FROM_EMAIL", "notifications@peckdeck.local"
    )

    # ── SMS (Twilio) ──────────────────────────────────────────────────────────
    TWILIO_ACCOUNT_SID: str = os.getenv("TWILIO_ACCOUNT_SID", "")
    TWILIO_AUTH_TOKEN: str = os.getenv("TWILIO_AUTH_TOKEN", "")
    TWILIO_FROM_NUMBER: str = os.getenv("TWILIO_FROM_NUMBER", "")

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

    # ── Cloud classification (Tier 3 — Claude API, M6) ────────────────────────
    ANTHROPIC_API_KEY: str = os.getenv("ANTHROPIC_API_KEY", "")
    ANTHROPIC_MODEL: str = os.getenv("ANTHROPIC_MODEL", "claude-opus-4-8")


settings = Settings()
