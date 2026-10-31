"""Long sign-ins and how they end.

A user JWT lasts 30 days so the installed app opens from a push notification
without a login. Revocation goes through User.token_version, which the user
guard checks on every request. These tests register throwaway users, because
signing out revokes every token the user holds and would break the seeded
owner and viewer for later tests.
"""
import secrets
from datetime import datetime, timedelta, timezone

import jwt as pyjwt

from backend.auth.jwt_utils import create_user_token, decode_user_token
from backend.auth.rate_limit import login_rate_limiter
from backend.config import settings
from backend.tests.conftest import IDS, _auth


def _owner_headers() -> dict:
    return _auth(create_user_token(IDS["owner_id"], "owner"))


def _register(client, *, role="viewer", password="pw") -> tuple[int, str]:
    email = f"sess_{secrets.token_hex(4)}@test.dev"
    res = client.post(
        "/users",
        headers=_owner_headers(),
        json={"name": "Session User", "email": email, "password": password, "role": role},
    )
    assert res.status_code == 201
    return res.json()["id"], email


def _login(client, email, password="pw") -> dict:
    res = client.post("/login", json={"email": email, "password": password})
    assert res.status_code == 201
    return _auth(res.json()["access_token"])


def _issued_at(user_id, *, hours_ago, version=0) -> str:
    """A token signed `hours_ago`, with the default lifetime from then."""
    iat = datetime.now(timezone.utc) - timedelta(hours=hours_ago)
    payload = {
        "sub": str(user_id),
        "role": "viewer",
        "ver": version,
        "iat": iat,
        "exp": iat + timedelta(hours=settings.JWT_EXPIRE_HOURS),
    }
    return pyjwt.encode(payload, settings.JWT_SECRET, algorithm=settings.JWT_ALGORITHM)


def test_login_token_lasts_thirty_days(client):
    _, email = _register(client)
    token = _login(client, email)["Authorization"][7:]
    claims = decode_user_token(token)
    assert claims["exp"] - claims["iat"] == 720 * 3600


def test_token_signed_two_days_ago_still_opens_a_sighting(client):
    # The issue's case: signed in more than 24 hours ago, tap a push, see it.
    # The seeded viewer, because a fresh user is a member of no device. The
    # test only reads, so it leaves that user's token version alone.
    headers = _auth(_issued_at(IDS["viewer_id"], hours_ago=48))
    listing = client.get("/sightings", headers=headers)
    assert listing.status_code == 200
    sighting_id = listing.json()[0]["id"]
    assert client.get(f"/sightings/{sighting_id}", headers=headers).status_code == 200


def test_logout_revokes_the_token(client):
    _, email = _register(client)
    headers = _login(client, email)
    assert client.get("/users/me", headers=headers).status_code == 200

    assert client.post("/logout", headers=headers).status_code == 204
    assert client.get("/users/me", headers=headers).status_code == 401


def test_logout_revokes_tokens_on_every_device(client):
    _, email = _register(client)
    phone = _login(client, email)
    laptop = _login(client, email)

    assert client.post("/logout", headers=laptop).status_code == 204
    assert client.get("/users/me", headers=phone).status_code == 401


def test_login_after_logout_works(client):
    _, email = _register(client)
    assert client.post("/logout", headers=_login(client, email)).status_code == 204
    assert client.get("/users/me", headers=_login(client, email)).status_code == 200


def test_logout_requires_a_user_token(client):
    assert client.post("/logout").status_code == 401
    assert client.post("/logout", headers=_auth("dev1-token")).status_code == 401


def test_owner_password_reset_cuts_the_user_off(client):
    uid, email = _register(client)
    headers = _login(client, email)

    res = client.post(
        f"/users/{uid}/password", headers=_owner_headers(), json={"new_password": "new"}
    )
    assert res.status_code == 204
    assert client.get("/users/me", headers=headers).status_code == 401
    assert client.get("/users/me", headers=_login(client, email, "new")).status_code == 200


def test_own_password_change_keeps_the_session(client):
    uid, email = _register(client, password="old")
    headers = _login(client, email, "old")

    res = client.post(
        f"/users/{uid}/password",
        headers=headers,
        json={"current_password": "old", "new_password": "new"},
    )
    assert res.status_code == 204
    assert client.get("/users/me", headers=headers).status_code == 200


def test_deleted_user_token_is_rejected(client):
    uid, email = _register(client)
    headers = _login(client, email)

    assert client.delete(f"/users/{uid}", headers=_owner_headers()).status_code == 204
    # Before the version check, this passed the guard for the token's lifetime.
    assert client.get("/species", headers=headers).status_code == 401


def test_stale_version_is_rejected(client):
    uid, _ = _register(client)
    assert client.get("/species", headers=_auth(_issued_at(uid, hours_ago=0, version=1))).status_code == 401


def test_token_without_version_claim_is_version_zero(client):
    # Tokens signed before token_version existed carry no `ver`. They stay valid
    # until their own expiry, then revoke like any other.
    uid, _ = _register(client)
    now = datetime.now(timezone.utc)
    payload = {"sub": str(uid), "role": "viewer", "iat": now, "exp": now + timedelta(hours=1)}
    token = pyjwt.encode(payload, settings.JWT_SECRET, algorithm=settings.JWT_ALGORITHM)
    assert client.get("/species", headers=_auth(token)).status_code == 200


def test_role_comes_from_the_database_not_the_claim(client):
    # A viewer token that claims owner must not pass the owner guard.
    uid, _ = _register(client, role="viewer")
    forged = _auth(create_user_token(uid, "owner"))
    res = client.post(
        "/users",
        headers=forged,
        json={"name": "x", "email": f"x_{secrets.token_hex(4)}@test.dev", "password": "x"},
    )
    assert res.status_code == 401


def test_login_throttle_still_applies(client):
    login_rate_limiter.clear()
    _, email = _register(client)
    try:
        codes = [
            client.post("/login", json={"email": email, "password": "wrong"}).status_code
            for _ in range(6)
        ]
        assert codes[:5] == [401] * 5
        assert codes[5] == 429
        # A correct password is still refused while the account is locked.
        res = client.post("/login", json={"email": email, "password": "pw"})
        assert res.status_code == 429
        assert "Retry-After" in res.headers
    finally:
        login_rate_limiter.clear()
