"""Tier-chain fallthrough logic in ``Pipeline._classify``.

The chain must advance on **failure** (``None``) *and* on a result that lands
below ``confidence_threshold`` — the latter is what makes CLAUDE.md's
"falls back ... based on availability and confidence thresholds" true.
"""
import asyncio
from pathlib import Path

import pytest

from raspberry_pi_code.classification.base import ClassificationResult, ClassifierBase
from raspberry_pi_code.config import Config
from raspberry_pi_code.pipeline import Pipeline

_IMAGE = Path("capture.jpg")


class _StubClassifier(ClassifierBase):
    """Returns a canned result (or None) and records whether it was called."""

    def __init__(self, tier: str, confidence: float | None):
        self._tier = tier
        self._confidence = confidence
        self.calls = 0

    @property
    def tier_name(self) -> str:
        return self._tier

    async def classify(self, image_path: Path) -> ClassificationResult | None:
        self.calls += 1
        if self._confidence is None:
            return None
        return ClassificationResult(
            common_name=f"{self._tier}-bird",
            scientific_name=f"Genus {self._tier}",
            confidence=self._confidence,
            tier_used=self._tier,
        )


def _pipeline(tmp_path, threshold: float = 0.5) -> Pipeline:
    cfg = Config(
        cache_dir=str(tmp_path / "cache"),
        confidence_threshold=threshold,
        device_token="test-token",
    )
    return Pipeline(cfg)


def _run(pipeline: Pipeline, *classifiers: _StubClassifier):
    pipeline._classifiers_for_preference = lambda: list(classifiers)
    return asyncio.run(pipeline._classify(_IMAGE))


def test_confident_first_tier_wins_without_calling_the_rest(tmp_path):
    tier1 = _StubClassifier("local", 0.87)
    tier2 = _StubClassifier("gpu", 0.99)

    result = _run(_pipeline(tmp_path), tier1, tier2)

    assert result.tier_used == "local"
    assert result.confidence == 0.87
    assert tier2.calls == 0, "GPU must not be hit when Tier 1 is already confident"


def test_low_confidence_falls_through_to_next_tier(tmp_path):
    # The regression this suite exists for: 0.31 < 0.5 must NOT win outright.
    tier1 = _StubClassifier("local", 0.31)
    tier2 = _StubClassifier("gpu", 0.92)

    result = _run(_pipeline(tmp_path), tier1, tier2)

    assert tier1.calls == 1
    assert tier2.calls == 1
    assert result.tier_used == "gpu"
    assert result.confidence == 0.92


def test_confidence_exactly_at_threshold_is_accepted(tmp_path):
    tier1 = _StubClassifier("local", 0.5)
    tier2 = _StubClassifier("gpu", 0.99)

    result = _run(_pipeline(tmp_path, threshold=0.5), tier1, tier2)

    assert result.tier_used == "local"
    assert tier2.calls == 0


def test_best_low_confidence_result_is_kept_when_no_tier_clears(tmp_path):
    # Nothing clears the bar — a weak guess still beats discarding the sighting.
    tier1 = _StubClassifier("local", 0.20)
    tier2 = _StubClassifier("gpu", 0.44)
    tier3 = _StubClassifier("cloud", 0.11)

    result = _run(_pipeline(tmp_path), tier1, tier2, tier3)

    assert result.tier_used == "gpu"
    assert result.confidence == 0.44
    assert tier3.calls == 1, "every tier is tried before settling for best-effort"


def test_hard_failure_still_falls_through(tmp_path):
    tier1 = _StubClassifier("local", None)  # model missing / inference crashed
    tier2 = _StubClassifier("gpu", 0.77)

    result = _run(_pipeline(tmp_path), tier1, tier2)

    assert result.tier_used == "gpu"


def test_returns_none_when_every_tier_fails(tmp_path):
    tier1 = _StubClassifier("local", None)
    tier2 = _StubClassifier("gpu", None)

    assert _run(_pipeline(tmp_path), tier1, tier2) is None


def test_low_confidence_beats_a_failing_later_tier(tmp_path):
    tier1 = _StubClassifier("local", 0.30)
    tier2 = _StubClassifier("gpu", None)

    result = _run(_pipeline(tmp_path), tier1, tier2)

    assert result is not None
    assert result.tier_used == "local"
    assert result.confidence == 0.30


@pytest.mark.parametrize(
    "preference, expected",
    [
        ("auto", ["local", "gpu", "cloud"]),
        ("local", ["local"]),
        ("gpu", ["gpu", "local"]),
        ("cloud", ["cloud", "gpu", "local"]),
    ],
)
def test_tier_preference_ordering(tmp_path, preference, expected):
    cfg = Config(cache_dir=str(tmp_path / "cache"), tier_preference=preference)
    pipeline = Pipeline(cfg)

    assert [c.tier_name for c in pipeline._classifiers_for_preference()] == expected
