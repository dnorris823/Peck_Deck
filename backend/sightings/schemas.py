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


def sighting_response(s) -> SightingResponse:
    """Serialize a ``Sighting`` row for the wire.

    Shared by ``GET /sightings`` and the ``GET /events`` stream on purpose: a
    streamed sighting has to be indistinguishable from a fetched one, because
    the web app maps both through the same function and prepends the streamed
    one straight into the list it got from the fetch.
    """
    return SightingResponse(
        id=s.id,
        species_id=s.species_id,
        device_id=s.device_id,
        datetime=s.datetime.isoformat(),
        classification_tier_used=s.classification_tier_used,
        confidence_score=s.confidence_score,
        weather_conditions=s.weather_conditions,
        delayed=s.delayed,
        has_image=s.image_data is not None,
        tier_trace=(
            [TierAttempt(**a) for a in s.tier_trace] if s.tier_trace is not None else None
        ),
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
