"""Tier 1 must never answer "Background".

On 2026-10-28 Tier 1 called a house finch "Background" at 0.92, above its 0.85
bar, and the backend made a species row for it. The camera has already decided
there is a bird, so Background is a non-answer and the chain must move on.
"""
import asyncio
from pathlib import Path

import numpy as np

from raspberry_pi_code.classification import tier1_tflite
from raspberry_pi_code.classification.base import ClassificationResult, ClassifierBase
from raspberry_pi_code.classification.tier1_tflite import TFLiteClassifier, _Taxon
from raspberry_pi_code.config import Config
from raspberry_pi_code.pipeline import Pipeline

_IMAGE = Path("capture.jpg")

# Same shape as the real taxonomy.csv: species rows, then Background last.
_TAXA = [
    _Taxon("House Finch", "Haemorhous", "mexicanus"),
    _Taxon("Cassin's Finch", "Haemorhous", "cassinii"),
    _Taxon("Background", "", ""),
]


class _FakeInterpreter:
    """Returns fixed float scores, one per taxon."""

    def __init__(self, scores: list[float]):
        self._scores = np.array([scores], dtype=np.float32)

    def get_input_details(self):
        return [{"index": 0, "dtype": np.float32}]

    def get_output_details(self):
        return [{"index": 1, "quantization": (0.0, 0)}]

    def set_tensor(self, index, data):
        pass

    def invoke(self):
        pass

    def get_tensor(self, index):
        return self._scores


def _tier1(monkeypatch, scores: list[float]) -> TFLiteClassifier:
    monkeypatch.setattr(tier1_tflite, "_preprocess", lambda path, as_uint8: None)
    clf = TFLiteClassifier("model.tflite", "taxonomy.csv")
    clf._interp = _FakeInterpreter(scores)
    clf._taxa = _TAXA
    return clf


class _StubGpu(ClassifierBase):
    def __init__(self):
        self.calls = 0

    @property
    def tier_name(self) -> str:
        return "gpu"

    async def classify(self, image_path: Path) -> ClassificationResult | None:
        self.calls += 1
        return ClassificationResult("House Finch", "Haemorhous mexicanus", 0.91, "gpu")


def _classify(tmp_path, *classifiers) -> ClassificationResult | None:
    pipeline = Pipeline(Config(cache_dir=str(tmp_path / "cache"), device_token="test-token"))
    pipeline._classifiers_for_preference = lambda: list(classifiers)
    return asyncio.run(pipeline._classify(_IMAGE))


def test_tier1_returns_no_result_when_background_is_top(monkeypatch):
    clf = _tier1(monkeypatch, [0.05, 0.03, 0.92])

    assert asyncio.run(clf.classify(_IMAGE)) is None


def test_tier1_still_answers_a_real_species(monkeypatch):
    clf = _tier1(monkeypatch, [0.90, 0.05, 0.05])

    result = asyncio.run(clf.classify(_IMAGE))

    assert result.common_name == "House Finch"
    assert result.scientific_name == "Haemorhous mexicanus"


def test_chain_moves_to_the_next_tier_when_tier1_says_background(monkeypatch, tmp_path):
    gpu = _StubGpu()

    result = _classify(tmp_path, _tier1(monkeypatch, [0.05, 0.03, 0.92]), gpu)

    assert gpu.calls == 1
    assert result.tier_used == "gpu"
    assert result.common_name == "House Finch"


def test_background_is_not_kept_as_a_best_effort_answer(monkeypatch, tmp_path):
    # With no other tier, the chain returns nothing. The pipeline then uploads
    # the capture as "Unknown" with tier "none" rather than as "Background".
    assert _classify(tmp_path, _tier1(monkeypatch, [0.05, 0.03, 0.92])) is None
