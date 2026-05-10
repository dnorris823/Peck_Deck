import asyncio
import logging
from pathlib import Path

import aiohttp

from .base import ClassificationResult, ClassifierBase

logger = logging.getLogger(__name__)


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
