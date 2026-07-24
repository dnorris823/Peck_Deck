"""Security regressions (FLEDGE Phase 8).

Each test here corresponds to something that was actually exploitable, or to a
control that would be easy to weaken by accident later.
"""
import secrets

import pytest

from backend.auth.rate_limit import LoginRateLimiter, login_rate_limiter
from backend.fixtures import DEV1_TOKEN


@pytest.fixture(autouse=True)
def _clear_rate_limiter():
    """Login throttle state is process-global — don't leak it between tests."""
    login_rate_limiter.clear()
    yield
    login_rate_limiter.clear()


# ---------------------------------------------------------------------------
# Privilege escalation via open registration
# ---------------------------------------------------------------------------
def test_registration_requires_authentication(client):
    """Regression: POST /users was unauthenticated.

    Anyone who could reach the API could mint themselves an owner account and
    then enumerate every user's email and phone number.
    """
    res = client.post(
        "/users",
        json={"name": "Anon", "email": "anon@evil.test", "password": "pw", "role": "owner"},
    )

    assert res.status_code == 401


def test_registration_requires_owner_not_just_any_user(client, viewer_headers):
    res = client.post(
        "/users",
        headers=viewer_headers,
        json={"name": "By Viewer", "email": "byviewer@test.dev", "password": "pw"},
    )

    assert res.status_code == 401


def test_owner_can_still_invite(client, owner_headers):
    email = f"invited_{secrets.token_hex(4)}@test.dev"
    res = client.post(
        "/users",
        headers=owner_headers,
        json={"name": "Invited", "email": email, "password": "pw", "role": "viewer"},
    )

    assert res.status_code == 201
    assert res.json()["role"] == "viewer"


def test_unknown_role_is_rejected(client, owner_headers):
    res = client.post(
        "/users",
        headers=owner_headers,
        json={
            "name": "Weird Role",
            "email": f"weird_{secrets.token_hex(4)}@test.dev",
            "password": "pw",
            "role": "superadmin",
        },
    )

    assert res.status_code == 400


# ---------------------------------------------------------------------------
# Login throttling
# ---------------------------------------------------------------------------
def test_repeated_bad_logins_are_locked_out(client):
    creds = {"email": "owner@test.dev", "password": "definitely-wrong"}

    codes = [client.post("/login", json=creds).status_code for _ in range(7)]

    assert codes[:5] == [401] * 5, "first attempts should be plain auth failures"
    assert 429 in codes[5:], "lockout should engage after the attempt budget"


def test_lockout_response_carries_retry_after(client):
    creds = {"email": "retry@test.dev", "password": "wrong"}
    for _ in range(6):
        res = client.post("/login", json=creds)

    assert res.status_code == 429
    assert int(res.headers["Retry-After"]) > 0


def test_failed_logins_do_not_reveal_whether_an_account_exists(client):
    known = client.post("/login", json={"email": "owner@test.dev", "password": "wrong"})
    unknown = client.post(
        "/login", json={"email": "nobody@nowhere.test", "password": "wrong"}
    )

    assert known.status_code == unknown.status_code == 401
    assert known.json()["detail"] == unknown.json()["detail"]


def test_successful_login_clears_the_failure_count():
    limiter = LoginRateLimiter(max_attempts=3, window_seconds=300)

    limiter.record_failure("account:a@b.c")
    limiter.record_failure("account:a@b.c")
    limiter.reset("account:a@b.c")
    limiter.record_failure("account:a@b.c")

    assert not limiter.is_locked("account:a@b.c")


def test_lockout_is_per_key_not_global():
    limiter = LoginRateLimiter(max_attempts=2, window_seconds=300)

    limiter.record_failure("account:victim@x.y")
    limiter.record_failure("account:victim@x.y")

    assert limiter.is_locked("account:victim@x.y")
    assert not limiter.is_locked("account:someone-else@x.y")


# ---------------------------------------------------------------------------
# Transport / app configuration
# ---------------------------------------------------------------------------
def test_cors_is_not_a_wildcard_while_credentials_are_allowed():
    """'*' plus credentials would let any site drive the API as a logged-in user."""
    from backend.main import app

    cors = app.cors_config
    assert cors is not None
    assert "*" not in cors.allow_origins
    assert cors.allow_credentials is True


def test_request_body_size_is_capped():
    from backend.config import settings
    from backend.main import app

    assert app.request_max_body_size == settings.MAX_UPLOAD_BYTES
    assert settings.MAX_UPLOAD_BYTES <= 32 * 1024 * 1024


def test_production_refuses_the_default_jwt_secret(monkeypatch):
    from backend import main
    from backend.config import settings

    monkeypatch.setattr(settings, "ENVIRONMENT", "production")
    monkeypatch.setattr(settings, "JWT_SECRET", "change_this_in_production")

    with pytest.raises(RuntimeError, match="JWT_SECRET"):
        main._check_production_config()


def test_production_refuses_wildcard_cors(monkeypatch):
    from backend import main
    from backend.config import settings

    monkeypatch.setattr(settings, "ENVIRONMENT", "production")
    monkeypatch.setattr(settings, "JWT_SECRET", "x" * 40)
    monkeypatch.setattr(settings, "CORS_ALLOW_ORIGINS", "*")

    with pytest.raises(RuntimeError, match="CORS"):
        main._check_production_config()


def test_development_tolerates_defaults(monkeypatch):
    from backend import main
    from backend.config import settings

    monkeypatch.setattr(settings, "ENVIRONMENT", "development")
    monkeypatch.setattr(settings, "JWT_SECRET", "change_this_in_production")

    main._check_production_config()  # must not raise


# ---------------------------------------------------------------------------
# Token handling
# ---------------------------------------------------------------------------
def test_device_token_is_not_accepted_as_a_user_token(client):
    """Device tokens authenticate hardware, not people."""
    res = client.get("/users", headers={"Authorization": f"Bearer {DEV1_TOKEN}"})

    assert res.status_code == 401
