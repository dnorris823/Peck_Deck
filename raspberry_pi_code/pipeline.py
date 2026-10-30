import asyncio
import logging
from dataclasses import asdict, dataclass, replace
from datetime import datetime, timezone
from pathlib import Path

from .api_client import BackendClient, UploadOutcome
from .bird_crop import Box, write_crop
from .camera.base import CameraBase
from .camera.pi_camera import PiCamera
from .classification.base import ClassificationResult, ClassifierBase, TierAttempt
from .classification.tier1_tflite import TFLiteClassifier
from .classification.tier2_gpu import GPUServerClassifier
from .classification.tier3_cloud import CloudClassifier
from .config import Config
from .storage.local_cache import LocalCache, QueuedSighting

logger = logging.getLogger(__name__)

# What a capture carries when every tier in the chain failed. The backend files
# it under an "Unknown" species, which is also what Tier 3 returns for no bird.
_UNCLASSIFIED = ClassificationResult(
    common_name="Unknown",
    scientific_name="",
    confidence=0.0,
    tier_used="none",
)

TIER_PREFERENCES = ("gpu", "auto", "cloud", "local")


@dataclass(frozen=True)
class Capture:
    """A photo taken for one visit, waiting for classify and upload."""

    event_id: str
    timestamp: str  # ISO 8601 UTC, when the photo was taken
    image_path: Path
    # The trigger's bird box, in fractions of the frame. The classifiers see a
    # crop around it. The sighting keeps the full frame.
    box: Box | None = None


