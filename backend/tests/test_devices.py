from datetime import datetime, timedelta, timezone

import pytest

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
    headers = _fresh_owner(client)
    device = client.post("/devices", json={"name": "Telemetry"}, headers=headers).json()
    res = client.post("/devices/%d/heartbeat" % device["id"],
                      json={"battery": 0.6, "signal": "good"},
                      headers={"Authorization": f"Bearer {device['token']}"})
    assert res.status_code == 200
    body = res.json()
    assert body["battery"] == 0.6
    assert body["status"] == "online"  # heartbeat refreshes last_seen


# --- Power source. A plugged-in feeder has no battery to show. ---

def _beat(client, token, body):
    return client.post("/devices/me/heartbeat", json=body,
                       headers={"Authorization": f"Bearer {token}"})


def _new_device(client, name):
    return client.post("/devices", json={"name": name}, headers=_fresh_owner(client)).json()


def test_device_list_carries_power_source(client, owner_headers):
    by_name = {d["name"]: d for d in client.get("/devices", headers=owner_headers).json()}
    assert by_name["Dev One"]["power_source"] == "mains"
    assert by_name["Dev One"]["battery"] is None
    assert by_name["Dev Three"]["power_source"] == "battery"


def test_mains_heartbeat_clears_a_stale_battery_level(client):
    # The live feeder kept a seeded 78% because no heartbeat ever replaced it.
    device = _new_device(client, "Stale Battery")
    assert _beat(client, device["token"], {"battery": 0.15}).json()["status"] == "warn"

    body = _beat(client, device["token"], {"power_source": "mains"}).json()
    assert body["power_source"] == "mains"
    assert body["battery"] is None
    assert body["status"] == "online"


def test_mains_ignores_a_battery_level_in_the_same_heartbeat(client):
    device = _new_device(client, "Mains And Battery")
    body = _beat(client, device["token"], {"power_source": "mains", "battery": 0.1}).json()
    assert body["battery"] is None
    assert body["status"] == "online"


def test_battery_feeder_keeps_its_level_and_warns_when_low(client):
    device = _new_device(client, "On Battery")
    body = _beat(client, device["token"], {"power_source": "battery", "battery": 0.15}).json()
    assert body["power_source"] == "battery"
    assert body["battery"] == 0.15
    assert body["status"] == "warn"


def test_power_source_stays_when_a_heartbeat_omits_it(client):
    device = _new_device(client, "Sticky Power")
    _beat(client, device["token"], {"power_source": "mains"})
    body = _beat(client, device["token"], {}).json()
    assert body["power_source"] == "mains"


def test_unknown_power_source_is_refused(client):
    device = _new_device(client, "Solar Maybe")
    res = _beat(client, device["token"], {"power_source": "solar"})
    assert res.status_code == 400


# --- Pi health. The offline queue and vitals, so a stuck Pi shows on its card. ---

def test_heartbeat_stores_the_queue_and_vitals(client):
    device = _new_device(client, "Backlog")
    res = _beat(client, device["token"], {
        "queued_sightings": 14, "oldest_queued_age_seconds": 3 * 3600,
        "dropped_since_boot": 0, "disk_free_bytes": 20 * 1024**3, "cpu_temp_c": 52.5,
    })
    assert res.status_code == 200
    health = res.json()["pi_health"]
    assert health["queued_sightings"] == 14
    assert health["dropped_since_boot"] == 0
    assert health["disk_free_bytes"] == 20 * 1024**3
    assert health["cpu_temp_c"] == 52.5
    assert health["warnings"] == []
    # An age goes in, an instant comes out, so the card's age keeps growing.
    oldest = datetime.fromisoformat(health["oldest_queued_at"])
    assert abs((datetime.now(timezone.utc) - oldest) - timedelta(hours=3)) < timedelta(minutes=1)


def test_heartbeat_without_health_fields_is_still_valid(client):
    # A Pi on older code sends none of them.
    device = _new_device(client, "Older Pi")
    res = _beat(client, device["token"], {"signal": "good"})
    assert res.status_code == 200
    assert res.json()["pi_health"] == {
        "queued_sightings": None, "oldest_queued_at": None, "dropped_since_boot": None,
        "disk_free_bytes": None, "cpu_temp_c": None, "warnings": [],
    }


