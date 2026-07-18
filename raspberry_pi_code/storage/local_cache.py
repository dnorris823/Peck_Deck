import json
import logging
import uuid
from dataclasses import asdict, dataclass
from pathlib import Path

logger = logging.getLogger(__name__)


@dataclass
class QueuedSighting:
    id: str
    timestamp: str       # ISO 8601 UTC
    image_path: str      # absolute path on Pi SD card
    common_name: str
    scientific_name: str
    confidence: float
    tier_used: str


class LocalCache:
    """Rolling image cache + persistent offline sighting queue.

    Images live in {cache_dir}/images/.
    The queue is a JSON array at {cache_dir}/queue.json.
    When the image count exceeds max_images, the oldest file is deleted.
    """

    def __init__(self, cache_dir: str, max_images: int = 25):
        self._root = Path(cache_dir)
        self._images = self._root / "images"
        self._queue_file = self._root / "queue.json"
        self._max = max_images

    def setup(self) -> None:
        self._images.mkdir(parents=True, exist_ok=True)
        if not self._queue_file.exists():
            self._queue_file.write_text("[]", encoding="utf-8")

    def new_event_id(self) -> str:
        return uuid.uuid4().hex

    def image_path_for(self, event_id: str) -> Path:
        return self._images / f"{event_id}.jpg"

    def evict_if_needed(self) -> None:
        """Delete the oldest cached image(s) if the cache is over the limit."""
        imgs = sorted(self._images.glob("*.jpg"), key=lambda p: p.stat().st_mtime)
        while len(imgs) > self._max:
            oldest = imgs.pop(0)
            logger.debug("Evicting cached image: %s", oldest.name)
            oldest.unlink(missing_ok=True)

    # ── Offline queue ─────────────────────────────────────────────────────────

    def enqueue(self, sighting: QueuedSighting) -> None:
        queue = self._read()
        queue.append(asdict(sighting))
        self._write(queue)

    def get_pending(self) -> list[QueuedSighting]:
        return [QueuedSighting(**item) for item in self._read()]

    def remove(self, sighting_id: str) -> None:
        self._write([r for r in self._read() if r["id"] != sighting_id])
        img = self._images / f"{sighting_id}.jpg"
        img.unlink(missing_ok=True)

    def _read(self) -> list[dict]:
        try:
            return json.loads(self._queue_file.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, FileNotFoundError):
            return []

    def _write(self, queue: list[dict]) -> None:
        self._queue_file.write_text(json.dumps(queue, indent=2), encoding="utf-8")
