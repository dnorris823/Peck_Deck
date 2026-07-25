import logging
from enum import Enum
from pathlib import Path

import aiohttp

logger = logging.getLogger(__name__)


class UploadOutcome(Enum):
    """Why an upload finished the way it did.

    A bare ``bool`` collapsed "the network is down" into the same answer as
    "this device token is refused", so the pipeline queued a permanently
    rejected sighting and retried it forever while logging *"backend
    unreachable"* — sending the operator to debug a network that was fine.

    ``__bool__`` keeps ``if ok:`` reading correctly at every call site.
    """

    OK = "ok"
    RETRY = "retry"                # transient (network, 5xx, 429) — try again later
    UNAUTHORIZED = "unauthorized"  # token refused — keep the data, re-provision the token
    REJECTED = "rejected"          # the request itself is bad — retrying cannot help

    def __bool__(self) -> bool:
        return self is UploadOutcome.OK


def _classify_status(status: int) -> UploadOutcome:
    if status in (200, 201):
        return UploadOutcome.OK
    if status in (401, 403):
        return UploadOutcome.UNAUTHORIZED
    # 429 and 5xx are worth another attempt; other 4xx mean the payload or the
    # route is wrong, and replaying it just poisons the offline queue.
    if status == 429 or status >= 500:
        return UploadOutcome.RETRY
    return UploadOutcome.REJECTED


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
    ) -> UploadOutcome:
        """Upload image + sighting metadata in a single multipart POST.

        Returns an :class:`UploadOutcome`; it is falsy for every failure, so
        callers that only care whether it worked can still just test it.
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
                        outcome = _classify_status(resp.status)
                        if outcome is UploadOutcome.UNAUTHORIZED:
                            logger.error(
                                "POST /sightings refused this device token (HTTP %d) — "
                                "re-provision DEVICE_TOKEN; uploads cannot succeed until then",
                                resp.status,
                            )
                        elif outcome is not UploadOutcome.OK:
                            logger.warning("POST /sightings returned HTTP %d", resp.status)
                        return outcome
        except aiohttp.ClientError:
            logger.warning("POST /sightings failed: backend unreachable")
            return UploadOutcome.RETRY
        except Exception:
            logger.exception("Unexpected error posting sighting")
            return UploadOutcome.RETRY
