"""Tests for Tier 3 cloud classification (POST /classify).

The Anthropic client is never hit — we either exercise the no-key/no-image
guards, or inject a fake classifier / fake Anthropic client so no network or
API key is needed.
"""
import asyncio
import json
import os
import types

import pytest

from backend import main as main_module
from backend.classification.claude import (
    ClaudeClassifier,
    build_classifier,
    normalize_prediction,
)
from backend.tests.conftest import IDS  # noqa: F401  (ensures seeding import order)

_DEVICE_AUTH = {"Authorization": "Bearer dev1-token"}
_JPEG = b"\xff\xd8\xff\xe0fake-jpeg-bytes"


def test_classify_requires_device_token(client):
    res = client.post("/classify", files={"image": ("bird.jpg", _JPEG, "image/jpeg")})
    assert res.status_code == 401  # no device token


def test_classify_empty_image_returns_400(client):
    res = client.post(
        "/classify",
        headers=_DEVICE_AUTH,
        files={"image": ("bird.jpg", b"", "image/jpeg")},
    )
    assert res.status_code == 400


def test_classify_without_api_key_returns_503(client):
    # ANTHROPIC_API_KEY is unset in the test env → build_classifier() returns None.
    res = client.post(
        "/classify",
        headers=_DEVICE_AUTH,
        files={"image": ("bird.jpg", _JPEG, "image/jpeg")},
    )
    assert res.status_code == 503


def test_classify_success_maps_response(client, monkeypatch):
    class _FakeClassifier:
        async def classify(self, image_bytes, media_type="image/jpeg"):
            assert image_bytes == _JPEG
            return {
                "common_name": "Northern Cardinal",
                "scientific_name": "Cardinalis cardinalis",
                "confidence": 0.92,
            }

    monkeypatch.setattr(main_module, "get_classifier", lambda: _FakeClassifier())
    res = client.post(
        "/classify",
        headers=_DEVICE_AUTH,
        files={"image": ("bird.jpg", _JPEG, "image/jpeg")},
    )
    assert res.status_code == 200
    assert res.json() == {
        "common_name": "Northern Cardinal",
        "scientific_name": "Cardinalis cardinalis",
        "confidence": 0.92,
    }


def test_claude_classifier_builds_request_and_maps_response():
    """Unit-test ClaudeClassifier against a fake Anthropic async client."""
    captured = {}

    async def fake_create(**kwargs):
        captured.update(kwargs)
        text = json.dumps(
            {
                "common_name": "Blue Jay",
                "scientific_name": "Cyanocitta cristata",
                "confidence": 0.81,
            }
        )
        block = types.SimpleNamespace(type="text", text=text)
        return types.SimpleNamespace(content=[block])

    fake_client = types.SimpleNamespace(
        messages=types.SimpleNamespace(create=fake_create)
    )
    classifier = ClaudeClassifier(fake_client, "claude-opus-4-8")

    result = asyncio.run(classifier.classify(_JPEG))

    # Response mapping
    assert result == {
        "common_name": "Blue Jay",
        "scientific_name": "Cyanocitta cristata",
        "confidence": 0.81,
    }
    # Request shape: correct model + a base64 image block is present
    assert captured["model"] == "claude-opus-4-8"
    content = captured["messages"][0]["content"]
    image_block = next(b for b in content if b["type"] == "image")
    assert image_block["source"]["type"] == "base64"
    assert image_block["source"]["media_type"] == "image/jpeg"
    assert image_block["source"]["data"]  # non-empty base64
    # Structured-output schema is requested so parsing is deterministic
    assert captured["output_config"]["format"]["type"] == "json_schema"
    # Schema bounds confidence to [0, 1] so out-of-range values can't slip through.
    conf_schema = captured["output_config"]["format"]["schema"]["properties"]["confidence"]
    assert conf_schema["minimum"] == 0.0 and conf_schema["maximum"] == 1.0


