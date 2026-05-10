import logging
from pathlib import Path

import aiohttp

logger = logging.getLogger(__name__)


class BackendClient:
    """Async HTTP client for the Peck Deck backend API."""

    def __init__(
        self,
        base_url: str,
        device_token: str,
        connect_timeout: int = 10,
        upload_timeout: int = 60,
    ):
        self._base = base_url.rstrip("/")
        self._token = device_token
        self._short_timeout = aiohttp.ClientTimeout(total=connect_timeout)
        self._upload_timeout = aiohttp.ClientTimeout(
            connect=connect_timeout, total=upload_timeout
        )

    def _auth(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self._token}"}

    async def is_reachable(self) -> bool:
        try:
            async with aiohttp.ClientSession(timeout=self._short_timeout) as session:
                async with session.get(f"{self._base}/health") as resp:
                    return resp.status < 500
        except Exception:
            return False

    async def post_sighting(
        self,
        *,
        image_path: Path,
        timestamp: str,
        common_name: str,
        scientific_name: str,
        confidence: float,
        tier_used: str,
        delayed: bool = False,
    ) -> bool:
        """Upload image + sighting metadata in a single multipart POST.

        Returns True on HTTP 200/201, False on any failure.
        """
        try:
            async with aiohttp.ClientSession(timeout=self._upload_timeout) as session:
                with open(image_path, "rb") as fh:
                    form = aiohttp.FormData()
                    form.add_field(
                        "image", fh,
                        filename=image_path.name,
                        content_type="image/jpeg",
                    )
                    form.add_field("timestamp", timestamp)
                    form.add_field("common_name", common_name)
                    form.add_field("scientific_name", scientific_name)
                    form.add_field("confidence_score", str(confidence))
                    form.add_field("classification_tier_used", tier_used)
                    form.add_field("delayed", str(delayed).lower())

                    async with session.post(
                        f"{self._base}/sightings",
                        data=form,
                        headers=self._auth(),
                    ) as resp:
                        if resp.status not in (200, 201):
                            logger.warning("POST /sightings returned HTTP %d", resp.status)
                            return False
                        return True
        except aiohttp.ClientError:
            logger.warning("POST /sightings failed: backend unreachable")
            return False
        except Exception:
            logger.exception("Unexpected error posting sighting")
            return False
