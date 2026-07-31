import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

_ROOT = Path(__file__).parents[1]

# Escalation thresholds, per tier, from the field measurement in
# machine_learning/MODELS.md. A single 0.5 for all three was a guess, and the
# measurement showed what it cost: 18.2% of the answers Tier 1 accepted at 0.5
# were the wrong species, accepted silently, because a tier that is confidently
# wrong never escalates.
#
# The tiers need different numbers for two independent reasons:
#
#   * Their confidences are not comparable. Tier 2 softmaxes over 10,000 iNat21
#     classes to Tier 1's 965, so it is structurally lower for the same certainty.
#   * Their escalations do not cost the same. Tier 1 escalates to a GPU already
#     running on the LAN (~26 ms, free); Tier 2 escalates to a paid Claude call.
#     So Tier 1 should escalate eagerly and Tier 2 reluctantly.
#
# 0.85 takes Tier 1's silent-error rate from 18.2% to 8.2%. 0.60 holds Tier 2's
# at 3.8%. Tier 3 is last in the chain, so its value only decides whether a weak
# cloud answer is returned outright or as best-effort — 0.5 is kept.
DEFAULT_TIER_THRESHOLDS: dict[str, float] = {
    "local": 0.85,
    "gpu": 0.60,
    "cloud": 0.50,
}


def _opt_float(name: str) -> float | None:
    """Read an optional float. Unset stays None so "set" is distinguishable
    from "set to the same value the default happens to be"."""
    raw = os.getenv(name)
    return float(raw) if raw not in (None, "") else None


@dataclass
class Config:
    # Backend API
    backend_url: str = os.getenv("BACKEND_URL", "http://192.168.1.100:8000")
    device_token: str = os.getenv("DEVICE_TOKEN", "")

    # GPU inference server (Tier 2)
    inference_server_url: str = os.getenv("INFERENCE_SERVER_URL", "http://192.168.1.100:8001")

    # Classification
    tier_preference: str = os.getenv("TIER_PREFERENCE", "auto")  # local|gpu|cloud|auto
    # Per-tier escalation thresholds; None means "use the default for that tier".
    tier1_confidence_threshold: float | None = _opt_float("TIER1_CONFIDENCE_THRESHOLD")
    tier2_confidence_threshold: float | None = _opt_float("TIER2_CONFIDENCE_THRESHOLD")
    tier3_confidence_threshold: float | None = _opt_float("TIER3_CONFIDENCE_THRESHOLD")
    # Legacy single threshold. Still honoured — an operator who set it deliberately
    # should not be overridden by a default — but it now applies only to tiers with
    # no per-tier value, and Pipeline logs a warning when it is in play.
    confidence_threshold: float | None = _opt_float("CONFIDENCE_THRESHOLD")
    tier2_request_timeout: int = int(os.getenv("TIER2_REQUEST_TIMEOUT", "30"))
    # Keep below debounce_seconds: an unreachable backend must not stall the
    # pipeline past the next trigger.
    tier3_request_timeout: int = int(os.getenv("TIER3_REQUEST_TIMEOUT", "25"))
    backend_connect_timeout: int = int(os.getenv("BACKEND_CONNECT_TIMEOUT", "10"))
    backend_upload_timeout: int = int(os.getenv("BACKEND_UPLOAD_TIMEOUT", "60"))

    # Trigger
    trigger_type: str = os.getenv("TRIGGER_TYPE", "pir")  # pir|ir_beam
    trigger_gpio_pin: int = int(os.getenv("TRIGGER_GPIO_PIN", "17"))
    debounce_seconds: float = float(os.getenv("DEBOUNCE_SECONDS", "30"))

    # Camera
    image_width: int = int(os.getenv("IMAGE_WIDTH", "1920"))
    image_height: int = int(os.getenv("IMAGE_HEIGHT", "1080"))
    jpeg_quality: int = int(os.getenv("JPEG_QUALITY", "90"))

    # Storage
    cache_dir: str = os.getenv("CACHE_DIR", "/var/lib/peck_deck/cache")
    max_cache_images: int = int(os.getenv("MAX_CACHE_IMAGES", "25"))
    # Queued sightings are protected from image eviction, so this — not
    # max_cache_images — is what bounds the cache during a long outage.
    max_queued_sightings: int = int(os.getenv("MAX_QUEUED_SIGHTINGS", "200"))

    # ML models (default: relative to project root)
    model_path: str = os.getenv(
        "MODEL_PATH",
        str(_ROOT / "machine_learning" / "INatVision_Small_2_fact256_8bit.tflite"),
    )
    taxonomy_path: str = os.getenv(
        "TAXONOMY_PATH",
        str(_ROOT / "machine_learning" / "taxonomy.csv"),
    )

    # Background sync
    sync_interval_seconds: int = int(os.getenv("SYNC_INTERVAL_SECONDS", "60"))

    def threshold_for(self, tier_name: str) -> float:
        """The confidence a given tier must reach to win outright.

        Precedence: that tier's own setting, then the legacy global, then the
        measured default. Explicit configuration always beats a default — a
        deployment that pinned CONFIDENCE_THRESHOLD did so for a reason, and
        silently ignoring it would be the worse surprise.
        """
        explicit = {
            "local": self.tier1_confidence_threshold,
            "gpu": self.tier2_confidence_threshold,
            "cloud": self.tier3_confidence_threshold,
        }.get(tier_name)
        if explicit is not None:
            return explicit
        if self.confidence_threshold is not None:
            return self.confidence_threshold
        return DEFAULT_TIER_THRESHOLDS.get(tier_name, 0.5)

    def uses_legacy_global_threshold(self) -> bool:
        """True when CONFIDENCE_THRESHOLD is displacing a measured default."""
        if self.confidence_threshold is None:
            return False
        return any(
            getattr(self, f"tier{i}_confidence_threshold") is None for i in (1, 2, 3)
        )