def test_health_fields_clear_when_a_heartbeat_omits_them(client):
    # A snapshot. A queue the Pi stopped reporting must not show forever.
    device = _new_device(client, "Drained")
    _beat(client, device["token"], {"queued_sightings": 3, "oldest_queued_age_seconds": 60})
    health = _beat(client, device["token"], {}).json()["pi_health"]
    assert health["queued_sightings"] is None
    assert health["oldest_queued_at"] is None


def test_health_warns_on_drops_low_disk_and_heat(client):
    device = _new_device(client, "Struggling")
    health = _beat(client, device["token"], {
        "dropped_since_boot": 2, "disk_free_bytes": 200 * 1024**2, "cpu_temp_c": 82.0,
    }).json()["pi_health"]
    assert health["warnings"] == ["dropped", "disk", "temp"]


def test_health_does_not_change_the_feeder_status(client):
    # The card shows the backlog on its own line. Status stays about contact.
    device = _new_device(client, "Queued But Online")
    body = _beat(client, device["token"], {"queued_sightings": 50, "dropped_since_boot": 1}).json()
    assert body["status"] == "online"


@pytest.mark.parametrize("field", [
    "queued_sightings", "oldest_queued_age_seconds", "dropped_since_boot", "disk_free_bytes",
])
def test_negative_health_counts_are_refused(client, field):
    device = _new_device(client, f"Negative {field}")
    res = _beat(client, device["token"], {field: -1})
    assert res.status_code == 400
    assert field in res.json()["detail"]


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


# --- The owner can rotate a device token or remove a device. ---

def _fresh_viewer(client):
    """A throwaway viewer, so membership tests leave the seeded viewer alone."""
    import secrets
    seeded_owner = {"Authorization": f"Bearer {create_user_token(IDS['owner_id'], 'owner')}"}
    res = client.post("/users", headers=seeded_owner, json={
        "name": "Dev Test Viewer", "email": f"devview_{secrets.token_hex(4)}@test.dev",
        "password": "pw", "role": "viewer",
    })
    uid = res.json()["id"]
    return uid, {"Authorization": f"Bearer {create_user_token(uid, 'viewer')}"}


def _upload(client, token, monkeypatch):
    import backend.sightings.aftercare as aftercare

    async def _noop(*_a, **_k):
        return None

    monkeypatch.setattr(aftercare.notification_service, "dispatch", _noop)
    monkeypatch.setattr(aftercare, "enrich_species", _noop)
    return client.post(
        "/sightings",
        headers={"Authorization": f"Bearer {token}"},
        data={
            "timestamp": "2026-10-31T10:30:00",
            "common_name": "Rotate Sparrow",
            "scientific_name": "Passer rotatus",
            "confidence_score": "0.9",
            "classification_tier_used": "gpu",
        },
        files={"image": ("bird.jpg", b"\xff\xd8\xff\xe0rotate", "image/jpeg")},
    )


def test_rotating_the_token_refuses_the_old_one(client, monkeypatch):
    headers = _fresh_owner(client)
    device = client.post("/devices", json={"name": "Rotate Me"}, headers=headers).json()
    old = device["token"]

    res = client.post("/devices/%d/token" % device["id"], headers=headers)
    assert res.status_code == 200
    new = res.json()["token"]
    assert res.json()["id"] == device["id"]
    assert new and new != old

    assert _upload(client, old, monkeypatch).status_code == 401
    assert _upload(client, new, monkeypatch).status_code == 201

    # The read route the provisioning script uses returns the new token.
    read = client.get("/devices/%d/token" % device["id"], headers=headers)
    assert read.json()["token"] == new


def test_viewer_cannot_rotate_device_token(client, viewer_headers):
    res = client.post("/devices/%d/token" % IDS["dev1_id"], headers=viewer_headers)
    assert res.status_code == 403
    # Dev One still answers to its seeded token.
    beat = client.post("/devices/me/heartbeat", json={},
                       headers={"Authorization": "Bearer dev1-token"})
    assert beat.status_code == 200


