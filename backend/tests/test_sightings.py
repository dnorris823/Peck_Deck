from backend.tests.conftest import IDS


def test_owner_sees_all_sightings(client, owner_headers):
    res = client.get("/sightings?limit=100", headers=owner_headers)
    assert res.status_code == 200
    data = res.json()
    assert len(data) == 6  # 5 on dev1 + 1 on dev2
    # returned most-recent first
    times = [s["datetime"] for s in data]
    assert times == sorted(times, reverse=True)


def test_viewer_scoped_to_member_device(client, viewer_headers):
    res = client.get("/sightings?limit=100", headers=viewer_headers)
    assert res.status_code == 200
    data = res.json()
    assert len(data) == 5  # only dev1
    assert all(s["device_id"] == IDS["dev1_id"] for s in data)


def test_filter_by_species(client, owner_headers):
    res = client.get(f"/sightings?species_id={IDS['spB_id']}&limit=100", headers=owner_headers)
    assert res.status_code == 200
    data = res.json()
    assert len(data) == 2
    assert all(s["species_id"] == IDS["spB_id"] for s in data)


def test_get_one_sighting(client, owner_headers):
    listing = client.get("/sightings?limit=1", headers=owner_headers).json()
    sid = listing[0]["id"]
    res = client.get(f"/sightings/{sid}", headers=owner_headers)
    assert res.status_code == 200
    assert res.json()["id"] == sid
    assert res.json()["has_image"] is False


def test_image_missing_returns_404(client, owner_headers):
    listing = client.get("/sightings?limit=1", headers=owner_headers).json()
    sid = listing[0]["id"]
    res = client.get(f"/sightings/{sid}/image", headers=owner_headers)
    assert res.status_code == 404  # seeded sightings have no image_data
