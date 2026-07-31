import asyncio
import logging
from datetime import datetime, timezone
from pathlib import Path

from .api_client import BackendClient, UploadOutcome
from .camera.pi_camera import PiCamera
from .classification.base import ClassificationResult, ClassifierBase
from .classification.tier1_tflite import TFLiteClassifier
from .classification.tier2_gpu import GPUServerClassifier
from .classification.tier3_cloud import CloudClassifier
from .config import DEFAULT_TIER_THRESHOLDS, Config
from .storage.local_cache import LocalCache, QueuedSighting

logger = logging.getLogger(__name__)


class Pipeline:
    """Orchestrates trigger → capture → classify → upload/queue for each bird visit."""

    def __init__(self, config: Config):
        self._cfg = config
        self._cache = LocalCache(
            config.cache_dir, config.max_cache_images, config.max_queued_sightings
        )
        self._client = BackendClient(
            config.backend_url,
            config.device_token,
            config.backend_connect_timeout,
            config.backend_upload_timeout,
        )
        self._tier1 = TFLiteClassifier(config.model_path, config.taxonomy_path)
        self._tier2 = GPUServerClassifier(config.inference_server_url, config.tier2_request_timeout)
        self._tier3 = CloudClassifier(
            config.backend_url, config.device_token, config.tier3_request_timeout
        )

        self._last_capture: float = 0.0
        self._capture_lock = asyncio.Lock()

    def setup(self) -> None:
        self._cache.setup()
        if not self._tier1.load():
            logger.warning("Tier 1 classifier unavailable — will fall through to Tier 2/3")

        # Log what the chain will actually enforce. The thresholds decide which
        # answers reach the user unchallenged, and until now nothing said out
        # loud what they were.
        logger.info(
            "Escalation thresholds: local=%.2f gpu=%.2f cloud=%.2f",
            *(self._cfg.threshold_for(t) for t in ("local", "gpu", "cloud")),
        )
        if self._cfg.uses_legacy_global_threshold():
            logger.warning(
                "CONFIDENCE_THRESHOLD=%.2f is set and is overriding the measured "
                "per-tier defaults %s. At 0.5, 18.2%% of the answers Tier 1 accepts "
                "are the wrong species, and they never escalate. Prefer "
                "TIER1_/TIER2_/TIER3_CONFIDENCE_THRESHOLD; see "
                "machine_learning/MODELS.md.",
                self._cfg.confidence_threshold,
                DEFAULT_TIER_THRESHOLDS,
            )

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

            outcome = await self._client.post_sighting(
                image_path=img,
                timestamp=sighting.timestamp,
                common_name=sighting.common_name,
                scientific_name=sighting.scientific_name,
                confidence=sighting.confidence,
                tier_used=sighting.tier_used,
                delayed=True,
            )
            if outcome is UploadOutcome.OK:
                self._cache.remove(sighting.id)
            elif outcome is UploadOutcome.REJECTED:
                logger.error(
                    "Backend permanently rejected queued sighting %s — dropping it "
                    "rather than retrying forever",
                    sighting.id,
                )
                self._cache.remove(sighting.id)
            elif outcome is UploadOutcome.UNAUTHORIZED:
                # Every remaining item carries the same token, so the rest of
                # this pass would just be 401s. Stop and keep the backlog.
                logger.error(
                    "Device token rejected — abandoning this sync pass with %d "
                    "sighting(s) still queued",
                    len(pending),
                )
                return
            else:
                logger.warning("Sync failed for sighting %s — will retry next cycle", sighting.id)

    # ── Internal ──────────────────────────────────────────────────────────────

    async def _capture_and_process(self) -> None:
        event_id = self._cache.new_event_id()
        timestamp = datetime.now(timezone.utc).isoformat()

        async with PiCamera(self._cfg.image_width, self._cfg.image_height, self._cfg.jpeg_quality) as cam:
            image_path = await cam.capture(self._cache.image_path_for(event_id))

        self._cache.evict_if_needed(protect=image_path)

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

        outcome = await self._client.post_sighting(
            image_path=image_path,
            timestamp=timestamp,
            common_name=result.common_name,
            scientific_name=result.scientific_name,
            confidence=result.confidence,
            tier_used=result.tier_used,
            delayed=False,
        )

        if outcome is UploadOutcome.REJECTED:
            logger.error(
                "Backend rejected sighting %s outright — discarding (retrying cannot help)",
                event_id,
            )
            return

        if outcome is not UploadOutcome.OK:
            if outcome is UploadOutcome.UNAUTHORIZED:
                logger.error("Device token rejected — queuing sighting, but it cannot "
                             "upload until DEVICE_TOKEN is re-provisioned")
            else:
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
        """Walk the tier chain, falling through on failure *or* low confidence.

        A tier that answers below **its own** threshold doesn't win outright —
        the next tier gets a shot. The best low-confidence answer is kept as a
        fallback so a weak guess still beats discarding the sighting entirely.

        Thresholds are per tier (see ``DEFAULT_TIER_THRESHOLDS``) because a raw
        confidence means different things coming from different tiers.
        """
        best: ClassificationResult | None = None
        best_ratio = 0.0

        for clf in self._classifiers_for_preference():
            result = await clf.classify(image_path)

            if result is None:
                logger.warning("Tier '%s' failed — trying next", clf.tier_name)
                continue

            threshold = self._cfg.threshold_for(clf.tier_name)
            if result.confidence >= threshold:
                return result

            logger.info(
                "Tier '%s' confidence %.2f below its threshold %.2f — trying next",
                clf.tier_name,
                result.confidence,
                threshold,
            )
            # Rank leftovers by how close each came to *its own* bar, not by raw
            # confidence. Comparing raw numbers across tiers is what per-tier
            # thresholds exist to stop: 0.55 from Tier 2 (bar 0.60) is a stronger
            # answer than 0.60 from Tier 1 (bar 0.85), and Tier 2 is the more
            # accurate tier besides.
            ratio = result.confidence / threshold if threshold > 0 else float("inf")
            if best is None or ratio > best_ratio:
                best, best_ratio = result, ratio

        if best is not None:
            logger.warning(
                "No tier met its confidence threshold — using best effort: %s (%.2f, "
                "%.0f%% of its tier's bar) [tier=%s]",
                best.common_name,
                best.confidence,
                100 * best_ratio,
                best.tier_used,
            )
        return best
