from backend.tests.conftest import IDS


def test_list_users(client, owner_headers):
    res = client.get("/users", headers=owner_headers)
    assert res.status_code == 200
    emails = {u["email"] for u in res.json()}
    assert {"owner@test.dev", "viewer@test.dev"} <= emails


def test_register_and_duplicate(client, owner_headers):
    payload = {"name": "New Person", "email": "new@test.dev", "password": "pw", "role": "viewer"}
    res = client.post("/users", headers=owner_headers, json=payload)
    assert res.status_code == 201
    assert res.json()["email"] == "new@test.dev"

    dup = client.post("/users", headers=owner_headers, json=payload)
    assert dup.status_code == 409


def test_get_self(client, owner_headers):
    res = client.get(f"/users/{IDS['owner_id']}", headers=owner_headers)
    assert res.status_code == 200
    assert res.json()["role"] == "owner"


def test_owner_can_read_other_user(client, owner_headers):
    res = client.get(f"/users/{IDS['viewer_id']}", headers=owner_headers)
    assert res.status_code == 200


def test_viewer_cannot_read_other_user(client, viewer_headers):
    res = client.get(f"/users/{IDS['owner_id']}", headers=viewer_headers)
    assert res.status_code == 403


def test_me_returns_authenticated_user(client, owner_headers):
    res = client.get("/users/me", headers=owner_headers)
    assert res.status_code == 200
    body = res.json()
    assert body["id"] == IDS["owner_id"]
    assert body["email"] == "owner@test.dev"
    assert body["role"] == "owner"


def test_me_requires_auth(client):
    assert client.get("/users/me").status_code == 401


def test_preferences_defaults_then_update(client, viewer_headers):
    res = client.get("/users/me/preferences", headers=viewer_headers)
    assert res.status_code == 200
    assert res.json() == {
        "quiet_interval_seconds": 60,
        "notify_new_species_only": False,
    }

    upd = client.put(
        "/users/me/preferences",
        headers=viewer_headers,
        json={
            "quiet_interval_seconds": 120,
            "notify_new_species_only": True,
        },
    )
    assert upd.status_code == 200
    assert upd.json()["quiet_interval_seconds"] == 120

    # Persisted across a fresh read.
    again = client.get("/users/me/preferences", headers=viewer_headers)
    assert again.json()["quiet_interval_seconds"] == 120
    assert again.json()["notify_new_species_only"] is True


def test_preferences_partial_update(client, owner_headers):
    client.put(
        "/users/me/preferences", headers=owner_headers, json={"notify_new_species_only": True}
    )
    # Only the provided field changes; others keep their defaults.
    body = client.get("/users/me/preferences", headers=owner_headers).json()
    assert body["notify_new_species_only"] is True
    assert body["quiet_interval_seconds"] == 60


def test_preferences_validation(client, owner_headers):
    for bad in (
        {"quiet_interval_seconds": 5},
    ):
        res = client.put("/users/me/preferences", headers=owner_headers, json=bad)
        assert res.status_code == 400, bad


# --- Owner controls on the Users page. ---

import secrets  # noqa: E402

from backend.auth.jwt_utils import create_user_token  # noqa: E402
from backend.notifications.push_sender import b64url_encode  # noqa: E402


def _headers(uid):
    return {"Authorization": f"Bearer {create_user_token(uid, 'owner')}"}


def _new_user(client, owner_headers, role="viewer"):
    res = client.post("/users", headers=owner_headers, json={
        "name": f"User {role}", "email": f"u_{secrets.token_hex(4)}@test.dev",
        "password": "password1", "role": role,
    })
    assert res.status_code == 201
    return res.json()["id"]


def test_viewer_cannot_list_users(client, viewer_headers):
    assert client.get("/users", headers=viewer_headers).status_code == 403


def test_delete_user_with_no_feeders(client, owner_headers):
    uid = _new_user(client, owner_headers)
    assert client.delete(f"/users/{uid}", headers=owner_headers).status_code == 204
    assert client.get(f"/users/{uid}", headers=owner_headers).status_code == 404


