"""Re-check Tier 1 fallbacks on the GPU tier once the inference server is back.

When the inference server is off, the Pi falls back to Tier 1 so a sighting
still appears at once. Tier 2 is the more accurate tier (85% against 64% on 300
field photos, see machine_learning/MODELS.md), so the backend asks it again
later and lets it have the final word.

At upload, ``needs_recheck`` reads the Pi's trace and marks the sighting
``tier2_recheck = "pending"`` when Tier 2 gave no answer. A task in the API
process then wakes every ``TIER2_RECHECK_INTERVAL_SECONDS``. While pending rows
exist it calls the server's ``GET /health``. When the server answers, it sends
the pending captures to ``POST /classify`` one at a time, oldest first, so the
Pi's live requests still get a turn.

- A connection error, a timeout or a 5xx ends the pass. The rows stay pending.
  A server paused for a game answers ``GET /health`` with its state and
  ``POST /classify`` with 503, so its rows wait too.
- A 4xx for one image marks that row done with no change, so one bad image
  cannot block the queue.
- A sighting a person corrected is marked done and keeps their species.
- A feeder animal wins by the Pi's rule: it meets ``TIER2_ANIMAL_THRESHOLD`` and
  beats Tier 2's bird. The sighting then takes the animal species, whatever
  Tier 1 said, because Tier 1 knows birds only.
- ``tier_trace`` stays as the Pi wrote it. The Tier 2 warning on the feeder
  card reads the Pi's own attempt, and a re-check must not hide the outage.
- A changed row goes to open tabs as ``SightingUpdated``. The normal alert went
  out at upload, so the only push is the new species alert, which waited for
  the re-check. A person's correction sends none. See
  backend/notifications/new_species.py.

Like the SSE fan-out, the loop assumes one API process. Two processes could
re-check one row twice.
"""
import asyncio
import contextlib
import io
import logging
from dataclasses import asdict, dataclass
from datetime import datetime, timezone

import aiohttp
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..config import settings
from ..database.connection import get_session_factory
from ..database.models import Sighting
from ..events.hub import SightingUpdated, sighting_hub
from ..notifications.service import notification_service
from ..species.operations import ANIMAL
from .aftercare import enrich_if_sparse
from .operations import HAS_IMAGE, SKIP_IMAGE, species_for_names
from .schemas import sighting_response

logger = logging.getLogger("peckdeck.recheck")

PENDING = "pending"
DONE = "done"

# The Pi's defaults, from DEFAULT_TIER_THRESHOLDS in raspberry_pi_code/config.py.
# Used only when the trace has no entry for a tier.
DEFAULT_THRESHOLDS = {"local": 0.85, "gpu": 0.60, "cloud": 0.50}

HEALTH_TIMEOUT_SECONDS = 5
CLASSIFY_TIMEOUT_SECONDS = 30
CROP_JPEG_QUALITY = 90

_task: asyncio.Task | None = None


def needs_recheck(trace: list[dict] | None, tier_used: str) -> bool:
    """Whether the Pi's trace shows that Tier 2 gave no answer.

    - Tier 2 ``failed``: yes.
    - Every tier ``not_run`` and tier ``none``: yes. The Pi's classify queue
      overflowed behind Tier 2 timeouts.
    - Tier 2 ``accepted`` or ``below_threshold``: no. A second ask gives the
      same answer.
    - No Tier 2 entry, or no trace: no. That is ``TIER_PREFERENCE=local`` or an
      older Pi build.
    """
    if not trace:
        return False
    gpu = next((a for a in trace if a.get("tier") == "gpu"), None)
    if gpu is None:
        return False
    if gpu["outcome"] == "failed":
        return True
    return tier_used == "none" and all(a["outcome"] == "not_run" for a in trace)


def _threshold(trace: list[dict] | None, tier: str) -> float:
    """The bar the Pi held ``tier`` to, from the trace, else the default."""
    for attempt in trace or ():
        if attempt.get("tier") == tier:
            return attempt["threshold"]
    return DEFAULT_THRESHOLDS.get(tier, 1.0)


