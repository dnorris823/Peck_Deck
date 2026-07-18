"""Tests for Tier 3 cloud classification (POST /classify).

The Anthropic client is never hit — we either exercise the no-key/no-image
guards, or inject a fake classifier / fake Anthropic client so no network or
API key is needed.
"""
import asyncio
import json
import types

from backend import main as main_module
from backend.classification.claude import ClaudeClassifier
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
