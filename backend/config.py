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
    # 30 days. The installed app opens from a push notification with no chance
    # to sign in first, so a 24-hour token sent most taps to the login screen.
    # Revocation goes through User.token_version, not expiry (auth/guards.py).
    JWT_EXPIRE_HOURS: int = int(os.getenv("JWT_EXPIRE_HOURS", "720"))

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

    # ── Tier 2 re-check ───────────────────────────────────────────────────────
    # The inference server on this PC. The API runs in Docker and the server
    # runs bare metal, so the default reaches the host from the container.
    # See backend/sightings/recheck.py.
    INFERENCE_SERVER_URL: str = os.getenv(
        "INFERENCE_SERVER_URL", "http://host.docker.internal:8001"
    )
    # How often the re-check asks whether the server is back, while sightings
    # wait for it. 0 turns the re-check off.
    TIER2_RECHECK_INTERVAL_SECONDS: int = int(
        os.getenv("TIER2_RECHECK_INTERVAL_SECONDS", "60")
    )
    # The re-check takes Tier 2's animal when it meets this bar and beats the
    # bird, the same rule and default as the Pi's TIER2_ANIMAL_THRESHOLD. Keep
    # the two equal, or a squirrel caught live and one re-checked later get
    # different answers. See machine_learning/MODELS.md for the measurement.
    TIER2_ANIMAL_THRESHOLD: float = float(os.getenv("TIER2_ANIMAL_THRESHOLD", "0.30"))

    # ── Feed alerts ───────────────────────────────────────────────────────────
    # The hourly check that tells a feeder's owner when its feed is low or out.
    # "false" turns it off. See backend/feed/monitor.py.
    FEED_ALERTS_ENABLED: bool = os.getenv("FEED_ALERTS_ENABLED", "true").lower() == "true"

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

    # ── Weather on sightings ──────────────────────────────────────────────────
    # Looks up the weather at the device's city from Open-Meteo after each
    # upload. "false" turns it off, such as on a backend with no internet.
    WEATHER_ENABLED: bool = os.getenv("WEATHER_ENABLED", "true").lower() == "true"

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
