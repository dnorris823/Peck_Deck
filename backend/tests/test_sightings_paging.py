"""History pages through GET /sightings by timestamp, then by offset.

The web app asks for the next page with ``to_date`` set to the oldest row it
holds and ``offset`` set to how many rows it holds at that exact time. That
only works if rows sharing a timestamp come back in the same order on every
request, so the list breaks ties by id.

The rows go on a fresh device owned by a throwaway user, so the exact counts in
``test_sightings.py`` stay stable whatever the test order.
"""
import asyncio
import secrets
from datetime import datetime, timezone

from backend.auth.jwt_utils import create_user_token
from backend.database.connection import get_session_factory
from backend.database.models import Device, Sighting, User
from backend.tests.conftest import IDS

_AT = datetime(2026, 10, 3, 7, 30, tzinfo=timezone.utc)


async def _make_tied_sightings() -> dict:
    async with get_session_factory()() as db:
        async with db.begin():
            user = User(
                name="Paging Owner",
                email=f"paging_{secrets.token_hex(4)}@test.dev",
                password_hash="x",
                role="owner",
                notify_email=False,
            )
            db.add(user)
            await db.flush()
            device = Device(name="Paging Device", owner_id=user.id, token=secrets.token_urlsafe(12))
            db.add(device)
            await db.flush()
            rows = [
                Sighting(
                    species_id=IDS["spA_id"],
                    device_id=device.id,
                    datetime=_AT,
                    classification_tier_used="gpu",
                    confidence_score=0.9,
                )
                for _ in range(4)
            ]
            db.add_all(rows)
            await db.flush()
            return {"user_id": user.id, "device_id": device.id, "ids": [s.id for s in rows]}


def test_rows_with_one_timestamp_page_in_id_order(client):
    made = asyncio.run(_make_tied_sightings())
    headers = {"Authorization": f"Bearer {create_user_token(made['user_id'], 'owner')}"}
    at = _AT.isoformat()

    seen = []
    for offset in range(4):
        res = client.get(
            "/sightings",
            params={"device_id": made["device_id"], "to_date": at, "limit": 1, "offset": offset},
            headers=headers,
        )
        assert res.status_code == 200
        seen += [s["id"] for s in res.json()]

    assert seen == sorted(made["ids"], reverse=True)
