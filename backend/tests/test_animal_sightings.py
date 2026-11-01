"""Animal sightings: a squirrel Tier 2 named, uploaded with kind=animal.

An animal visit is a sighting like any other, with a species row whose kind is
"animal". It stays out of every bird count and bird stat, and it sends no bird
alert. Each test uploads to a fresh device owned by a fresh user, so the exact
counts in test_stats.py hold in any order.
"""
import asyncio
import secrets
from datetime import datetime, timezone

from sqlalchemy import select

import backend.sightings.aftercare as sighting_aftercare
from backend.auth.jwt_utils import create_user_token
from backend.database.connection import get_session_factory
from backend.database.models import Device, Sighting, Species, User
from backend.notifications import service as notif_module
from backend.notifications.service import NotificationService

_JPEG = b"\xff\xd8\xff\xe0animal-bytes"


async def _station() -> dict:
    async with get_session_factory()() as db:
        async with db.begin():
            u = User(
                name="Animal Owner",
                email=f"animal_{secrets.token_hex(4)}@test.dev",
                password_hash="x",
                role="owner",
                notify_email=True,
            )
            db.add(u)
            await db.flush()
            d = Device(name="Animal Feeder", owner_id=u.id, token=secrets.token_urlsafe(12))
            db.add(d)
            await db.flush()
            return {"user_id": u.id, "device_id": d.id, "token": d.token, "email": u.email}


def _silence(monkeypatch):
    async def _noop(*_a, **_k):
        return None

    monkeypatch.setattr(sighting_aftercare.notification_service, "dispatch", _noop)
    monkeypatch.setattr(sighting_aftercare, "enrich_species", _noop)


def _user(station) -> dict:
    return {"Authorization": f"Bearer {create_user_token(station['user_id'], 'owner')}"}


def _upload(client, station, *, common, sci, **extra):
    data = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "common_name": common,
        "scientific_name": sci,
        "confidence_score": "0.81",
        "classification_tier_used": "gpu",
        **extra,
    }
    return client.post(
        "/sightings",
        headers={"Authorization": f"Bearer {station['token']}"},
        data=data,
        files={"image": ("capture.jpg", _JPEG, "image/jpeg")},
    )


def _squirrel(client, station, name="Eastern Gray Squirrel"):
    return _upload(client, station, common=name, sci="Sciurus carolinensis",
                   kind="animal", animal_group="squirrel")


async def _species(species_id: int) -> Species:
    async with get_session_factory()() as db:
        return (await db.execute(select(Species).where(Species.id == species_id))).scalar_one()


# ── Upload ──────────────────────────────────────────────────────────────────

def test_an_animal_upload_creates_an_animal_species_row(client, monkeypatch):
    _silence(monkeypatch)
    station = asyncio.run(_station())
    name = f"Squirrel {secrets.token_hex(3)}"

    res = _squirrel(client, station, name)

    assert res.status_code == 201
    species = asyncio.run(_species(res.json()["species_id"]))
    assert (species.kind, species.animal_group) == ("animal", "squirrel")

    body = client.get(f"/species/{species.id}", headers=_user(station)).json()
    assert body["kind"] == "animal"
    assert body["animal_group"] == "squirrel"


def test_an_upload_with_no_kind_is_a_bird(client, monkeypatch):
    # What every Pi build from before animals sends.
    _silence(monkeypatch)
    station = asyncio.run(_station())

    res = _upload(client, station, common=f"Jay {secrets.token_hex(3)}", sci="Cyanocitta cristata")

    species = asyncio.run(_species(res.json()["species_id"]))
    assert (species.kind, species.animal_group) == ("bird", None)


def test_a_bad_kind_records_a_bird_rather_than_rejecting_the_photo(client, monkeypatch):
    # A 4xx makes the Pi drop the visit for good.
    _silence(monkeypatch)
    station = asyncio.run(_station())

    odd = _upload(client, station, common=f"Odd {secrets.token_hex(3)}", sci="Odd one", kind="lizard")
    no_group = _upload(client, station, common=f"Nog {secrets.token_hex(3)}", sci="No group", kind="animal")

    for res in (odd, no_group):
        assert res.status_code == 201
        assert asyncio.run(_species(res.json()["species_id"])).kind == "bird"


def test_an_old_pi_never_turns_an_animal_back_into_a_bird(client, monkeypatch):
    _silence(monkeypatch)
    station = asyncio.run(_station())
    name = f"Squirrel {secrets.token_hex(3)}"
    first = _squirrel(client, station, name).json()

    again = _upload(client, station, common=name, sci="Sciurus carolinensis").json()

    assert again["species_id"] == first["species_id"]
    assert asyncio.run(_species(first["species_id"])).kind == "animal"


def test_an_animal_upload_turns_a_bird_row_of_that_name_into_an_animal(client, monkeypatch):
    _silence(monkeypatch)
    station = asyncio.run(_station())
    name = f"Squirrel {secrets.token_hex(3)}"
    bird = _upload(client, station, common=name, sci="Sciurus carolinensis").json()

    _squirrel(client, station, name)

    species = asyncio.run(_species(bird["species_id"]))
    assert (species.kind, species.animal_group) == ("animal", "squirrel")


