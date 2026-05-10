from abc import ABC, abstractmethod
from dataclasses import dataclass
from pathlib import Path


@dataclass
class ClassificationResult:
    common_name: str
    scientific_name: str
    confidence: float
    tier_used: str  # "local" | "gpu" | "cloud"


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
