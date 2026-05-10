import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

_ROOT = Path(__file__).parents[1]


@dataclass
class Config:
    # Backend API
    backend_url: str = os.getenv("BACKEND_URL", "http://192.168.1.100:8000")
    device_token: str = os.getenv("DEVICE_TOKEN", "")

    # GPU inference server (Tier 2)
    inference_server_url: str = os.getenv("INFERENCE_SERVER_URL", "http://192.168.1.100:8001")

    # Classification
    tier_preference: str = os.getenv("TIER_PREFERENCE", "auto")  # local|gpu|cloud|auto
    confidence_threshold: float = float(os.getenv("CONFIDENCE_THRESHOLD", "0.5"))
    tier2_request_timeout: int = int(os.getenv("TIER2_REQUEST_TIMEOUT", "30"))
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