def should_replace(
    trace: list[dict] | None, tier_used: str, confidence: float, gpu_confidence: float
) -> bool:
    """Whether Tier 2's answer replaces the one the sighting holds.

    Tier 2 wins when it meets its own threshold. Below it, the rule from
    ``Pipeline._classify`` applies: the answer closer to its own tier's bar
    wins. An "Unknown" sighting, tier ``none``, takes any Tier 2 answer.
    """
    gpu_bar = _threshold(trace, "gpu")
    if gpu_confidence >= gpu_bar:
        return True
    if tier_used == "none":
        return True
    held_bar = _threshold(trace, tier_used)
    gpu_ratio = gpu_confidence / gpu_bar if gpu_bar > 0 else float("inf")
    held_ratio = confidence / held_bar if held_bar > 0 else float("inf")
    # A tie goes to Tier 2, as it does on the Pi, where Tier 2 is asked first.
    return gpu_ratio >= held_ratio


def crop_image(image: bytes, box: list[int] | None) -> bytes:
    """The square the Pi classified, as a JPEG, or the full frame without one.

    A box that does not fit the image, or an image Pillow cannot read, gives
    the full frame back. The server then decides. Blocking: call it through
    ``asyncio.to_thread``.
    """
    if not box:
        return image
    try:
        from PIL import Image

        with Image.open(io.BytesIO(image)) as img:
            left, top, right, bottom = box
            if right > img.width or bottom > img.height:
                logger.warning(
                    "crop_box %s is outside a %dx%d image. Re-checking the full frame",
                    box, img.width, img.height,
                )
                return image
            out = io.BytesIO()
            img.crop((left, top, right, bottom)).convert("RGB").save(
                out, "JPEG", quality=CROP_JPEG_QUALITY
            )
            return out.getvalue()
    except Exception:
        logger.warning("Could not crop a sighting image. Re-checking the full frame",
                       exc_info=True)
        return image


# ── The inference server ──────────────────────────────────────────────────────


class ServerDown(Exception):
    """The server did not answer, or answered with a 5xx. Ends the pass."""


class ImageRejected(Exception):
    """The server refused this one image with a 4xx."""


@dataclass(frozen=True)
class AnimalAnswer:
    """The ``animal`` field of ``POST /classify``, a row of feeder_animals.csv."""

    common_name: str
    scientific_name: str
    group: str
    confidence: float


@dataclass(frozen=True)
class Answer:
    common_name: str
    scientific_name: str
    confidence: float
    # Tier 2's best feeder animal. None from an older server, or a model with
    # no animal in its label space.
    animal: AnimalAnswer | None = None


def _animal(raw) -> AnimalAnswer | None:
    """Read the ``animal`` field. A malformed one is dropped, and the bird stands."""
    if raw is None:
        return None
    try:
        return AnimalAnswer(
            common_name=str(raw["common_name"]),
            scientific_name=str(raw.get("scientific_name") or ""),
            group=str(raw["group"]).strip().lower(),
            confidence=float(raw["confidence"]),
        )
    except (AttributeError, KeyError, TypeError, ValueError):
        logger.warning("tier2 recheck: ignoring a malformed animal field: %.200r", raw)
        return None


def winning_animal(answer: Answer, threshold: float) -> AnimalAnswer | None:
    """The animal, if it wins by the Pi's rule in ``Pipeline._winning_animal``.

    It wins when it meets ``threshold`` and beats Tier 2's bird confidence.
    """
    animal = answer.animal
    if animal is None or not animal.group:
        return None
    if animal.confidence < threshold or animal.confidence <= answer.confidence:
        return None
    return animal


