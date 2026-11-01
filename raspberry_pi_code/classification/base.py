from abc import ABC, abstractmethod
from dataclasses import dataclass
from pathlib import Path
from typing import Literal


@dataclass(frozen=True)
class AnimalAnswer:
    """Tier 2's best feeder animal, a row of ``machine_learning/feeder_animals.csv``."""

    common_name: str
    scientific_name: str
    group: str  # squirrel, raccoon, bear, ...
    confidence: float


@dataclass
class ClassificationResult:
    common_name: str
    scientific_name: str
    confidence: float
    tier_used: str  # "local" | "gpu" | "cloud", or "none" when every tier failed
    # Set on a result that names an animal, not a bird. The sighting then
    # uploads with kind "animal" and this group.
    animal_group: str | None = None
    # Tier 2's animal candidate next to its bird answer. The pipeline decides
    # whether it wins. Only Tier 2 sets it.
    animal: AnimalAnswer | None = None


# What happened at one tier of the chain. "failed" covers a tier that returned
# no result: down, timed out, no model loaded, or no bird in its answer. When no
# tier clears its bar, the best-effort answer keeps "below_threshold", and the
# sighting's classification_tier_used says which tier it came from.
TierOutcome = Literal["accepted", "below_threshold", "failed", "not_run"]


@dataclass(frozen=True)
class TierAttempt:
    """One entry of a sighting's ``tier_trace``, uploaded as JSON.

    ``confidence`` is None when the tier gave no answer. ``threshold`` is the
    bar the tier was held to, so the app can draw it without the Pi's config.
    """

    tier: str
    outcome: TierOutcome
    confidence: float | None
    threshold: float


class ClassifierBase(ABC):
    """Abstract species classifier."""

    @property
    @abstractmethod
    def tier_name(self) -> str:
        ...

    @abstractmethod
    async def classify(self, image_path: Path) -> ClassificationResult | None:
        """Return a result, or None if the classifier is unavailable or fails."""
        ...
