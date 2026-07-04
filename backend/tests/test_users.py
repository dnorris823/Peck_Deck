from backend.tests.conftest import IDS


def test_list_users(client, owner_headers):
    res = client.get("/users", headers=owner_headers)
    assert res.status_code == 200
    emails = {u["email"] for u in res.json()}
    assert {"owner@test.dev", "viewer@test.dev"} <= emails


def test_register_and_duplicate(client):
    payload = {"name": "New Person", "email": "new@test.dev", "password": "pw", "role": "viewer"}
    res = client.post("/users", json=payload)
    assert res.status_code == 201
    assert res.json()["email"] == "new@test.dev"

    dup = client.post("/users", json=payload)
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