# ── Bird counts leave animals out ───────────────────────────────────────────

def _two_birds_three_squirrels(client, monkeypatch) -> dict:
    _silence(monkeypatch)
    station = asyncio.run(_station())
    bird = f"Cardinal {secrets.token_hex(3)}"
    for _ in range(2):
        assert _upload(client, station, common=bird, sci="Cardinalis cardinalis").status_code == 201
    for _ in range(3):
        res = _squirrel(client, station)
        assert res.status_code == 201
    station["bird"] = bird
    station["squirrel_id"] = res.json()["species_id"]
    return station


def test_species_counts_list_birds_only(client, monkeypatch):
    station = _two_birds_three_squirrels(client, monkeypatch)

    rows = client.get("/stats/species-counts", params={"tz": "UTC"}, headers=_user(station)).json()

    assert [(r["common_name"], r["count"]) for r in rows] == [(station["bird"], 2)]


def test_dashboard_heatmap_and_hours_count_birds_only(client, monkeypatch):
    station = _two_birds_three_squirrels(client, monkeypatch)
    headers = _user(station)

    dash = client.get("/stats/dashboard", headers=headers).json()
    heat = client.get("/stats/heatmap", headers=headers).json()
    hours = client.get("/stats/hours", headers=headers).json()

    assert dash["today_sightings"] == 2
    assert dash["species_this_week"] == 1
    assert dash["total_species"] == 1
    assert dash["most_frequent"] == station["bird"]
    assert sum(map(sum, heat)) == 2
    assert hours["total"] == 2


def test_a_feeder_card_counts_birds_only(client, monkeypatch):
    station = _two_birds_three_squirrels(client, monkeypatch)

    [device] = client.get("/devices", headers=_user(station)).json()

    assert device["today_sightings"] == 2
    assert device["all_time_sightings"] == 2
    # The tier mix is about Tier 2's health, and a squirrel proves Tier 2 is up.
    assert device["tier_mix"]["gpu"] == 5


def test_history_and_export_keep_animal_visits(client, monkeypatch):
    station = _two_birds_three_squirrels(client, monkeypatch)
    headers = _user(station)

    history = client.get("/sightings", headers=headers).json()
    export = client.get("/sightings/export", params={"fmt": "json"}, headers=headers).json()

    assert len(history) == 5
    assert sorted(r["kind"] for r in export) == ["animal"] * 3 + ["bird"] * 2


def test_hours_for_one_animal_species_still_answers(client, monkeypatch):
    # The bird filter applies to the all-species dial, not to a species asked for by id.
    station = _two_birds_three_squirrels(client, monkeypatch)

    hours = client.get(
        "/stats/hours", params={"species_id": station["squirrel_id"]}, headers=_user(station)
    ).json()

    assert hours["total"] == 3


# ── Alerts ──────────────────────────────────────────────────────────────────

async def _sighting(species_id: int, device_id: int) -> int:
    async with get_session_factory()() as db:
        async with db.begin():
            s = Sighting(
                species_id=species_id, device_id=device_id,
                datetime=datetime.now(timezone.utc), confidence_score=0.8,
                classification_tier_used="gpu", delayed=False,
            )
            db.add(s)
            await db.flush()
            return s.id


async def _new_species(kind: str, group: str | None) -> int:
    async with get_session_factory()() as db:
        async with db.begin():
            sp = Species(
                common_name=f"Notif {kind} {secrets.token_hex(3)}", genus="G", species_name="s",
                kind=kind, animal_group=group,
            )
            db.add(sp)
            await db.flush()
            return sp.id


def test_an_animal_sends_no_alert_and_never_mutes_the_next_bird(client, monkeypatch):
    emails: list[str] = []

    async def fake_email(*, to_email, **_):
        emails.append(to_email)
        return True

    monkeypatch.setattr(notif_module, "send_email", fake_email)
    station = asyncio.run(_station())
    squirrel = asyncio.run(_new_species("animal", "squirrel"))
    cardinal = asyncio.run(_new_species("bird", None))
    svc = NotificationService(min_interval_seconds=3600)

    asyncio.run(svc.dispatch(asyncio.run(_sighting(squirrel, station["device_id"])), station["device_id"]))
    assert emails == []

    asyncio.run(svc.dispatch(asyncio.run(_sighting(cardinal, station["device_id"])), station["device_id"]))
    assert emails == [station["email"]], "the squirrel must not start the bird throttle"


def test_the_upload_keeps_what_made_the_pi_capture(client, monkeypatch):
    _silence(monkeypatch)
    station = asyncio.run(_station())

    motion = _squirrel(client, station).json()
    tagged = _upload(client, station, common=f"Jay {secrets.token_hex(3)}", sci="Cyanocitta cristata",
                     trigger="motion").json()
    odd = _upload(client, station, common=f"Jay {secrets.token_hex(3)}", sci="Cyanocitta cristata",
                  trigger="pir").json()

    assert motion["trigger"] is None  # an older Pi build sends none
    assert tagged["trigger"] == "motion"
    assert odd["trigger"] is None
