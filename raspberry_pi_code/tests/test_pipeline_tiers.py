"""Tier-chain fallthrough logic in ``Pipeline._classify``.

The chain must advance on **failure** (``None``) *and* on a result that lands
below the answering tier's threshold — the latter is what makes CLAUDE.md's
"falls back ... based on availability and confidence thresholds" true.

Thresholds are per tier, so most tests here pin one explicitly rather than
relying on ``DEFAULT_TIER_THRESHOLDS``; the defaults have their own tests in
``test_config_thresholds.py``.
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


def _pipeline(tmp_path, threshold: float | None = 0.5, **overrides) -> Pipeline:
    """A pipeline with every tier on the same bar unless told otherwise.

    ``threshold`` goes in as the legacy global, which is exactly the knob these
    tests want: one number for all three tiers, so a test about fallthrough
    order isn't also a test about which default applies to which tier.
    """
    cfg = Config(
        cache_dir=str(tmp_path / "cache"),
        confidence_threshold=threshold,
        device_token="test-token",
        **overrides,
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


def test_each_tier_is_held_to_its_own_threshold(tmp_path):
    """0.80 from Tier 1 used to win outright at the old global 0.5.

    Under the measured defaults it is below Tier 1's 0.85 bar and escalates,
    while the same 0.80 from Tier 2 clears its 0.60 bar. This is the whole
    change in one assertion.
    """
    tier1 = _StubClassifier("local", 0.80)
    tier2 = _StubClassifier("gpu", 0.80)

    result = _run(_pipeline(tmp_path, threshold=None), tier1, tier2)

    assert tier1.calls == 1
    assert tier2.calls == 1, "Tier 1 at 0.80 is under its 0.85 bar and must escalate"
    assert result.tier_used == "gpu"


def test_a_tier_that_clears_its_own_bar_still_short_circuits(tmp_path):
    tier1 = _StubClassifier("local", 0.91)
    tier2 = _StubClassifier("gpu", 0.99)

    result = _run(_pipeline(tmp_path, threshold=None), tier1, tier2)

    assert result.tier_used == "local"
    assert tier2.calls == 0, "no reason to spend a LAN hop on an already-confident answer"


def test_best_effort_ranks_by_distance_from_each_tiers_own_bar(tmp_path):
    """The subtle half of per-tier thresholds.

    Tier 1 at 0.62 is the higher raw number and would have won a naive max().
    But it is only 73% of its 0.85 bar, while Tier 2's 0.55 is 92% of its 0.60
    bar — and Tier 2 is the more accurate tier. Ranking on raw confidence would
    reintroduce exactly the cross-tier comparison these thresholds exist to
    stop, in the one code path that still compares tiers to each other.
    """
    tier1 = _StubClassifier("local", 0.62)
    tier2 = _StubClassifier("gpu", 0.55)

    result = _run(_pipeline(tmp_path, threshold=None), tier1, tier2)

    assert result.tier_used == "gpu"
    assert result.confidence == 0.55


def test_legacy_global_still_governs_every_tier(tmp_path):
    # A deployment pinned to the old single knob keeps its old behaviour.
    tier1 = _StubClassifier("local", 0.55)
    tier2 = _StubClassifier("gpu", 0.99)

    result = _run(_pipeline(tmp_path, threshold=0.5), tier1, tier2)

    assert result.tier_used == "local"
    assert tier2.calls == 0


def test_a_per_tier_override_beats_the_legacy_global(tmp_path):
    tier1 = _StubClassifier("local", 0.55)
    tier2 = _StubClassifier("gpu", 0.99)

    result = _run(
        _pipeline(tmp_path, threshold=0.5, tier1_confidence_threshold=0.9), tier1, tier2
    )

    assert result.tier_used == "gpu"


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
