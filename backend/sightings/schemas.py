import json
import logging
from dataclasses import dataclass
from datetime import datetime
from typing import Literal

logger = logging.getLogger("peckdeck.sightings")

TierOutcome = Literal["accepted", "below_threshold", "failed", "not_run"]
_OUTCOMES = {"accepted", "below_threshold", "failed", "not_run"}


@dataclass
class TierAttempt:
    """What one tier of the Pi's chain did with a capture.

    ``confidence`` is null when the tier gave no answer. ``threshold`` is the
    bar the Pi held the tier to.
    """

    tier: str  # "local" | "gpu" | "cloud"
    outcome: TierOutcome
    confidence: float | None
    threshold: float


@dataclass
class SightingResponse:
    id: int
    species_id: int
    device_id: int
    datetime: str
    classification_tier_used: str
    confidence_score: float
    weather_conditions: str | None
    delayed: bool
    has_image: bool
    # In chain order. Null for sightings from before the Pi sent a trace.
    tier_trace: list[TierAttempt] | None
    # Set once a person corrects the species. `species_id` is then their
    # answer, and `original_species_id` is the one the tier above named.
    original_species_id: int | None = None
    corrected_by: int | None = None
    corrected_at: str | None = None
    # "pending" while the species is the Pi's fallback and waits for the GPU
    # tier, "done" once the backend asked it. Null when Tier 2 answered live.
    tier2_recheck: str | None = None
    # The species the Pi named, set only when a re-check replaced it.
    provisional_species_id: int | None = None
    rechecked_at: str | None = None


@dataclass
class DeleteSightings:
    """The sightings to delete, by id. At most ``MAX_BULK_DELETE``."""

    ids: list[int]


@dataclass
class DeletedCount:
    deleted: int


@dataclass
class CorrectSpecies:
    """Body of ``PATCH /sightings/{id}``."""

    species_id: int


def sighting_response(s, has_image: bool | None = None) -> SightingResponse:
    """Serialize a ``Sighting`` row for the wire.

    Shared by ``GET /sightings`` and the ``GET /events`` stream on purpose: a
    streamed sighting has to be indistinguishable from a fetched one, because
    the web app maps both through the same function and prepends the streamed
    one straight into the list it got from the fetch.

    A query that deferred ``image_data`` passes ``has_image``, the flag it
    selected next to the row. Leave it out only when the image is already in
    memory, such as a sighting that was just created.
    """
    if has_image is None:
        has_image = s.image_data is not None
    return SightingResponse(
        id=s.id,
        species_id=s.species_id,
        device_id=s.device_id,
        datetime=s.datetime.isoformat(),
        classification_tier_used=s.classification_tier_used,
        confidence_score=s.confidence_score,
        weather_conditions=s.weather_conditions,
        delayed=s.delayed,
        has_image=has_image,
        tier_trace=(
            [TierAttempt(**a) for a in s.tier_trace] if s.tier_trace is not None else None
        ),
        original_species_id=s.original_species_id,
        corrected_by=s.corrected_by,
        corrected_at=s.corrected_at.isoformat() if s.corrected_at else None,
        tier2_recheck=s.tier2_recheck,
        provisional_species_id=s.provisional_species_id,
        rechecked_at=s.rechecked_at.isoformat() if s.rechecked_at else None,
    )


def parse_tier_trace(raw: str | None) -> list[dict] | None:
    """Read the upload's ``tier_trace`` field, or None if it is absent or bad.

    A bad trace stores null and keeps the sighting. The trace only explains the
    answer, and a 4xx would make the Pi drop the visit for good.
    """
    if raw is None or raw == "":
        return None
    try:
        entries = json.loads(raw)
        if not isinstance(entries, list):
            raise ValueError("not a list")
        return [_attempt(e) for e in entries]
    except (ValueError, TypeError, KeyError) as exc:
        logger.warning("Ignoring a malformed tier_trace (%s): %.200s", exc, raw)
        return None


def parse_crop_box(raw: str | None) -> list[int] | None:
    """Read the upload's ``crop_box`` field, or None if it is absent or bad.

    The field is a JSON list of pixel edges, ``[left, top, right, bottom]``. A
    bad box stores null and keeps the sighting, like a bad trace. The re-check
    then classifies the full frame.
    """
    if raw is None or raw == "":
        return None
    try:
        box = json.loads(raw)
        if not isinstance(box, list) or len(box) != 4:
            raise ValueError("not a list of four")
        if any(isinstance(v, bool) or not isinstance(v, int) for v in box):
            raise ValueError("not whole numbers")
        left, top, right, bottom = box
        if left < 0 or top < 0 or right <= left or bottom <= top:
            raise ValueError("edges out of order")
        return box
    except ValueError as exc:
        logger.warning("Ignoring a malformed crop_box (%s): %.200s", exc, raw)
        return None


def _attempt(entry: dict) -> dict:
    """One checked entry, holding only the four known keys."""
    tier, outcome = entry["tier"], entry["outcome"]
    confidence, threshold = entry["confidence"], entry["threshold"]
    if not isinstance(tier, str) or outcome not in _OUTCOMES:
        raise ValueError(f"bad tier or outcome in {entry!r}")
    if confidence is not None:
        confidence = _number(confidence)
    return {
        "tier": tier,
        "outcome": outcome,
        "confidence": confidence,
        "threshold": _number(threshold),
    }


def _number(value) -> float:
    # bool is an int in Python, and true is not a confidence.
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"not a number: {value!r}")
    return float(value)


@dataclass
class SightingListParams:
    device_id: int | None = None
    species_id: int | None = None
    from_date: str | None = None
    to_date: str | None = None
    limit: int = 50
    offset: int = 0