def test_delete_feeder_member_removes_membership(client, owner_headers):
    uid = _new_user(client, owner_headers)
    viewer = {"Authorization": f"Bearer {create_user_token(uid, 'viewer')}"}
    assert client.post(f"/devices/{IDS['dev1_id']}/users", headers=owner_headers,
                       json={"user_id": uid}).status_code == 204
    # A preferences row and a push subscription also point at the user.
    assert client.get("/users/me/preferences", headers=viewer).status_code == 200
    keys = {"p256dh": b64url_encode(b"" + bytes(64)), "auth": b64url_encode(bytes(16))}
    assert client.post("/push/subscriptions", headers=viewer, json={
        "endpoint": f"https://push.test/{uid}", "keys": keys,
    }).status_code == 201

    assert client.delete(f"/users/{uid}", headers=owner_headers).status_code == 204
    access = client.get(f"/devices/{IDS['dev1_id']}/users", headers=owner_headers).json()
    assert uid not in [m["id"] for m in access["members"]]


def test_delete_feeder_owner_is_refused(client, owner_headers):
    uid = _new_user(client, owner_headers)
    headers = {"Authorization": f"Bearer {create_user_token(uid, 'viewer')}"}
    device = client.post("/devices", json={"name": "Kept Feeder"}, headers=headers).json()

    res = client.delete(f"/users/{uid}", headers=owner_headers)
    assert res.status_code == 409
    assert "Kept Feeder" in res.json()["detail"]
    assert client.get(f"/users/{uid}", headers=owner_headers).status_code == 200
    assert any(d["id"] == device["id"] for d in client.get("/devices", headers=headers).json())


def test_owner_changes_a_role_and_it_applies_at_once(client, owner_headers):
    uid = _new_user(client, owner_headers)
    token = {"Authorization": f"Bearer {create_user_token(uid, 'viewer')}"}
    assert client.get("/users", headers=token).status_code == 403

    res = client.put(f"/users/{uid}/role", headers=owner_headers, json={"role": "owner"})
    assert res.status_code == 200
    assert res.json()["role"] == "owner"
    # The same token now passes the owner check, because the guard reads the row.
    assert client.get("/users", headers=token).status_code == 200

    client.put(f"/users/{uid}/role", headers=owner_headers, json={"role": "viewer"})
    assert client.get("/users", headers=token).status_code == 403


def test_role_change_rejects_unknown_role(client, owner_headers):
    uid = _new_user(client, owner_headers)
    res = client.put(f"/users/{uid}/role", headers=owner_headers, json={"role": "admin"})
    assert res.status_code == 400


def test_viewer_cannot_change_a_role(client, viewer_headers):
    res = client.put(f"/users/{IDS['viewer_id']}/role", headers=viewer_headers,
                     json={"role": "owner"})
    assert res.status_code == 403


def test_last_owner_cannot_be_demoted_or_removed(client, owner_headers):
    last = _new_user(client, owner_headers, role="owner")
    others = [u["id"] for u in client.get("/users", headers=owner_headers).json()
              if u["role"] == "owner" and u["id"] != last]
    last_headers = _headers(last)
    try:
        for uid in others:
            res = client.put(f"/users/{uid}/role", headers=last_headers, json={"role": "viewer"})
            assert res.status_code == 200

        res = client.put(f"/users/{last}/role", headers=last_headers, json={"role": "viewer"})
        assert res.status_code == 409
        res = client.delete(f"/users/{last}", headers=last_headers)
        assert res.status_code == 409
        assert "last owner" in res.json()["detail"]
    finally:
        for uid in others:
            client.put(f"/users/{uid}/role", headers=last_headers, json={"role": "owner"})
    assert client.get("/users/me", headers=owner_headers).json()["role"] == "owner"


def test_owner_signs_a_user_out_everywhere(client, owner_headers):
    uid = _new_user(client, owner_headers)
    login = client.post("/login", json={"email": client.get(
        f"/users/{uid}", headers=owner_headers).json()["email"], "password": "password1"})
    token = {"Authorization": f"Bearer {login.json()['access_token']}"}
    assert client.get("/users/me", headers=token).status_code == 200

    assert client.post(f"/users/{uid}/logout", headers=owner_headers).status_code == 204
    assert client.get("/users/me", headers=token).status_code == 401


def test_viewer_cannot_sign_others_out(client, viewer_headers):
    res = client.post(f"/users/{IDS['owner_id']}/logout", headers=viewer_headers)
    assert res.status_code == 403
