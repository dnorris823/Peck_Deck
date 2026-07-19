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


# ---------------------------------------------------------------------------
# JWT validity failures
# ---------------------------------------------------------------------------
from datetime import datetime, timedelta, timezone  # noqa: E402

import jwt as pyjwt  # noqa: E402

from backend.config import settings  # noqa: E402
from backend.tests.conftest import IDS, _auth  # noqa: E402


def _jwt(user_id, role="owner", *, secret=None, exp_delta=timedelta(hours=1)):
    """Craft a JWT directly so tests can control expiry and signing secret."""
    now = datetime.now(timezone.utc)
    payload = {"sub": str(user_id), "role": role, "iat": now, "exp": now + exp_delta}
    return pyjwt.encode(
        payload, secret or settings.JWT_SECRET, algorithm=settings.JWT_ALGORITHM
    )


def test_expired_jwt_rejected(client):
    token = _jwt(IDS["owner_id"], exp_delta=timedelta(hours=-1))
    res = client.get("/species", headers=_auth(token))
    assert res.status_code == 401


def test_wrong_secret_jwt_rejected(client):
    token = _jwt(IDS["owner_id"], secret="a-different-secret-that-is-also-32-bytes!")
    res = client.get("/species", headers=_auth(token))
    assert res.status_code == 401


def test_garbage_token_rejected(client):
    res = client.get("/species", headers=_auth("not.a.real.jwt"))
    assert res.status_code == 401


def test_empty_bearer_token_rejected(client):
    res = client.get("/species", headers={"Authorization": "Bearer "})
    assert res.status_code == 401


# ---------------------------------------------------------------------------
# Role / ownership authorization (authenticated but not permitted → 403)
# ---------------------------------------------------------------------------
def test_viewer_cannot_update_others_device(client, viewer_headers):
    # Viewer can *see* dev1 (membership) but is neither its owner nor an owner
    # role, so mutating it is forbidden — a 403, distinct from an auth 401.
    res = client.put(
        f"/devices/{IDS['dev1_id']}",
        headers=viewer_headers,
        json={"name": "Renamed By Viewer"},
    )
    assert res.status_code == 403


# ---------------------------------------------------------------------------
# Device-token vs user-JWT: each guard rejects the other credential type
# ---------------------------------------------------------------------------
def test_user_jwt_rejected_on_device_endpoint(client, owner_headers):
    # A user JWT is not a valid device token; device_guard must reject it.
    res = client.post(
        f"/devices/{IDS['dev1_id']}/heartbeat",
        headers=owner_headers,
        json={"battery": 0.9, "signal": "good"},
    )
    assert res.status_code == 401


def test_device_token_rejected_on_user_endpoint(client):
    # A device token is not a valid JWT; user_guard must reject it.
    res = client.get("/species", headers=_auth("dev1-token"))
    assert res.status_code == 401


def test_unknown_device_token_rejected(client):
    res = client.post(
        f"/devices/{IDS['dev1_id']}/heartbeat",
        headers=_auth("no-such-device-token"),
        json={"battery": 0.5, "signal": "good"},
    )
    assert res.status_code == 401


def test_device_cannot_report_for_another_device(client):
    # Valid dev1 token, but reporting for dev2 — scoped to itself only (403).
    res = client.post(
        f"/devices/{IDS['dev2_id']}/heartbeat",
        headers=_auth("dev1-token"),
        json={"battery": 0.5, "signal": "good"},
    )
    assert res.status_code == 403
