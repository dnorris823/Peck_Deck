"""Tier 3 cloud classification via the Claude multimodal API (M6).

The Pi sends a JPEG to the backend's ``POST /classify`` (guarded by a device
token); the backend relays it to Claude with a structured-output schema and
returns the exact 3-field contract the Pi client parses:

    {"common_name": str, "scientific_name": str, "confidence": float}

The Anthropic client is built lazily behind :func:`get_classifier` so the
module imports cleanly without the ``anthropic`` package or an API key present
(tests inject a fake classifier; production builds the real one on first use).
"""
import base64
import json
import logging
from typing import Protocol

from ..config import settings

logger = logging.getLogger(__name__)

# Structured-output schema — guarantees Claude's first text block is JSON with
# exactly these keys, so parsing is deterministic.
_CLASSIFY_SCHEMA = {
    "type": "object",
    "properties": {
        "common_name": {"type": "string"},
        "scientific_name": {"type": "string"},
        "confidence": {"type": "number"},
    },
    "required": ["common_name", "scientific_name", "confidence"],
    "additionalProperties": False,
}

_PROMPT = (
    "You are an expert ornithologist identifying a bird from a backyard feeder "
    "camera image. Identify the single most prominent bird. Provide its common "
    "name, its scientific name (Genus species), and your confidence from 0.0 to "
    "1.0. If no bird is clearly visible, use common_name \"Unknown\", "
    "scientific_name \"\", and a low confidence."
)


class Classifier(Protocol):
    async def classify(self, image_bytes: bytes, media_type: str = ...) -> dict: ...


class ClaudeClassifier:
    """Wraps an Anthropic async client behind the ``Classifier`` interface."""

    def __init__(self, client, model: str):
        self._client = client
        self._model = model

    async def classify(self, image_bytes: bytes, media_type: str = "image/jpeg") -> dict:
        b64 = base64.standard_b64encode(image_bytes).decode()
        response = await self._client.messages.create(
            model=self._model,
            max_tokens=1024,
            messages=[
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "image",
                            "source": {
                                "type": "base64",
                                "media_type": media_type,
                                "data": b64,
                            },
                        },
                        {"type": "text", "text": _PROMPT},
                    ],
                }
            ],
            output_config={"format": {"type": "json_schema", "schema": _CLASSIFY_SCHEMA}},
        )
        text = next(block.text for block in response.content if block.type == "text")
        data = json.loads(text)
        return {
            "common_name": str(data["common_name"]),
            "scientific_name": str(data["scientific_name"]),
            "confidence": float(data["confidence"]),
        }


def build_classifier() -> Classifier | None:
    """Build a real ClaudeClassifier, or None when no API key is configured."""
    if not settings.ANTHROPIC_API_KEY:
        return None
    from anthropic import AsyncAnthropic  # imported lazily — optional dependency

    client = AsyncAnthropic(api_key=settings.ANTHROPIC_API_KEY)
    return ClaudeClassifier(client, settings.ANTHROPIC_MODEL)


_classifier: Classifier | None = None
_built = False


def get_classifier() -> Classifier | None:
    """Return the process-wide classifier, building it once on first use."""
    global _classifier, _built
    if not _built:
        _classifier = build_classifier()
        _built = True
    return _classifier