class InferenceClient:
    """``GET /health``, ``POST /classify`` and the pause switch on the inference server."""

    def __init__(self, base_url: str):
        self._base = base_url.rstrip("/")

    async def status(self) -> dict | None:
        """The server's ``GET /health`` body, or None when it does not answer."""
        try:
            timeout = aiohttp.ClientTimeout(total=HEALTH_TIMEOUT_SECONDS)
            async with aiohttp.ClientSession(timeout=timeout) as session:
                async with session.get(f"{self._base}/health") as resp:
                    if resp.status != 200:
                        return None
                    body = await resp.json()
        except (aiohttp.ClientError, asyncio.TimeoutError, ValueError):
            return None
        return body if isinstance(body, dict) else None

    async def healthy(self) -> bool:
        """True when the server answers and its model has loaded.

        A paused server, for a game or by the owner, is not healthy, so the
        pending rows wait for it. An older server sends no ``state``.
        """
        body = await self.status()
        if body is None:
            return False
        return bool(body.get("model_ready", True)) and body.get("state", "ready") == "ready"

    async def set_paused(self, paused: bool) -> dict | None:
        """``POST /pause`` or ``POST /resume``. The new status, or None if down."""
        path = "/pause" if paused else "/resume"
        try:
            timeout = aiohttp.ClientTimeout(total=HEALTH_TIMEOUT_SECONDS)
            async with aiohttp.ClientSession(timeout=timeout) as session:
                async with session.post(f"{self._base}{path}") as resp:
                    if resp.status != 200:
                        return None
                    body = await resp.json()
        except (aiohttp.ClientError, asyncio.TimeoutError, ValueError):
            return None
        return body if isinstance(body, dict) else None

    async def classify(self, image: bytes) -> Answer:
        form = aiohttp.FormData()
        form.add_field("image", image, filename="sighting.jpg", content_type="image/jpeg")
        try:
            timeout = aiohttp.ClientTimeout(total=CLASSIFY_TIMEOUT_SECONDS)
            async with aiohttp.ClientSession(timeout=timeout) as session:
                async with session.post(f"{self._base}/classify", data=form) as resp:
                    if 400 <= resp.status < 500:
                        raise ImageRejected(f"HTTP {resp.status}")
                    if resp.status != 200:
                        raise ServerDown(f"HTTP {resp.status}")
                    body = await resp.json()
        except (aiohttp.ClientError, asyncio.TimeoutError) as exc:
            raise ServerDown(str(exc) or type(exc).__name__) from exc
        try:
            return Answer(
                common_name=str(body["common_name"]),
                scientific_name=str(body.get("scientific_name") or ""),
                confidence=float(body["confidence"]),
                animal=_animal(body.get("animal")),
            )
        except (KeyError, TypeError, ValueError) as exc:
            # A server bug, not a bad image. Try again on a later pass.
            raise ServerDown(f"unreadable answer: {body!r:.200}") from exc


# ── One sighting ──────────────────────────────────────────────────────────────


async def pending_ids(db: AsyncSession) -> list[int]:
    """Pending sightings, oldest capture first."""
    result = await db.execute(
        select(Sighting.id)
        .where(Sighting.tier2_recheck == PENDING)
        .order_by(Sighting.datetime, Sighting.id)
    )
    return list(result.scalars())


async def recheck_one(sighting_id: int, client: InferenceClient) -> str:
    """Re-check one sighting. Returns what happened, for the log and tests.

    ``"replaced"``, ``"kept"``, ``"corrected"``, ``"rejected"``, ``"no_image"``
    or ``"gone"``. Raises ``ServerDown`` with the row still pending.

    The image is read in one session and the answer applied in another, so no
    transaction stays open across a 30-second classify call.
    """
    async with get_session_factory()() as db:
        row = (
            await db.execute(
                select(
                    Sighting.image_data,
                    Sighting.crop_box,
                    Sighting.corrected_at,
                    Sighting.tier2_recheck,
                ).where(Sighting.id == sighting_id)
            )
        ).one_or_none()
    if row is None or row.tier2_recheck != PENDING:
        return "gone"
    if row.corrected_at is not None:
        return await _apply(sighting_id, None, outcome="corrected")
    if row.image_data is None:
        return await _apply(sighting_id, None, outcome="no_image")

    image = await asyncio.to_thread(crop_image, row.image_data, row.crop_box)
    try:
        answer = await client.classify(image)
    except ImageRejected as exc:
        logger.warning("tier2 recheck: server refused sighting %d (%s)", sighting_id, exc)
        return await _apply(sighting_id, None, outcome="rejected")
    return await _apply(sighting_id, answer)


