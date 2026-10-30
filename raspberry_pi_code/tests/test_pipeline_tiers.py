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

from raspberry_pi_code.api_client import UploadOutcome
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

    ``threshold`` sets all three tiers to one number, so a test about
    fallthrough order isn't also a test about which default applies to which
    tier. ``None`` leaves the measured defaults in place.
    """
    bars = {}
    if threshold is not None:
        bars = {f"tier{i}_confidence_threshold": threshold for i in (1, 2, 3)}
    cfg = Config(
        cache_dir=str(tmp_path / "cache"),
        device_token="test-token",
        **{**bars, **overrides},
    )
    return Pipeline(cfg)


def _run(pipeline: Pipeline, *classifiers: _StubClassifier):
    return _run_traced(pipeline, *classifiers)[0]


def _run_traced(pipeline: Pipeline, *classifiers: _StubClassifier):
    """The result and the trace, as ``(result, [(tier, outcome, confidence, threshold)])``."""
    pipeline._classifiers_for_preference = lambda: list(classifiers)
    result, trace = asyncio.run(pipeline._classify(_IMAGE))
    return result, [(a.tier, a.outcome, a.confidence, a.threshold) for a in trace]


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


def test_a_per_tier_override_beats_the_shared_bar(tmp_path):
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


def test_default_preference_sends_captures_to_tier2_first(tmp_path):
    """A Pi with a default .env asks the GPU first and never calls Claude."""
    pipeline = Pipeline(Config(cache_dir=str(tmp_path / "cache")))

    order = [c.tier_name for c in pipeline._classifiers_for_preference()]

    assert order == ["gpu", "local"]


@pytest.mark.parametrize("bad", ["", "GPU", "gpu ", "claude"])
def test_unknown_tier_preference_refuses_to_start(tmp_path, bad):
    """It used to fall through to "auto", so a typo turned on paid Claude calls."""
    with pytest.raises(ValueError, match="TIER_PREFERENCE"):
        Pipeline(Config(cache_dir=str(tmp_path / "cache"), tier_preference=bad))


# ── Every tier down ──────────────────────────────────────────────────────────

class _FileCamera:
    """Writes a few bytes where the pipeline asks, like a real capture."""

    async def capture(self, output_path: Path) -> Path:
        output_path.write_bytes(b"\xff\xd8 not really a jpeg")
        return output_path


class _RecordingClient:
    def __init__(self, outcome: UploadOutcome):
        self.outcome = outcome
        self.posts: list[dict] = []

    async def post_sighting(self, **kwargs) -> UploadOutcome:
        self.posts.append(kwargs)
        return self.outcome


async def _capture_and_process(pipeline: Pipeline) -> None:
    """One visit, start to finish, without the background worker."""
    await pipeline._process(await pipeline._capture())


def _dead_chain_pipeline(tmp_path, outcome: UploadOutcome) -> tuple[Pipeline, _RecordingClient]:
    """Default config, Tier 1's model file missing, Tier 2 unreachable."""
    cfg = Config(
        cache_dir=str(tmp_path / "cache"),
        device_token="t",
        model_path=str(tmp_path / "no-such-model.tflite"),
    )
    pipeline = Pipeline(cfg, camera=_FileCamera())
    pipeline.setup()  # Tier 1 fails to load here, as it does on the Pi
    # GPUServerClassifier returns None on a refused connection or a timeout.
    pipeline._tier2 = _StubClassifier("gpu", None)
    client = _RecordingClient(outcome)
    pipeline._client = client
    return pipeline, client


def test_capture_uploads_with_no_species_when_every_tier_fails(tmp_path):
    pipeline, client = _dead_chain_pipeline(tmp_path, UploadOutcome.OK)

    asyncio.run(_capture_and_process(pipeline))

    assert len(client.posts) == 1, "the visit must not be discarded"
    post = client.posts[0]
    assert post["common_name"] == "Unknown"
    assert post["scientific_name"] == ""
    assert post["confidence"] == 0.0
    assert post["tier_used"] == "none"
    assert pipeline._cache.get_pending() == []


def test_capture_queues_with_no_species_when_every_tier_and_the_backend_fail(tmp_path):
    pipeline, client = _dead_chain_pipeline(tmp_path, UploadOutcome.RETRY)

    asyncio.run(_capture_and_process(pipeline))

    queued = pipeline._cache.get_pending()
    assert len(queued) == 1
    assert queued[0].common_name == "Unknown"
    assert queued[0].tier_used == "none"
    assert Path(queued[0].image_path).exists()


# ── Tier trace ───────────────────────────────────────────────────────────────

def test_trace_shows_tier2_failed_and_tier1_accepted(tmp_path):
    """The case the trace exists for: under "gpu", was Tier 2 down or unsure?"""
    tier2 = _StubClassifier("gpu", None)
    tier1 = _StubClassifier("local", 0.91)

    result, trace = _run_traced(_pipeline(tmp_path, threshold=None), tier2, tier1)

    assert result.tier_used == "local"
    assert trace == [
        ("gpu", "failed", None, 0.60),
        ("local", "accepted", 0.91, 0.85),
    ]


def test_trace_marks_the_tiers_after_the_answer_not_run(tmp_path):
    tier2 = _StubClassifier("gpu", 0.72)
    tier1 = _StubClassifier("local", 0.99)

    _, trace = _run_traced(_pipeline(tmp_path, threshold=None), tier2, tier1)

    assert trace == [
        ("gpu", "accepted", 0.72, 0.60),
        ("local", "not_run", None, 0.85),
    ]


def test_trace_keeps_below_threshold_on_a_best_effort_answer(tmp_path):
    # classification_tier_used names the winner. The trace keeps the truth that
    # no tier cleared its bar.
    tier2 = _StubClassifier("gpu", 0.44)
    tier1 = _StubClassifier("local", 0.20)

    result, trace = _run_traced(_pipeline(tmp_path, threshold=0.5), tier2, tier1)

    assert result.tier_used == "gpu"
    assert trace == [
        ("gpu", "below_threshold", 0.44, 0.5),
        ("local", "below_threshold", 0.20, 0.5),
    ]


def test_every_tier_failed_uploads_a_trace_of_failures(tmp_path):
    pipeline, client = _dead_chain_pipeline(tmp_path, UploadOutcome.OK)

    asyncio.run(_capture_and_process(pipeline))

    post = client.posts[0]
    assert post["tier_used"] == "none"
    assert post["tier_trace"] == [
        {"tier": "gpu", "outcome": "failed", "confidence": None, "threshold": 0.60},
        {"tier": "local", "outcome": "failed", "confidence": None, "threshold": 0.85},
    ]


def test_a_queued_sighting_keeps_its_trace(tmp_path):
    pipeline, _ = _dead_chain_pipeline(tmp_path, UploadOutcome.RETRY)

    asyncio.run(_capture_and_process(pipeline))

    [queued] = pipeline._cache.get_pending()
    assert [(a["tier"], a["outcome"]) for a in queued.tier_trace] == [
        ("gpu", "failed"),
        ("local", "failed"),
    ]
