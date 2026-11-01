import asyncio
import logging
from pathlib import Path

import aiohttp

from .base import AnimalAnswer, ClassificationResult, ClassifierBase

logger = logging.getLogger(__name__)


def _animal(raw) -> AnimalAnswer | None:
    """The ``animal`` field of the reply. An older server sends none.

    A malformed field is dropped, so the bird answer still counts.
    """
    if not isinstance(raw, dict):
        return None
    try:
        return AnimalAnswer(
            common_name=str(raw["common_name"]),
            scientific_name=str(raw["scientific_name"]),
            group=str(raw["group"]),
            confidence=float(raw["confidence"]),
        )
    except (KeyError, TypeError, ValueError):
        logger.warning("GPU server sent a malformed animal field: %.200r", raw)
        return None


class GPUServerClassifier(ClassifierBase):
    """Tier 2 — LAN GPU inference server (POST /classify → JSON prediction)."""

    def __init__(self, server_url: str, timeout_seconds: int = 30):
        self._url = server_url.rstrip("/") + "/classify"
        self._timeout = aiohttp.ClientTimeout(total=timeout_seconds)

    @property
    def tier_name(self) -> str:
        return "gpu"

    async def classify(self, image_path: Path) -> ClassificationResult | None:
        try:
            async with aiohttp.ClientSession(timeout=self._timeout) as session:
                with open(image_path, "rb") as fh:
                    form = aiohttp.FormData()
                    form.add_field(
                        "image", fh,
                        filename=image_path.name,
                        content_type="image/jpeg",
                    )
                    async with session.post(self._url, data=form) as resp:
                        if resp.status != 200:
                            logger.warning("GPU server returned HTTP %d", resp.status)
                            return None
                        data = await resp.json()
                        return ClassificationResult(
                            common_name=data["common_name"],
                            scientific_name=data["scientific_name"],
                            confidence=float(data["confidence"]),
                            tier_used="gpu",
                            animal=_animal(data.get("animal")),
                        )
        except asyncio.TimeoutError:
            logger.warning("GPU server timed out (%s)", image_path.name)
            return None
        except aiohttp.ClientError:
            logger.warning("GPU server unreachable")
            return None
        except Exception:
            logger.exception("Unexpected error calling GPU server")
            return None
