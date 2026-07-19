"""Task 3.2a — Contract test for the Pi ↔ backend seam.

Drives the **real** Raspberry Pi client (``raspberry_pi_code.api_client.
BackendClient``) against a **live** backend server (uvicorn + Postgres). This
proves the multipart ``POST /sightings`` contract end to end: the exact field
names the Pi sends, device-token auth, and the image bytes landing in the DB —
none of it mocked on either side of the wire.
"""
import asyncio

from raspberry_pi_code.api_client import BackendClient

from backend.main import app
from integration_tests._dbutil import create_throwaway_device, sightings_for_device
from integration_tests._live import run_server

_JPEG = b"\xff\xd8\xff\xe0" + b"pi-contract-image" * 32


def _write_jpeg(tmp_path):
    p = tmp_path / "capture.jpg"
    p.write_bytes(_JPEG)
    return p


def test_pi_client_uploads_sighting_over_http(ids, tmp_path):
    token, device_id = create_throwaway_device("pi-upload")
    image = _write_jpeg(tmp_path)

    with run_server(app) as base_url:
        client = BackendClient(base_url, token)

        # /health probe the Pi uses to decide reachability.
        assert asyncio.run(client.is_reachable()) is True

        ok = asyncio.run(
            client.post_sighting(
                image_path=image,
                timestamp="2026-07-19T10:30:00+00:00",
                # Matches a seeded species so the fire-and-forget wiki backfill
                # is skipped (keeps the test hermetic — no outbound Wikipedia call).
                common_name="Test Cardinal",
                scientific_name="Cardinalis testus",
                confidence=0.87,
                tier_used="gpu",
                delayed=False,
            )
        )
        assert ok is True

    # The seam delivered: exactly one sighting, image bytes intact in Postgres.
    rows = sightings_for_device(device_id)
    assert len(rows) == 1
    row = rows[0]
    assert row["confidence_score"] == 0.87
    assert row["classification_tier_used"] == "gpu"
    assert row["delayed"] is False
    assert row["has_image"] is True
    assert row["image_len"] == len(_JPEG)


def test_pi_client_offline_sync_marks_delayed(ids, tmp_path):
    """The offline-sync path uploads queued captures with delayed=True."""
    token, device_id = create_throwaway_device("pi-sync")
    image = _write_jpeg(tmp_path)

    with run_server(app) as base_url:
        client = BackendClient(base_url, token)
        ok = asyncio.run(
            client.post_sighting(
                image_path=image,
                timestamp="2026-07-18T22:05:00+00:00",
                common_name="Test Jay",
                scientific_name="Cyanocitta testus",
                confidence=0.66,
                tier_used="local",
                delayed=True,
            )
        )
        assert ok is True

    rows = sightings_for_device(device_id)
    assert len(rows) == 1
    assert rows[0]["delayed"] is True


def test_pi_client_rejects_bad_device_token(ids, tmp_path):
    """A bogus device token is refused by device_guard → client reports failure."""
    image = _write_jpeg(tmp_path)
    with run_server(app) as base_url:
        client = BackendClient(base_url, "not-a-real-device-token")
        ok = asyncio.run(
            client.post_sighting(
                image_path=image,
                timestamp="2026-07-19T10:30:00+00:00",
                common_name="Test Cardinal",
                scientific_name="Cardinalis testus",
                confidence=0.5,
                tier_used="gpu",
            )
        )
        assert ok is False
