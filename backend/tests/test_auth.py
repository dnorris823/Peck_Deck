def test_login_success(client):
    res = client.post("/login", json={"email": "owner@test.dev", "password": "ownerpw"})
    assert res.status_code == 201
    body = res.json()
    assert body["token_type"] == "bearer"
    assert body["access_token"]


def test_login_wrong_password(client):
    res = client.post("/login", json={"email": "owner@test.dev", "password": "nope"})
    assert res.status_code == 401


def test_login_unknown_email(client):
    res = client.post("/login", json={"email": "ghost@test.dev", "password": "x"})
    assert res.status_code == 401


def test_protected_requires_auth(client):
    assert client.get("/species").status_code == 401
    assert client.get("/devices").status_code == 401
    assert client.get("/users").status_code == 401
    assert client.get("/stats/dashboard").status_code == 401


def test_malformed_bearer_rejected(client):
    res = client.get("/species", headers={"Authorization": "Token abc"})
    assert res.status_code == 401
