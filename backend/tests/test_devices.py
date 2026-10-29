from backend.auth.jwt_utils import create_user_token
from backend.tests.conftest import IDS


def _fresh_owner(client):
    """Register a throwaway owner and return their auth headers.

    Device-creating tests use this so they don't pollute the seeded owner's
    device counts (asserted exactly by the stats tests).
    """
    import secrets
    email = f"devtest_{secrets.token_hex(4)}@test.dev"
    # Registration is owner-only, so the seeded owner issues the invite.
    seeded_owner = {"Authorization": f"Bearer {create_user_token(IDS['owner_id'], 'owner')}"}
    res = client.post("/users", headers=seeded_owner, json={
        "name": "Dev Test Owner", "email": email, "password": "pw", "role": "owner",
    })
    uid = res.json()["id"]
    return {"Authorization": f"Bearer {create_user_token(uid, 'owner')}"}


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


def test_self_heartbeat_reports_for_the_token_device(client):
    # The Pi knows its token but not its id, so this route takes neither.
    res = client.post("/devices/me/heartbeat",
                      json={"signal": "good"},
                      headers={"Authorization": "Bearer dev1-token"})
    assert res.status_code == 200
    body = res.json()
    assert body["id"] == IDS["dev1_id"]
    assert body["status"] == "online"
    assert body["last_seen"] is not None


def test_self_heartbeat_rejects_user_token(client, owner_headers):
    res = client.post("/devices/me/heartbeat", json={}, headers=owner_headers)
    assert res.status_code == 401


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



# --- The device token is the Pi's only credential. Only the owner may read it. ---

def test_device_list_carries_no_token(client, owner_headers, viewer_headers):
    for headers in (owner_headers, viewer_headers):
        res = client.get("/devices", headers=headers)
        assert res.status_code == 200
        assert res.json()
        assert all("token" not in d for d in res.json())


def test_device_update_carries_no_token(client):
    headers = _fresh_owner(client)
    device = client.post("/devices", json={"name": "Update Me"}, headers=headers).json()
    res = client.put("/devices/%d" % device["id"],
                     json={"city": "Portland"}, headers=headers)
    assert res.status_code == 200
    assert "token" not in res.json()


def test_heartbeat_carries_no_token(client):
    res = client.post("/devices/me/heartbeat", json={},
                      headers={"Authorization": "Bearer dev1-token"})
    assert res.status_code == 200
    assert "token" not in res.json()


def test_register_returns_token_once(client):
    headers = _fresh_owner(client)
    res = client.post("/devices", json={"name": "Token Once"}, headers=headers)
    assert res.status_code == 201
    created = res.json()
    assert created["token"]

    listed = next(d for d in client.get("/devices", headers=headers).json()
                  if d["id"] == created["id"])
    assert "token" not in listed

    # The token from POST is a working device credential.
    beat = client.post("/devices/me/heartbeat", json={},
                       headers={"Authorization": f"Bearer {created['token']}"})
    assert beat.status_code == 200
    assert beat.json()["id"] == created["id"]


def test_owner_reads_device_token(client, owner_headers):
    res = client.get("/devices/%d/token" % IDS["dev1_id"], headers=owner_headers)
    assert res.status_code == 200
    assert res.json() == {"id": IDS["dev1_id"], "token": "dev1-token"}


def test_viewer_cannot_read_device_token(client, viewer_headers):
    # The viewer is a DeviceUser on Dev One, so it can see the device but not act as it.
    res = client.get("/devices/%d/token" % IDS["dev1_id"], headers=viewer_headers)
    assert res.status_code == 403


def test_device_token_route_rejects_device_token(client):
    res = client.get("/devices/%d/token" % IDS["dev1_id"],
                     headers={"Authorization": "Bearer dev1-token"})
    assert res.status_code == 401


def test_device_token_route_404s_unknown_device(client, owner_headers):
    res = client.get("/devices/999999/token", headers=owner_headers)
    assert res.status_code == 404
