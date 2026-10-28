import math
import os
from dataclasses import dataclass, field
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


FULL_FRAME: tuple[float, float, float, float] = (0.0, 0.0, 1.0, 1.0)


def parse_roi(raw: str | None) -> tuple[float, float, float, float]:
    """Parse CAMERA_ROI: "x,y,width,height" as fractions of the frame.

    Unset or empty means the full frame. Anything else that does not describe
    a region inside the frame raises ValueError, so the Pi refuses to start
    rather than watch the wrong part of the picture.
    """
    if raw is None or raw.strip() == "":
        return FULL_FRAME
    parts = raw.split(",")
    try:
        x, y, w, h = (float(p) for p in parts)
    except ValueError:
        raise ValueError(
            f"CAMERA_ROI must be four numbers x,y,width,height, got {raw!r}"
        ) from None
    if not all(math.isfinite(v) for v in (x, y, w, h)):
        raise ValueError(f"CAMERA_ROI must be finite numbers, got {raw!r}")
    if x < 0 or y < 0 or w <= 0 or h <= 0:
        raise ValueError(
            f"CAMERA_ROI needs x and y of 0 or more and a width and height above 0, "
            f"got {raw!r}"
        )
    # A small tolerance, so "0.3,0.2,0.7,0.8" is not refused for float rounding.
    if x + w > 1 + 1e-9 or y + h > 1 + 1e-9:
        raise ValueError(f"CAMERA_ROI must lie inside the frame (x+width and "
                         f"y+height at most 1), got {raw!r}")
    return (x, y, w, h)


@dataclass
class Config:
    # Backend API
    backend_url: str = os.getenv("BACKEND_URL", "http://192.168.1.100:8000")
    device_token: str = os.getenv("DEVICE_TOKEN", "")

    # GPU inference server (Tier 2)
    inference_server_url: str = os.getenv("INFERENCE_SERVER_URL", "http://192.168.1.100:8001")

    # Classification
    tier_preference: str = os.getenv("TIER_PREFERENCE", "gpu")  # gpu|auto|cloud|local
    # Per-tier escalation thresholds; None means "use the default for that tier".
    tier1_confidence_threshold: float | None = _opt_float("TIER1_CONFIDENCE_THRESHOLD")
    tier2_confidence_threshold: float | None = _opt_float("TIER2_CONFIDENCE_THRESHOLD")
    tier3_confidence_threshold: float | None = _opt_float("TIER3_CONFIDENCE_THRESHOLD")
    # Tier 2 is on the LAN and a healthy GPU answers in well under a second.
    # Past 5 s it is down, and Tier 1 should answer instead.
    tier2_request_timeout: int = int(os.getenv("TIER2_REQUEST_TIMEOUT", "5"))
    # Every capture waiting in the classify queue waits this long behind an
    # unreachable backend, so keep it short.
    tier3_request_timeout: int = int(os.getenv("TIER3_REQUEST_TIMEOUT", "25"))
    backend_connect_timeout: int = int(os.getenv("BACKEND_CONNECT_TIMEOUT", "10"))
    backend_upload_timeout: int = int(os.getenv("BACKEND_UPLOAD_TIMEOUT", "60"))

    # Trigger
    # The only trigger is "camera". Any other value refuses to start.
    trigger_type: str = os.getenv("TRIGGER_TYPE", "camera")
    debounce_seconds: float = float(os.getenv("DEBOUNCE_SECONDS", "30"))

    # Camera trigger only. It replaces DEBOUNCE_SECONDS with the visit gap.
    # Fraction of lores pixels (0 to 1) that must change before the detector runs.
    camera_motion_threshold: float = float(os.getenv("CAMERA_MOTION_THRESHOLD", "0.01"))
    # Detector score for "bird". See machine_learning/MODELS.md for the measurement.
    camera_detection_threshold: float = float(os.getenv("CAMERA_DETECTION_THRESHOLD", "0.5"))
    # One visit = the first bird detection after this many seconds with no bird.
    camera_visit_gap_seconds: float = float(os.getenv("CAMERA_VISIT_GAP_SECONDS", "15"))
    # Analysis ticks per second. The motion check runs on every tick.
    camera_analysis_fps: float = float(os.getenv("CAMERA_ANALYSIS_FPS", "5"))
    # The feeder's region, as fractions of the frame. The detector and the motion
    # check see only this crop. Parsed when Config() is built, so a bad value
    # stops the service at start.
    camera_roi: tuple[float, float, float, float] = field(
        default_factory=lambda: parse_roi(os.getenv("CAMERA_ROI"))
    )
    # TFLite interpreter threads for the bird detector. The Pi 5 has four cores.
    detector_threads: int = int(os.getenv("DETECTOR_THREADS", "4"))

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
    # Captures waiting for classify and upload. Past this, a new capture goes to
    # the offline queue unclassified. Waiting images are kept from eviction too.
    classify_queue_size: int = int(os.getenv("CLASSIFY_QUEUE_SIZE", "4"))

    # ML models (default: relative to project root). scripts/fetch_models.py
    # writes the Tier 1 model to this default path.
    model_path: str = os.getenv(
        "MODEL_PATH",
        str(_ROOT / "machine_learning" / "aiy_birds_V1_224_uint8.tflite"),
    )
    taxonomy_path: str = os.getenv(
        "TAXONOMY_PATH",
        str(_ROOT / "machine_learning" / "taxonomy.csv"),
    )
    # COCO bird detector for the camera trigger. scripts/fetch_models.py writes it.
    detector_model_path: str = os.getenv(
        "DETECTOR_MODEL_PATH",
        str(_ROOT / "machine_learning" / "efficientdet_lite0_detection.tflite"),
    )

    # Background sync
    sync_interval_seconds: int = int(os.getenv("SYNC_INTERVAL_SECONDS", "60"))

    def threshold_for(self, tier_name: str) -> float:
        """The confidence a given tier must reach to win outright.

        That tier's own setting wins, then the measured default.
        """
        explicit = {
            "local": self.tier1_confidence_threshold,
            "gpu": self.tier2_confidence_threshold,
            "cloud": self.tier3_confidence_threshold,
        }.get(tier_name)
        if explicit is not None:
            return explicit
        return DEFAULT_TIER_THRESHOLDS.get(tier_name, 0.5)

