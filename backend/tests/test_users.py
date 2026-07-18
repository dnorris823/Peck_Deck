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
        "default_tier": "auto",
        "escalation_threshold": 70,
        "debounce_seconds": 30,
    }

    upd = client.put(
        "/users/me/preferences",
        headers=viewer_headers,
        json={
            "quiet_interval_seconds": 120,
            "notify_new_species_only": True,
            "default_tier": "gpu",
            "escalation_threshold": 85,
            "debounce_seconds": 60,
        },
    )
    assert upd.status_code == 200
    assert upd.json()["default_tier"] == "gpu"

    # Persisted across a fresh read.
    again = client.get("/users/me/preferences", headers=viewer_headers)
    assert again.json()["quiet_interval_seconds"] == 120
    assert again.json()["notify_new_species_only"] is True


def test_preferences_partial_update(client, owner_headers):
    client.put(
        "/users/me/preferences", headers=owner_headers, json={"default_tier": "local"}
    )
    # Only the provided field changes; others keep their defaults.
    body = client.get("/users/me/preferences", headers=owner_headers).json()
    assert body["default_tier"] == "local"
    assert body["escalation_threshold"] == 70


def test_preferences_validation(client, owner_headers):
    for bad in (
        {"default_tier": "quantum"},
        {"escalation_threshold": 10},
        {"quiet_interval_seconds": 5},
        {"debounce_seconds": -1},
    ):
        res = client.put("/users/me/preferences", headers=owner_headers, json=bad)
        assert res.status_code == 400, bad
