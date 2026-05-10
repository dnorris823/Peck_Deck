import logging
from pathlib import Path

import aiohttp

from .base import ClassificationResult, ClassifierBase

logger = logging.getLogger(__name__)


class CloudClassifier(ClassifierBase):
    """Tier 3 — cloud classification via backend relay to Claude API.

    The Pi sends the image to the backend's /classify endpoint;
    the backend calls the Claude multimodal API and returns a prediction.
    The API key never leaves the gaming PC.
    """

    def __init__(self, backend_url: str, device_token: str, timeout_seconds: int = 60):
        self._url = backend_url.rstrip("/") + "/classify"
        self._token = device_token
        self._timeout = aiohttp.ClientTimeout(total=timeout_seconds)

    @property
    def tier_name(self) -> str:
        return "cloud"

    async def classify(self, image_path: Path) -> ClassificationResult | None:
        headers = {"Authorization": f"Bearer {self._token}"}
        try:
            async with aiohttp.ClientSession(timeout=self._timeout) as session:
                with open(image_path, "rb") as fh:
                    form = aiohttp.FormData()
                    form.add_field(
                        "image", fh,
                        filename=image_path.name,
                        content_type="image/jpeg",
                    )
                    async with session.post(self._url, data=form, headers=headers) as resp:
                        if resp.status != 200:
                            logger.warning("Cloud classify returned HTTP %d", resp.status)
                            return None
                        data = await resp.json()
                        return ClassificationResult(
                            common_name=data["common_name"],
                            scientific_name=data["scientific_name"],
                            confidence=float(data["confidence"]),
                            tier_used="cloud",
                        )
        except aiohttp.ClientError:
            logger.warning("Backend unreachable for cloud classification")
            return None
        except Exception:
            logger.exception("Unexpected error during cloud classification")
            return None
