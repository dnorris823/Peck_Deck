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
