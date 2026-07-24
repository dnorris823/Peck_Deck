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

    # ── Cloud classification (Tier 3 — Claude API, M6) ────────────────────────
    ANTHROPIC_API_KEY: str = os.getenv("ANTHROPIC_API_KEY", "")
    ANTHROPIC_MODEL: str = os.getenv("ANTHROPIC_MODEL", "claude-opus-4-8")


settings = Settings()
