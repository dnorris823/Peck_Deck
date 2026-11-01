import json
import logging
import uuid
from collections.abc import Iterable
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
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
    # TierAttempt dicts in chain order. None for a row queued by an older build.
    tier_trace: list[dict] | None = None
    # [left, top, right, bottom] of the square the tiers classified. None for
    # the full frame, or a row queued by an older build.
    crop_box: list[int] | None = None
    # The animal group, such as "squirrel", for an animal sighting. None for a
    # bird, and for a row queued by an older build.
    animal_group: str | None = None
    # "detector" or "motion". None for a row queued by an older build.
    trigger: str | None = None


class LocalCache:
    """Rolling image cache + persistent offline sighting queue.

    Images live in {cache_dir}/images/.
    The queue is a JSON array at {cache_dir}/queue.json.
    When the image count exceeds max_images, the oldest file is deleted.
    """

    def __init__(self, cache_dir: str, max_images: int = 25, max_queued: int = 200):
        self._root = Path(cache_dir)
        self._images = self._root / "images"
        self._queue_file = self._root / "queue.json"
        self._max = max_images
        self._max_queued = max_queued
        # Sightings lost since this process started, for the heartbeat. A full
        # queue pushing one out counts, and so does ``discard``.
        self.dropped = 0

    def setup(self) -> None:
        self._images.mkdir(parents=True, exist_ok=True)
        if not self._queue_file.exists():
            self._queue_file.write_text("[]", encoding="utf-8")

    def new_event_id(self) -> str:
        return uuid.uuid4().hex

    def image_path_for(self, event_id: str) -> Path:
        return self._images / f"{event_id}.jpg"

    def evict_if_needed(self, protect: Iterable[Path | str] = ()) -> None:
        """Delete the oldest cached image(s) if the cache is over the limit.

        Images still referenced by the offline queue are **never** evicted.
        Deleting one leaves its queued sighting pointing at a missing file, and
        ``Pipeline.sync_offline_queue`` drops those on sight — so an outage
        lasting longer than ``max_images`` captures used to silently destroy
        the very backlog it had just created. The queue is bounded separately,
        by ``max_queued``, so the cache still cannot grow without limit.

        ``protect`` holds the captures waiting for or under classification.
        They are not in the queue yet, so without it an in-flight image is the
        *only* eviction candidate once the queue is full — the classifier then
        reads a file that was deleted a moment earlier and the sighting is lost.
        """
        queued = {Path(r["image_path"]).name for r in self._read()}
        queued.update(Path(p).name for p in protect)
        images = sorted(self._images.glob("*.jpg"), key=lambda p: p.stat().st_mtime)
        excess = len(images) - self._max

        for path in images:
            if excess <= 0:
                break
            if path.name in queued:
                continue
            logger.debug("Evicting cached image: %s", path.name)
            path.unlink(missing_ok=True)
            excess -= 1

        if excess > 0:
            logger.info(
                "Image cache is %d over its limit but every candidate is queued "
                "for upload — keeping them until the backlog drains",
                excess,
            )

    # ── Offline queue ─────────────────────────────────────────────────────────

    def enqueue(self, sighting: QueuedSighting) -> None:
        queue = self._read()
        queue.append(asdict(sighting))

        # Protecting queued images from eviction means the queue itself is the
        # thing that has to be bounded, or a long outage fills the SD card.
        # Dropping data is loud on purpose — it is a real loss of a sighting.
        while len(queue) > self._max_queued:
            dropped = queue.pop(0)
            logger.error(
                "Offline queue is full (%d) — dropping oldest sighting %s from %s",
                self._max_queued, dropped["id"], dropped["timestamp"],
            )
            Path(dropped["image_path"]).unlink(missing_ok=True)
            self.dropped += 1

        self._write(queue)

    def get_pending(self) -> list[QueuedSighting]:
        return [QueuedSighting(**item) for item in self._read()]

    def backlog(self, now: datetime | None = None) -> tuple[int, float | None]:
        """The queue length, and the age in seconds of the oldest queued capture.

        The age is None for an empty queue, or a timestamp that will not parse.
        """
        queue = self._read()
        if not queue:
            return 0, None
        now = now or datetime.now(timezone.utc)
        try:
            oldest = min(datetime.fromisoformat(r["timestamp"]) for r in queue)
        except (KeyError, TypeError, ValueError):
            return len(queue), None
        if oldest.tzinfo is None:
            oldest = oldest.replace(tzinfo=timezone.utc)
        return len(queue), max((now - oldest).total_seconds(), 0.0)

    def discard(self, sighting_id: str) -> None:
        """Remove a queued sighting that will never upload, and count the loss."""
        self.remove(sighting_id)
        self.dropped += 1

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
