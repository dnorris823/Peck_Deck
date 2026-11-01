from backend.tests.conftest import IDS


def test_dashboard_owner(client, owner_headers):
    d = client.get("/stats/dashboard", headers=owner_headers).json()
    assert d["today_sightings"] == 5
    assert d["species_this_week"] == 2          # species A and B in last 7d
    assert d["most_frequent"] == "Test Cardinal"
    assert d["most_frequent_count"] == 4         # 3 on dev1 + 1 on dev2
    assert d["total_species"] == 2               # species with any sightings
    assert d["total_devices"] == 3
    assert d["avg_confidence"] is not None
    # sparklines: 7 points, today's bucket matches today's count, sum == week
    assert len(d["spark_sightings"]) == 7
    assert d["spark_sightings"][-1] == 5
    assert sum(d["spark_sightings"]) == 6        # 5 today + 1 three days ago


def test_species_counts_owner_ordering(client, owner_headers):
    rows = client.get("/stats/species-counts", headers=owner_headers).json()
    assert [r["common_name"] for r in rows] == ["Test Cardinal", "Test Jay"]
    assert rows[0]["count"] == 4
    assert rows[1]["count"] == 2
    assert rows[0]["first_seen"] is not None
    assert rows[0]["last_seen"] is not None
    assert rows[0]["peak_hours"] is None       # no tz sent
    # Test Wren has no sightings and must not appear
    assert "Test Wren" not in [r["common_name"] for r in rows]


def test_heatmap_shape_and_total(client, owner_headers):
    grid = client.get("/stats/heatmap", headers=owner_headers).json()
    assert len(grid) == 7
    assert all(len(row) == 24 for row in grid)
    assert sum(sum(row) for row in grid) == 6    # all six sightings in last 7d


def test_stats_scoped_to_viewer(client, viewer_headers):
    d = client.get("/stats/dashboard", headers=viewer_headers).json()
    assert d["today_sightings"] == 5
    assert d["total_devices"] == 1               # viewer only accesses dev1
    assert d["most_frequent_count"] == 3         # dev2 sighting not visible

    rows = client.get("/stats/species-counts", headers=viewer_headers).json()
    assert rows[0]["count"] == 3                 # Cardinal, dev1 only


# ── Scoped to one feeder (device_id) ──────────────────────────────────────


def _get(client, path, headers, device_id):
    return client.get(path, params={"device_id": device_id}, headers=headers).json()


def test_dashboard_scoped_to_one_feeder(client, owner_headers):
    one = _get(client, "/stats/dashboard", owner_headers, IDS["dev1_id"])
    assert one["today_sightings"] == 5
    assert one["most_frequent_count"] == 3       # dev2's cardinal left out
    assert one["total_devices"] == 1
    assert sum(one["spark_sightings"]) == 5

    two = _get(client, "/stats/dashboard", owner_headers, IDS["dev2_id"])
    assert two["today_sightings"] == 0
    assert two["most_frequent"] == "Test Cardinal"
    assert two["most_frequent_count"] == 1
    assert two["total_species"] == 1
    assert sum(two["spark_sightings"]) == 1


def test_species_counts_scoped_to_one_feeder(client, owner_headers):
    one = _get(client, "/stats/species-counts", owner_headers, IDS["dev1_id"])
    assert [(r["common_name"], r["count"]) for r in one] == [("Test Cardinal", 3), ("Test Jay", 2)]

    two = _get(client, "/stats/species-counts", owner_headers, IDS["dev2_id"])
    assert [(r["common_name"], r["count"]) for r in two] == [("Test Cardinal", 1)]


def test_heatmap_scoped_to_one_feeder(client, owner_headers):
    one = _get(client, "/stats/heatmap", owner_headers, IDS["dev1_id"])
    two = _get(client, "/stats/heatmap", owner_headers, IDS["dev2_id"])
    assert sum(map(sum, one)) == 5
    assert sum(map(sum, two)) == 1


def test_hours_scoped_to_one_feeder(client, owner_headers):
    params = {"days": 30, "tz": "UTC"}
    one = client.get("/stats/hours", params={**params, "device_id": IDS["dev1_id"]},
                     headers=owner_headers).json()
    two = client.get("/stats/hours", params={**params, "device_id": IDS["dev2_id"]},
                     headers=owner_headers).json()
    assert one["total"] == 5
    assert two["total"] == 1


def test_a_feeder_the_viewer_cannot_see_scopes_to_nothing(client, viewer_headers):
    d = _get(client, "/stats/dashboard", viewer_headers, IDS["dev2_id"])
    assert d["total_devices"] == 0
    assert d["most_frequent_count"] == 0
    assert _get(client, "/stats/species-counts", viewer_headers, IDS["dev2_id"]) == []
    assert sum(map(sum, _get(client, "/stats/heatmap", viewer_headers, IDS["dev2_id"]))) == 0
