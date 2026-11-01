"""Task 3.2b — Contract test for the Pi ↔ GPU inference-server seam.

Drives the **real** Raspberry Pi Tier-2 client
(``raspberry_pi_code.classification.tier2_gpu.GPUServerClassifier``) against a
**live** inference server (``inference_server.main.app`` under uvicorn) whose
GPU classifier is **mocked** — no torch, no CUDA, no model weights. This proves
the ``POST /classify`` contract: multipart image in, ``{common_name,
scientific_name, confidence}`` JSON out, mapped into a ``ClassificationResult``.
"""
import asyncio

import inference_server.main as inf_main
from inference_server.classifier import AnimalPrediction, Prediction
from raspberry_pi_code.classification.tier2_gpu import GPUServerClassifier

from integration_tests._live import run_server

_JPEG = b"\xff\xd8\xff\xe0" + b"gpu-contract-image" * 32

_STUB = Prediction(
    common_name="Northern Cardinal",
    scientific_name="Cardinalis cardinalis",
    confidence=0.9137,
)


class _FakeClassifier:
    """Stand-in for BirdClassifier — no torch, deterministic output."""

    def __init__(self, *_, **__):
        pass

    def load(self) -> bool:
        return True

    def classify(self, image_bytes: bytes) -> Prediction:
        assert image_bytes == _JPEG          # bytes crossed the wire intact
        return _STUB


class _UnloadableClassifier(_FakeClassifier):
    def load(self) -> bool:
        return False


def _write_jpeg(tmp_path):
    p = tmp_path / "capture.jpg"
    p.write_bytes(_JPEG)
    return p


def test_gpu_classifier_happy_path(monkeypatch, tmp_path):
    monkeypatch.setattr(inf_main, "BirdClassifier", _FakeClassifier)
    image = _write_jpeg(tmp_path)

    with run_server(inf_main.app) as base_url:
        clf = GPUServerClassifier(base_url)
        result = asyncio.run(clf.classify(image))

    assert result is not None
    assert result.common_name == "Northern Cardinal"
    assert result.scientific_name == "Cardinalis cardinalis"
    assert result.confidence == 0.9137
    assert result.tier_used == "gpu"


def test_gpu_classifier_returns_none_when_model_unavailable(monkeypatch, tmp_path):
    # load() → False means the server never gets a classifier and answers 503;
    # the Pi client must degrade to None so the pipeline falls through tiers.
    monkeypatch.setattr(inf_main, "BirdClassifier", _UnloadableClassifier)
    image = _write_jpeg(tmp_path)

    with run_server(inf_main.app) as base_url:
        clf = GPUServerClassifier(base_url)
        result = asyncio.run(clf.classify(image))

    assert result is None


class _SquirrelClassifier(_FakeClassifier):
    def classify(self, image_bytes: bytes) -> Prediction:
        return Prediction(
            common_name="Blue Jay",
            scientific_name="Cyanocitta cristata",
            confidence=0.03,
            animal=AnimalPrediction(
                common_name="Eastern Gray Squirrel",
                scientific_name="Sciurus carolinensis",
                group="squirrel",
                confidence=0.88,
            ),
        )


def test_gpu_classifier_reads_the_animal_field(monkeypatch, tmp_path):
    monkeypatch.setattr(inf_main, "BirdClassifier", _SquirrelClassifier)
    image = _write_jpeg(tmp_path)

    with run_server(inf_main.app) as base_url:
        result = asyncio.run(GPUServerClassifier(base_url).classify(image))

    # The bird fields are unchanged, so an old Pi build reads them as before.
    assert (result.common_name, result.confidence) == ("Blue Jay", 0.03)
    assert result.animal.group == "squirrel"
    assert result.animal.confidence == 0.88


def test_gpu_classifier_sees_no_animal_when_the_server_names_none(monkeypatch, tmp_path):
    monkeypatch.setattr(inf_main, "BirdClassifier", _FakeClassifier)
    image = _write_jpeg(tmp_path)

    with run_server(inf_main.app) as base_url:
        result = asyncio.run(GPUServerClassifier(base_url).classify(image))

    assert result.animal is None


def test_gpu_server_health_reports_model_ready(monkeypatch):
    import urllib.request

    monkeypatch.setattr(inf_main, "BirdClassifier", _FakeClassifier)
    with run_server(inf_main.app) as base_url:
        with urllib.request.urlopen(f"{base_url}/health") as resp:
            import json

            body = json.loads(resp.read())
    assert body["status"] == "ok"
    assert body["model_ready"] is True
    assert body["state"] == "ready"