def test_rotate_route_rejects_device_token(client):
    res = client.post("/devices/%d/token" % IDS["dev1_id"],
                      headers={"Authorization": "Bearer dev1-token"})
    assert res.status_code == 401


def test_rotate_route_404s_unknown_device(client, owner_headers):
    res = client.post("/devices/999999/token", headers=owner_headers)
    assert res.status_code == 404


def test_owner_deletes_a_device_without_sightings(client):
    headers = _fresh_owner(client)
    device = client.post("/devices", json={"name": "Delete Me"}, headers=headers).json()
    viewer_id, viewer = _fresh_viewer(client)
    client.post("/devices/%d/users" % device["id"], json={"user_id": viewer_id}, headers=headers)
    assert [d["id"] for d in client.get("/devices", headers=viewer).json()] == [device["id"]]

    res = client.delete("/devices/%d" % device["id"], headers=headers)
    assert res.status_code == 204

    # Gone for the owner and the viewer, and its token no longer authenticates.
    assert all(d["id"] != device["id"] for d in client.get("/devices", headers=headers).json())
    assert client.get("/devices", headers=viewer).json() == []
    assert client.get("/devices/%d/token" % device["id"], headers=headers).status_code == 404
    beat = client.post("/devices/me/heartbeat", json={},
                       headers={"Authorization": f"Bearer {device['token']}"})
    assert beat.status_code == 401


def test_delete_is_refused_while_sightings_exist(client, monkeypatch):
    headers = _fresh_owner(client)
    device = client.post("/devices", json={"name": "Has Birds"}, headers=headers).json()
    assert _upload(client, device["token"], monkeypatch).status_code == 201

    res = client.delete("/devices/%d" % device["id"], headers=headers)
    assert res.status_code == 409
    assert "1 sightings" in res.json()["detail"]

    # Nothing was removed: the device, its sighting and its token all remain.
    listed = next(d for d in client.get("/devices", headers=headers).json()
                  if d["id"] == device["id"])
    assert listed["all_time_sightings"] == 1
    beat = client.post("/devices/me/heartbeat", json={},
                       headers={"Authorization": f"Bearer {device['token']}"})
    assert beat.status_code == 200


def test_delete_with_sightings_removes_the_feeder_and_its_sightings(client, monkeypatch):
    headers = _fresh_owner(client)
    device = client.post("/devices", json={"name": "Placeholder"}, headers=headers).json()
    upload = _upload(client, device["token"], monkeypatch)
    assert upload.status_code == 201
    sighting_id = upload.json()["id"]

    res = client.delete("/devices/%d?delete_sightings=true" % device["id"], headers=headers)
    assert res.status_code == 204

    assert all(d["id"] != device["id"] for d in client.get("/devices", headers=headers).json())
    assert client.get("/sightings/%d" % sighting_id, headers=headers).status_code == 404


def test_viewer_cannot_delete_device(client, viewer_headers):
    res = client.delete("/devices/%d" % IDS["dev1_id"], headers=viewer_headers)
    assert res.status_code == 403


def test_delete_route_rejects_device_token(client):
    res = client.delete("/devices/%d" % IDS["dev1_id"],
                        headers={"Authorization": "Bearer dev1-token"})
    assert res.status_code == 401


def test_delete_route_404s_unknown_device(client, owner_headers):
    res = client.delete("/devices/999999", headers=owner_headers)
    assert res.status_code == 404


# --- Sharing a feeder and changing its location, from feeder settings. ---

def test_feeder_access_lists_owner_and_members(client, owner_headers):
    res = client.get("/devices/%d/users" % IDS["dev1_id"], headers=owner_headers)
    assert res.status_code == 200
    body = res.json()
    assert body["owner"]["id"] == IDS["owner_id"]
    assert [m["id"] for m in body["members"]] == [IDS["viewer_id"]]


def test_member_cannot_read_feeder_access(client, viewer_headers):
    res = client.get("/devices/%d/users" % IDS["dev1_id"], headers=viewer_headers)
    assert res.status_code == 403