class Pipeline:
    """Orchestrates trigger → capture → classify → upload/queue for each bird visit."""

    def __init__(
        self,
        config: Config,
        camera: CameraBase | None = None,
    ):
        """
        ``camera`` is the long-lived camera that ``main.py`` opens and shares
        with the trigger. Without one, each capture opens its own camera.

        The pipeline has no repeat rule. The camera trigger's visit gap decides
        what counts as a new visit.
        """
        # An unknown value refuses to start. It used to fall through to the
        # "auto" order, so a typo turned on paid Tier 3 calls.
        if config.tier_preference not in TIER_PREFERENCES:
            raise ValueError(
                f"Unknown TIER_PREFERENCE {config.tier_preference!r}. "
                f"Expected one of: {', '.join(TIER_PREFERENCES)}"
            )
        self._cfg = config
        self._camera = camera
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

        # Covers the camera only. Classify and upload run in run_classifier, so
        # a slow Tier 2 delays the answer but never costs the next visit its photo.
        self._capture_lock = asyncio.Lock()
        self._work: asyncio.Queue[Capture] = asyncio.Queue(config.classify_queue_size)
        # Captures waiting in _work or under classification. They are not in the
        # offline queue yet, so eviction has to be told to keep them.
        self._in_flight: set[Path] = set()

    def setup(self) -> None:
        self._cache.setup()
        if not self._tier1.load():
            logger.warning(
                "Tier 1 classifier unavailable. The chain skips it (TIER_PREFERENCE=%s)",
                self._cfg.tier_preference,
            )

        # Log what the chain will actually enforce. The thresholds decide which
        # answers reach the user unchallenged, and until now nothing said out
        # loud what they were.
        logger.info(
            "Escalation thresholds: local=%.2f gpu=%.2f cloud=%.2f",
            *(self._cfg.threshold_for(t) for t in ("local", "gpu", "cloud")),
        )

    # ── Public API ────────────────────────────────────────────────────────────

    async def handle_trigger(self, box: Box | None = None) -> None:
        """Take the photo for one visit and hand it to ``run_classifier``.

        ``box`` is where the trigger saw the bird, from ``TriggerEvent.box``.

        A trigger that fires during another capture waits for the camera. It
        used to be skipped, and the old lock covered classify and upload too, so
        an unreachable Tier 2 dropped every visit for 40 s at a time.
        """
        async with self._capture_lock:
            capture = await self._capture()
        self._submit(replace(capture, box=box))

    async def run_classifier(self) -> None:
        """Classify and upload captures one at a time, in visit order. Runs forever.

        One worker keeps Tier 2 to one request at a time, and keeps sightings
        reaching the backend in the order the birds came.
        """
        while True:
            capture = await self._work.get()
            try:
                await self._process(capture)
            except Exception:
                logger.exception("Processing failed for event %s", capture.event_id)
            finally:
                self._in_flight.discard(capture.image_path)
                self._work.task_done()

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
                tier_trace=sighting.tier_trace,
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

    async def _capture(self) -> Capture:
        event_id = self._cache.new_event_id()
        timestamp = datetime.now(timezone.utc).isoformat()

        target = self._cache.image_path_for(event_id)
        if self._camera is not None:
            image_path = await self._camera.capture(target)
        else:
            async with PiCamera(
                self._cfg.image_width, self._cfg.image_height, self._cfg.jpeg_quality
            ) as cam:
                image_path = await cam.capture(target)

        self._in_flight.add(image_path)
        self._cache.evict_if_needed(protect=self._in_flight)
        return Capture(event_id, timestamp, image_path)

    def _submit(self, capture: Capture) -> None:
        """Queue a capture for ``run_classifier``. A full queue keeps the photo."""
        try:
            self._work.put_nowait(capture)
            return
        except asyncio.QueueFull:
            pass

        # The worker is far behind, most likely on Tier 2 timeouts. Put the
        # photo in the offline queue unclassified rather than lose the visit.
        # The sync loop uploads it as "Unknown".
        logger.warning(
            "Classify queue is full (%d waiting). Sending event %s to the offline "
            "queue unclassified",
            self._work.qsize(),
            capture.event_id,
        )
        trace = self._not_run(self._classifiers_for_preference())
        self._enqueue_offline(capture, _UNCLASSIFIED, trace)
        self._in_flight.discard(capture.image_path)

    async def _process(self, capture: Capture) -> None:
        event_id = capture.event_id
        image_path = capture.image_path

        crop_path = await self._crop_for_classifiers(capture)
        try:
            result, trace = await self._classify(crop_path or image_path)
        finally:
            if crop_path is not None:
                crop_path.unlink(missing_ok=True)
        if result is None:
            # The trigger already decided this is a visit, so keep it. A tier
            # outage must not lose sightings. It uploads, or queues, as "Unknown".
            logger.error(
                "All classifiers failed for event %s. Uploading it with no species",
                event_id,
            )
            result = _UNCLASSIFIED

        logger.info(
            "Classified: %s (%.0f%%) [tier=%s]",
            result.common_name,
            result.confidence * 100,
            result.tier_used,
        )

        outcome = await self._client.post_sighting(
            image_path=image_path,
            timestamp=capture.timestamp,
            common_name=result.common_name,
            scientific_name=result.scientific_name,
            confidence=result.confidence,
            tier_used=result.tier_used,
            tier_trace=_trace_json(trace),
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
            self._enqueue_offline(capture, result, trace)

    async def _crop_for_classifiers(self, capture: Capture) -> Path | None:
        """Write the crop around the bird box. None means classify the full frame.

        The crop lives outside the image cache, so eviction never counts it,
        and ``_process`` deletes it after classification.
        """
        if capture.box is None:
            return None
        crop_path = Path(self._cfg.cache_dir) / "crops" / f"{capture.event_id}.jpg"
        try:
            size = await asyncio.to_thread(
                write_crop,
                capture.image_path,
                crop_path,
                capture.box,
                self._cfg.classify_crop_margin,
                self._cfg.jpeg_quality,
            )
        except Exception:
            logger.exception(
                "Could not crop event %s to the bird box. Classifying the full frame",
                capture.event_id,
            )
            return None
        logger.info("Classifying a %dx%d crop around the bird box", *size)
        return crop_path

    def _enqueue_offline(
        self, capture: Capture, result: ClassificationResult, trace: list[TierAttempt]
    ) -> None:
        self._cache.enqueue(
            QueuedSighting(
                id=capture.event_id,
                timestamp=capture.timestamp,
                image_path=str(capture.image_path),
                common_name=result.common_name,
                scientific_name=result.scientific_name,
                confidence=result.confidence,
                tier_used=result.tier_used,
                tier_trace=_trace_json(trace),
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
        # "auto". __init__ has already refused anything else.
        return [self._tier1, self._tier2, self._tier3]

    def _not_run(self, classifiers: list[ClassifierBase]) -> list[TierAttempt]:
        return [
            TierAttempt(clf.tier_name, "not_run", None, self._cfg.threshold_for(clf.tier_name))
            for clf in classifiers
        ]

    async def _classify(
        self, image_path: Path
    ) -> tuple[ClassificationResult | None, list[TierAttempt]]:
        """Walk the tier chain, falling through on failure *or* low confidence.

        A tier that answers below **its own** threshold doesn't win outright —
        the next tier gets a shot. The best low-confidence answer is kept as a
        fallback so a weak guess still beats discarding the sighting entirely.

        Thresholds are per tier (see ``DEFAULT_TIER_THRESHOLDS``) because a raw
        confidence means different things coming from different tiers.

        Also returns the trace: one ``TierAttempt`` per tier in the chain, in
        chain order. The tiers after the one that answered are ``not_run``.
        """
        best: ClassificationResult | None = None
        best_ratio = 0.0
        chain = self._classifiers_for_preference()
        trace: list[TierAttempt] = []

        for i, clf in enumerate(chain):
            threshold = self._cfg.threshold_for(clf.tier_name)
            result = await clf.classify(image_path)

            if result is None:
                logger.warning("Tier '%s' failed — trying next", clf.tier_name)
                trace.append(TierAttempt(clf.tier_name, "failed", None, threshold))
                continue

            if result.confidence >= threshold:
                trace.append(
                    TierAttempt(clf.tier_name, "accepted", result.confidence, threshold)
                )
                return result, trace + self._not_run(chain[i + 1:])

            trace.append(
                TierAttempt(clf.tier_name, "below_threshold", result.confidence, threshold)
            )

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
        return best, trace


def _trace_json(trace: list[TierAttempt]) -> list[dict]:
    """The trace as the plain dicts that the upload and the queue file carry."""
    return [asdict(attempt) for attempt in trace]
