"""GET /stats/insights — analytics over a selectable window (FLEDGE Phase 6).

Asserted against the deterministic fixture dataset (backend/fixtures.py):
6 sightings total — 5 today on dev1 (3× Test Cardinal, 2× Test Jay) and
1 three days ago on dev2, which the viewer cannot see.
"""
from backend.tests.conftest import IDS


def test_insights_requires_auth(client):
    assert client.get("/stats/insights").status_code == 401


def test_window_totals_for_the_owner(client, owner_headers):
    body = client.get("/stats/insights?days=30", headers=owner_headers).json()

    assert body["days"] == 30
    assert body["total_sightings"] == 6      # all fixture sightings inside 30 days
    assert body["distinct_species"] == 2     # Cardinal + Jay (Wren never seen)
    assert len(body["day_labels"]) == 30
    assert len(body["per_day"]) == 30
    assert len(body["hours"]) == 24


def test_per_day_series_puts_todays_visits_last(client, owner_headers):
    body = client.get("/stats/insights?days=7", headers=owner_headers).json()

    # Index -1 is today: the 5 dev1 sightings. Index -4 is three days ago: 1.
    assert body["per_day"][-1] == 5
    assert body["per_day"][-4] == 1
    assert sum(body["per_day"]) == 6


def test_diversity_is_cumulative_and_non_decreasing(client, owner_headers):
    body = client.get("/stats/insights?days=14", headers=owner_headers).json()

    diversity = body["diversity"]
    assert diversity == sorted(diversity), "cumulative species count must never drop"
    assert diversity[-1] == body["distinct_species"]


def test_hours_histogram_totals_match(client, owner_headers):
    body = client.get("/stats/insights?days=30", headers=owner_headers).json()

    assert sum(body["hours"]) == body["total_sightings"]
    assert 0 <= body["busiest_hour"] <= 23


def test_scoped_to_accessible_devices(client, viewer_headers):
    """The viewer can only see dev1, so the dev2 sighting must not be counted."""
    body = client.get("/stats/insights?days=30", headers=viewer_headers).json()

    assert body["total_sightings"] == 5
    assert body["per_day"][-1] == 5


def test_device_filter_narrows_results(client, owner_headers):
    body = client.get(
        f"/stats/insights?days=30&device_id={IDS['dev2_id']}", headers=owner_headers
    ).json()

    assert body["device_id"] == IDS["dev2_id"]
    assert body["total_sightings"] == 1


def test_device_filter_cannot_reach_an_inaccessible_device(client, viewer_headers):
    """Asking for a device you can't see returns nothing, not someone else's data."""
    body = client.get(
        f"/stats/insights?days=30&device_id={IDS['dev2_id']}", headers=viewer_headers
    ).json()

    assert body["total_sightings"] == 0


def test_new_species_lists_arrivals_inside_the_window(client, owner_headers):
    body = client.get("/stats/insights?days=30", headers=owner_headers).json()

    names = {n["common_name"] for n in body["new_species"]}
    assert names == {"Test Cardinal", "Test Jay"}
    assert "Test Wren" not in names, "a species never sighted is not an arrival"


def test_species_first_seen_before_the_window_is_not_new(client, owner_headers):
    """"New" means first-ever sighting, not first sighting within the window.

    In a 1-day window both species were *seen* today, but only Test Jay is an
    arrival — Test Cardinal's all-time first sighting was 3 days ago on dev2.
    """
    body = client.get("/stats/insights?days=1", headers=owner_headers).json()

    names = {n["common_name"] for n in body["new_species"]}
    assert names == {"Test Jay"}
    assert "Test Cardinal" not in names


def test_streak_and_active_days(client, owner_headers):
    body = client.get("/stats/insights?days=30", headers=owner_headers).json()

    # Two active days: today and three days ago — not consecutive.
    assert body["active_days"] == 2
    assert body["longest_streak"] == 1


def test_per_device_breakdown(client, owner_headers):
    body = client.get("/stats/insights?days=30", headers=owner_headers).json()

    counts = {d["device_id"]: d["count"] for d in body["per_device"]}
    assert counts[IDS["dev1_id"]] == 5
    assert counts[IDS["dev2_id"]] == 1


def test_days_is_clamped_to_a_sane_range(client, owner_headers):
    too_big = client.get("/stats/insights?days=99999", headers=owner_headers).json()
    too_small = client.get("/stats/insights?days=0", headers=owner_headers).json()

    assert too_big["days"] == 365
    assert too_small["days"] == 1
