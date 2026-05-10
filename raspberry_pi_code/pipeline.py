import asyncio
import logging
from datetime import datetime, timezone
from pathlib import Path

from .api_client import BackendClient
from .camera.pi_camera import PiCamera
from .classification.base import ClassificationResult, ClassifierBase
from .classification.tier1_tflite import TFLiteClassifier
from .classification.tier2_gpu import GPUServerClassifier
from .classification.tier3_cloud import CloudClassifier
from .config import Config
from .storage.local_cache import LocalCache, QueuedSighting

logger = logging.getLogger(__name__)


class Pipeline:
    """Orchestrates trigger → capture → classify → upload/queue for each bird visit."""

    def __init__(self, config: Config):
        self._cfg = config
        self._cache = LocalCache(config.cache_dir, config.max_cache_images)
        self._client = BackendClient(
            config.backend_url,
            config.device_token,
            config.backend_connect_timeout,
            config.backend_upload_timeout,
        )
        self._tier1 = TFLiteClassifier(config.model_path, config.taxonomy_path)
        self._tier2 = GPUServerClassifier(config.inference_server_url, config.tier2_request_timeout)
        self._tier3 = CloudClassifier(config.backend_url, config.device_token)

        self._last_capture: float = 0.0
        self._capture_lock = asyncio.Lock()

    def setup(self) -> None:
        self._cache.setup()
        if not self._tier1.load():
            logger.warning("Tier 1 classifier unavailable — will fall through to Tier 2/3")

    # ── Public API ────────────────────────────────────────────────────────────

    async def handle_trigger(self) -> None:
        if self._capture_lock.locked():
            logger.debug("Capture already in progress — skipping trigger")
            return

        async with self._capture_lock:
            now = asyncio.get_running_loop().time()
            if now - self._last_capture < self._cfg.debounce_seconds:
                logger.debug("Debounce active — skipping trigger")
                return
            self._last_capture = now
            await self._capture_and_process()

    async def sync_offline_queue(self) -> None:
        """Flush queued sightings to the backend when connectivity is restored."""
        pending = self._cache.get_pending()
        if not pending:
            return

        if not await self._client.is_reachable():
            return

        logger.info("Syncing %d queued sighting(s)", len(pending))
        for sighting in pending:
            img = Path(sighting.image_path)
            if not img.exists():
                logger.warning("Queued image missing (%s) — dropping", img.name)
                self._cache.remove(sighting.id)
                continue

            ok = await self._client.post_sighting(
                image_path=img,
                timestamp=sighting.timestamp,
                common_name=sighting.common_name,
                scientific_name=sighting.scientific_name,
                confidence=sighting.confidence,
                tier_used=sighting.tier_used,
                delayed=True,
            )
            if ok:
                self._cache.remove(sighting.id)
            else:
                logger.warning("Sync failed for sighting %s — will retry next cycle", sighting.id)

    # ── Internal ──────────────────────────────────────────────────────────────

    async def _capture_and_process(self) -> None:
        event_id = self._cache.new_event_id()
        timestamp = datetime.now(timezone.utc).isoformat()

        async with PiCamera(self._cfg.image_width, self._cfg.image_height, self._cfg.jpeg_quality) as cam:
            image_path = await cam.capture(self._cache.image_path_for(event_id))

        self._cache.evict_if_needed()

        result = await self._classify(image_path)
        if result is None:
            logger.error("All classifiers failed for event %s — sighting discarded", event_id)
            return

        logger.info(
            "Classified: %s (%.0f%%) [tier=%s]",
            result.common_name,
            result.confidence * 100,
            result.tier_used,
        )

        ok = await self._client.post_sighting(
            image_path=image_path,
            timestamp=timestamp,
            common_name=result.common_name,
            scientific_name=result.scientific_name,
            confidence=result.confidence,
            tier_used=result.tier_used,
            delayed=False,
        )

        if not ok:
            logger.warning("Backend unreachable — queuing sighting locally")
            self._cache.enqueue(
                QueuedSighting(
                    id=event_id,
                    timestamp=timestamp,
                    image_path=str(image_path),
                    common_name=result.common_name,
                    scientific_name=result.scientific_name,
                    confidence=result.confidence,
                    tier_used=result.tier_used,
                )
            )

    def _classifiers_for_preference(self) -> list[ClassifierBase]:
        pref = self._cfg.tier_preference
        if pref == "local":
            return [self._tier1]
        if pref == "gpu":
            return [self._tier2, self._tier1]
        if pref == "cloud":
            return [self._tier3, self._tier2, self._tier1]
        return [self._tier1, self._tier2, self._tier3]

    async def _classify(self, image_path: Path) -> ClassificationResult | None:
        for clf in self._classifiers_for_preference():
            result = await clf.classify(image_path)
            if result is not None:
                return result
            logger.warning("Tier '%s' failed — trying next", clf.tier_name)
        return None
