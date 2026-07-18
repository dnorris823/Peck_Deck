"""Tests for account self-service: password change and email change.

These register throwaway users so they never mutate the seeded owner/viewer
(whose credentials and emails other tests assert against).
"""
import secrets

from backend.auth.jwt_utils import create_user_token


def _register(client, *, role="viewer", password="pw"):
    email = f"acct_{secrets.token_hex(4)}@test.dev"
    res = client.post(
        "/users",
        json={"name": "Acct User", "email": email, "password": password, "role": role},
    )
    assert res.status_code == 201
    uid = res.json()["id"]
    headers = {"Authorization": f"Bearer {create_user_token(uid, role)}"}
    return uid, email, headers


def test_self_password_change_requires_correct_current(client):
    uid, email, headers = _register(client, password="oldpw")

    # Wrong current password → 400
    bad = client.post(
        f"/users/{uid}/password",
        headers=headers,
        json={"current_password": "nope", "new_password": "newpw"},
    )
    assert bad.status_code == 400

    # Correct current password → 204, and the new password logs in
    good = client.post(
        f"/users/{uid}/password",
        headers=headers,
        json={"current_password": "oldpw", "new_password": "newpw"},
    )
    assert good.status_code == 204

    assert client.post("/login", json={"email": email, "password": "newpw"}).status_code == 201
    assert client.post("/login", json={"email": email, "password": "oldpw"}).status_code == 401


def test_owner_reset_skips_current_password(client, owner_headers):
    uid, email, _ = _register(client, password="oldpw")

    # Owner resets another user's password without supplying current_password
    res = client.post(
        f"/users/{uid}/password",
        headers=owner_headers,
        json={"new_password": "resetpw"},
    )
    assert res.status_code == 204
    assert client.post("/login", json={"email": email, "password": "resetpw"}).status_code == 201


def test_non_owner_cannot_change_other_users_password(client):
    _, _, victim_headers = _register(client)
    other_uid, _, _ = _register(client)
    res = client.post(
        f"/users/{other_uid}/password",
        headers=victim_headers,
        json={"current_password": "pw", "new_password": "x"},
    )
    assert res.status_code == 403


def test_email_change_persists_and_allows_login(client):
    uid, old_email, headers = _register(client, password="pw")
    new_email = f"acct_{secrets.token_hex(4)}@test.dev"

    res = client.put(f"/users/{uid}", headers=headers, json={"email": new_email})
    assert res.status_code == 200
    assert res.json()["email"] == new_email

    assert client.post("/login", json={"email": new_email, "password": "pw"}).status_code == 201


def test_email_change_conflict_returns_409(client):
    uid, _, headers = _register(client)
    # Collide with the seeded owner's email.
    res = client.put(f"/users/{uid}", headers=headers, json={"email": "owner@test.dev"})
    assert res.status_code == 409