def test_viewer_owner_shares_by_email(client):
    """A feeder owner with the viewer role cannot list users, so adds by email."""
    owner_id, owner = _fresh_viewer(client)
    device = client.post("/devices", json={"name": "Brother's"}, headers=owner).json()
    friend_id, friend = _fresh_viewer(client)
    seeded = {"Authorization": f"Bearer {create_user_token(IDS['owner_id'], 'owner')}"}
    email = client.get(f"/users/{friend_id}", headers=seeded).json()["email"]

    res = client.post("/devices/%d/users" % device["id"], json={"email": email}, headers=owner)
    assert res.status_code == 204
    assert [d["id"] for d in client.get("/devices", headers=friend).json()] == [device["id"]]

    access = client.get("/devices/%d/users" % device["id"], headers=owner).json()
    assert access["owner"]["id"] == owner_id
    assert [m["id"] for m in access["members"]] == [friend_id]

    res = client.delete("/devices/%d/users/%d" % (device["id"], friend_id), headers=owner)
    assert res.status_code == 204
    assert client.get("/devices", headers=friend).json() == []


def test_add_member_rejects_unknown_user(client):
    headers = _fresh_owner(client)
    device = client.post("/devices", json={"name": "Lonely"}, headers=headers).json()
    path = "/devices/%d/users" % device["id"]
    assert client.post(path, json={"email": "nobody@test.dev"}, headers=headers).status_code == 404
    assert client.post(path, json={"user_id": 999999}, headers=headers).status_code == 404
    assert client.post(path, json={}, headers=headers).status_code == 400


def test_add_member_rejects_the_owner(client):
    headers = _fresh_owner(client)
    device = client.post("/devices", json={"name": "Mine"}, headers=headers).json()
    res = client.post("/devices/%d/users" % device["id"],
                      json={"user_id": device["owner_id"]}, headers=headers)
    assert res.status_code == 400


def test_update_device_location_and_clear_it(client):
    headers = _fresh_owner(client)
    device = client.post("/devices", json={"name": "Move Me"}, headers=headers).json()
    path = "/devices/%d" % device["id"]

    res = client.put(path, json={"name": " Porch ", "city": "Stowe", "state": "VT",
                                 "feed_type": "suet"}, headers=headers)
    assert res.status_code == 200
    body = res.json()
    assert (body["name"], body["city"], body["state"], body["feed_type"]) == \
        ("Porch", "Stowe", "VT", "suet")

    body = client.put(path, json={"city": "", "state": ""}, headers=headers).json()
    assert body["city"] is None and body["state"] is None
    assert body["feed_type"] == "suet"

    assert client.put(path, json={"name": "  "}, headers=headers).status_code == 400


# --- Handing a feeder to another owner. ---

def test_transfer_hands_the_feeder_over_and_keeps_the_old_owner_as_member(client):
    old_id, old = _fresh_viewer(client)
    new_id, new = _fresh_viewer(client)
    device = client.post("/devices", json={"name": "Hand Me On"}, headers=old).json()
    path = "/devices/%d" % device["id"]
    # The new owner was a member first. That row goes, since an owner is not a member.
    client.post(path + "/users", json={"user_id": new_id}, headers=old)

    res = client.put(path, json={"owner_id": new_id}, headers=old)
    assert res.status_code == 200
    assert res.json()["owner_id"] == new_id

    access = client.get(path + "/users", headers=new).json()
    assert access["owner"]["id"] == new_id
    assert [m["id"] for m in access["members"]] == [old_id]
    # The old owner still sees it, but can no longer act as its owner.
    assert [d["id"] for d in client.get("/devices", headers=old).json()] == [device["id"]]
    assert client.get(path + "/token", headers=old).status_code == 403
    assert client.get(path + "/token", headers=new).status_code == 200


def test_transfer_rejects_an_unknown_user(client):
    headers = _fresh_owner(client)
    device = client.post("/devices", json={"name": "Stay Put"}, headers=headers).json()
    res = client.put("/devices/%d" % device["id"], json={"owner_id": 999999}, headers=headers)
    assert res.status_code == 400
    assert client.get("/devices/%d/users" % device["id"], headers=headers).json()["owner"]["id"]         == device["owner_id"]


def test_member_cannot_transfer_a_feeder(client, viewer_headers):
    res = client.put("/devices/%d" % IDS["dev1_id"], json={"owner_id": IDS["viewer_id"]},
                     headers=viewer_headers)
    assert res.status_code == 403