async def _apply(sighting_id: int, answer: Answer | None, *, outcome: str = "") -> str:
    """Mark the row done, and take Tier 2's answer when it wins. Then publish."""
    new_species = None
    async with get_session_factory()() as db:
        async with db.begin():
            found = (
                await db.execute(
                    select(Sighting, HAS_IMAGE)
                    .options(SKIP_IMAGE)
                    .where(Sighting.id == sighting_id)
                    .with_for_update()
                )
            ).one_or_none()
            if found is None or found[0].tier2_recheck != PENDING:
                return "gone"
            s, has_image = found
            now = datetime.now(timezone.utc)
            s.tier2_recheck = DONE
            if outcome != "corrected":
                s.rechecked_at = now

            winner = None  # (common_name, confidence) of the answer that won
            if answer is not None:
                animal = winning_animal(answer, settings.TIER2_ANIMAL_THRESHOLD)
                # A person may have corrected it during the classify call.
                if s.corrected_at is not None:
                    outcome = "corrected"
                elif animal is not None:
                    # Tier 1 knows birds only, so its answer never beats an animal.
                    new_species = await species_for_names(
                        db, animal.common_name, animal.scientific_name,
                        kind=ANIMAL, animal_group=animal.group,
                    )
                    winner = (animal.common_name, animal.confidence)
                elif _named(answer) and should_replace(
                    s.tier_trace, s.classification_tier_used,
                    s.confidence_score, answer.confidence,
                ):
                    new_species = await species_for_names(
                        db, answer.common_name, answer.scientific_name
                    )
                    winner = (answer.common_name, answer.confidence)
                else:
                    outcome = "kept"
            if new_species is not None:
                s.provisional_species_id = s.species_id
                s.species_id = new_species.id
                s.classification_tier_used = "gpu"
                s.confidence_score = winner[1]
                outcome = "replaced"
            await db.flush()
            body = sighting_response(s, has_image=bool(has_image))
            device_id = s.device_id

    if winner is None and answer is not None:
        winner = (answer.common_name, answer.confidence)
    logger.info(
        "tier2 recheck: sighting %d %s%s", sighting_id, outcome,
        f" ({winner[0]}, {winner[1]:.2f})" if winner else "",
    )
    # After the commit, so a tab that reads the row back sees the change.
    sighting_hub.publish(
        SightingUpdated(sighting_id=sighting_id, device_id=device_id, payload=asdict(body))
    )
    # A species the GPU named for the first time gets its field-guide entry.
    enrich_if_sparse(new_species)
    # "New species" waited for this answer. Fire and forget, like the upload.
    if outcome != "corrected":
        asyncio.create_task(
            notification_service.dispatch(sighting_id, device_id, after_recheck=True)
        )
    return outcome


def _named(answer: Answer) -> bool:
    """An "Unknown" from Tier 2 names nothing, so it never replaces a species."""
    return answer.common_name.strip().lower() not in {"", "unknown"}


# ── The loop ──────────────────────────────────────────────────────────────────


async def run_pass(client: InferenceClient) -> int:
    """Re-check every pending sighting if the server is up. Returns how many.

    Takes the pending list once, so a row uploaded mid-pass waits for the next.
    """
    async with get_session_factory()() as db:
        ids = await pending_ids(db)
    if not ids:
        return 0
    if not await client.healthy():
        logger.debug("tier2 recheck: %d waiting, server not answering", len(ids))
        return 0

    logger.info("tier2 recheck: server is up, re-checking %d sightings", len(ids))
    count = 0
    for sighting_id in ids:
        try:
            await recheck_one(sighting_id, client)
        except ServerDown as exc:
            logger.warning(
                "tier2 recheck: server dropped (%s). %d sightings still waiting",
                exc, len(ids) - count,
            )
            break
        count += 1
    return count


async def _loop(interval: int, client: InferenceClient) -> None:
    while True:
        try:
            await run_pass(client)
        except Exception:
            # A failed pass must not end the loop. The next one tries again.
            logger.exception("tier2 recheck: pass failed")
        await asyncio.sleep(interval)


def start(interval: int, server_url: str) -> None:
    """Start the re-check task, or do nothing when it is off."""
    global _task
    if interval < 0:
        raise RuntimeError(
            f"TIER2_RECHECK_INTERVAL_SECONDS must be 0 (off) or more, not {interval}"
        )
    if interval == 0:
        logger.info("tier2 recheck: off (TIER2_RECHECK_INTERVAL_SECONDS is 0)")
        return
    logger.info("tier2 recheck: on, asking %s every %d s", server_url, interval)
    _task = asyncio.create_task(_loop(interval, InferenceClient(server_url)))


async def stop() -> None:
    global _task
    if _task is None:
        return
    _task.cancel()
    with contextlib.suppress(asyncio.CancelledError):
        await _task
    _task = None
