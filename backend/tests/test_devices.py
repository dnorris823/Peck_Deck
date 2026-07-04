from backend.tests.conftest import IDS


def test_owner_sees_all_devices_with_status(client, owner_headers):
    res = client.get("/devices", headers=owner_headers)
    assert res.status_code == 200
    by_name = {d["name"]: d for d in res.json()}
    assert set(by_name) == {"Dev One", "Dev Two", "Dev Three"}
    assert by_name["Dev One"]["status"] == "online"     # recent + healthy
    assert by_name["Dev Two"]["status"] == "offline"    # last_seen 40m ago
    assert by_name["Dev Three"]["status"] == "warn"     # low battery


def test_device_sighting_counts(client, owner_headers):
    res = client.get("/devices", headers=owner_headers)
    dev1 = next(d for d in res.json() if d["name"] == "Dev One")
    assert dev1["today_sightings"] == 5
    assert dev1["week_sightings"] == 5
    assert dev1["all_time_sightings"] == 5


def test_viewer_sees_only_member_device(client, viewer_headers):
    res = client.get("/devices", headers=viewer_headers)
    assert res.status_code == 200
    names = [d["name"] for d in res.json()]
    assert names == ["Dev One"]


def test_heartbeat_updates_telemetry(client):
    res = client.post("/devices/%d/heartbeat" % IDS["dev1_id"],
                      json={"battery": 0.6, "signal": "good"},
                      headers={"Authorization": "Bearer dev1-token"})
    assert res.status_code == 200
    body = res.json()
    assert body["battery"] == 0.6
    assert body["status"] == "online"  # heartbeat refreshes last_seen


def test_heartbeat_wrong_device_forbidden(client):
    # dev1's token trying to report for dev2
    res = client.post("/devices/%d/heartbeat" % IDS["dev2_id"],
                      json={"battery": 0.6},
                      headers={"Authorization": "Bearer dev1-token"})
    assert res.status_code == 403


def test_heartbeat_rejects_user_token(client, owner_headers):
    res = client.post("/devices/%d/heartbeat" % IDS["dev1_id"],
                      json={"battery": 0.6}, headers=owner_headers)
    assert res.status_code == 401  # user JWT is not a valid device token


def test_update_device_requires_owner(client, viewer_headers):
    res = client.put("/devices/%d" % IDS["dev1_id"],
                     json={"feed_type": "hacked"}, headers=viewer_headers)
    assert res.status_code == 403