# ---------------------------------------------------------------------------
# JSON-contract enforcement: normalize_prediction is the single choke point
# that guarantees {common_name: str, scientific_name: str, confidence: float}.
# ---------------------------------------------------------------------------
def test_normalize_clamps_confidence_range():
    assert normalize_prediction(
        {"common_name": "X", "scientific_name": "X y", "confidence": 1.7}
    )["confidence"] == 1.0
    assert normalize_prediction(
        {"common_name": "X", "scientific_name": "X y", "confidence": -0.4}
    )["confidence"] == 0.0


def test_normalize_coerces_and_strips():
    out = normalize_prediction(
        {"common_name": "  Blue Jay  ", "scientific_name": " Cyanocitta cristata ", "confidence": "0.5"}
    )
    assert out == {
        "common_name": "Blue Jay",
        "scientific_name": "Cyanocitta cristata",
        "confidence": 0.5,
    }


def test_normalize_handles_missing_and_blank_fields():
    out = normalize_prediction({"common_name": "   "})
    assert out["common_name"] == "Unknown"   # blank → Unknown
    assert out["scientific_name"] == ""        # missing → empty
    assert out["confidence"] == 0.0            # missing → 0.0


def test_normalize_bad_confidence_falls_back_to_zero():
    out = normalize_prediction(
        {"common_name": "X", "scientific_name": "X y", "confidence": "not-a-number"}
    )
    assert out["confidence"] == 0.0


def test_classifier_clamps_out_of_range_model_output():
    """Even if the model returns confidence > 1, the client returns a valid contract."""
    async def fake_create(**_):
        text = json.dumps(
            {"common_name": "American Robin", "scientific_name": "Turdus migratorius", "confidence": 4.2}
        )
        block = types.SimpleNamespace(type="text", text=text)
        return types.SimpleNamespace(content=[block])

    fake_client = types.SimpleNamespace(messages=types.SimpleNamespace(create=fake_create))
    result = asyncio.run(ClaudeClassifier(fake_client, "claude-opus-4-8").classify(_JPEG))
    assert result["confidence"] == 1.0
    assert set(result) == {"common_name", "scientific_name", "confidence"}


def test_classifier_raises_when_no_text_block():
    async def fake_create(**_):
        block = types.SimpleNamespace(type="image", text=None)
        return types.SimpleNamespace(content=[block])

    fake_client = types.SimpleNamespace(messages=types.SimpleNamespace(create=fake_create))
    try:
        asyncio.run(ClaudeClassifier(fake_client, "claude-opus-4-8").classify(_JPEG))
        assert False, "expected ValueError"
    except ValueError:
        pass


# ---------------------------------------------------------------------------
# Opt-in live test — exercises the real Claude API. Skipped by default; runs
# only when RUN_LIVE_CLAUDE=1 and ANTHROPIC_API_KEY are set (never in CI).
# ---------------------------------------------------------------------------
@pytest.mark.skipif(
    os.getenv("RUN_LIVE_CLAUDE") != "1" or not os.getenv("ANTHROPIC_API_KEY"),
    reason="Set RUN_LIVE_CLAUDE=1 and ANTHROPIC_API_KEY to hit the real Claude API",
)
def test_live_claude_returns_valid_contract():
    import pathlib

    classifier = build_classifier()
    assert classifier is not None, "build_classifier() returned None despite an API key"

    # A tiny solid-color JPEG is enough to assert the contract shape (not accuracy).
    sample = pathlib.Path(__file__).parent / "fixtures" / "sample_bird.jpg"
    image = sample.read_bytes() if sample.exists() else _JPEG

    result = asyncio.run(classifier.classify(image))
    assert set(result) == {"common_name", "scientific_name", "confidence"}
    assert isinstance(result["common_name"], str) and result["common_name"]
    assert isinstance(result["scientific_name"], str)
    assert isinstance(result["confidence"], float)
    assert 0.0 <= result["confidence"] <= 1.0
