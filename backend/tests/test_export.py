"""GET /sightings/export — CSV/JSON download of sighting history."""
import csv
import io
import json

from backend.sightings.export import COLUMNS
from backend.tests.conftest import IDS


def _rows(csv_text: str) -> list[dict]:
    return list(csv.DictReader(io.StringIO(csv_text)))


def test_export_requires_auth(client):
    assert client.get("/sightings/export").status_code == 401


def test_csv_export_has_a_stable_header_and_all_rows(client, owner_headers):
    res = client.get("/sightings/export?fmt=csv", headers=owner_headers)

    assert res.status_code == 200
    assert res.headers["content-type"].startswith("text/csv")
    rows = _rows(res.text)
    assert list(rows[0].keys()) == COLUMNS
    assert len(rows) == 6


def test_export_is_served_as_an_attachment(client, owner_headers):
    res = client.get("/sightings/export?fmt=csv", headers=owner_headers)

    disposition = res.headers["content-disposition"]
    assert disposition.startswith("attachment;")
    assert ".csv" in disposition


def test_rows_are_self_describing(client, owner_headers):
    """Names, not bare foreign keys — the file has to be readable on its own."""
    rows = _rows(client.get("/sightings/export?fmt=csv", headers=owner_headers).text)

    row = rows[0]
    assert row["common_name"].startswith("Test ")
    assert row["scientific_name"]
    assert row["device_name"].startswith("Dev ")
    assert row["classification_tier_used"] in {"gpu", "local", "cloud"}


def test_json_export(client, owner_headers):
    res = client.get("/sightings/export?fmt=json", headers=owner_headers)

    assert res.status_code == 200
    assert res.headers["content-type"].startswith("application/json")
    payload = json.loads(res.text)
    assert len(payload) == 6
    assert set(payload[0]) == set(COLUMNS)


def test_export_is_scoped_to_accessible_devices(client, viewer_headers):
    """The viewer can't see dev2, so its sighting must not leak into the file."""
    rows = _rows(client.get("/sightings/export?fmt=csv", headers=viewer_headers).text)

    assert len(rows) == 5
    assert {r["device_name"] for r in rows} == {"Dev One"}


def test_device_and_species_filters(client, owner_headers):
    by_device = _rows(
        client.get(
            f"/sightings/export?fmt=csv&device_id={IDS['dev2_id']}", headers=owner_headers
        ).text
    )
    by_species = _rows(
        client.get(
            f"/sightings/export?fmt=csv&species_id={IDS['spB_id']}", headers=owner_headers
        ).text
    )

    assert len(by_device) == 1
    assert len(by_species) == 2
    assert {r["common_name"] for r in by_species} == {"Test Jay"}


def test_date_range_filter(client, owner_headers):
    from datetime import datetime, timedelta, timezone
    from urllib.parse import quote

    # quote() matters: the "+" in a UTC offset is decoded as a space in a query
    # string, so an unencoded timestamp fails ISO parsing with a 400.
    yesterday = quote((datetime.now(timezone.utc) - timedelta(days=1)).isoformat())
    rows = _rows(
        client.get(f"/sightings/export?fmt=csv&from_date={yesterday}", headers=owner_headers).text
    )

    # Excludes the sighting from three days ago.
    assert len(rows) == 5


def test_bad_format_is_rejected(client, owner_headers):
    res = client.get("/sightings/export?fmt=xlsx", headers=owner_headers)

    assert res.status_code == 400


def test_bad_date_is_rejected(client, owner_headers):
    res = client.get("/sightings/export?from_date=not-a-date", headers=owner_headers)

    assert res.status_code == 400


def test_image_bytes_are_not_inlined(client, owner_headers):
    """Rows carry a URL, not the payload — otherwise exports would be enormous."""
    res = client.get("/sightings/export?fmt=csv", headers=owner_headers)

    assert "image_url" in res.text
    assert len(res.text) < 100_000
