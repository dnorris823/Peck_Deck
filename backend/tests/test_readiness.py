"""Liveness vs readiness semantics.

/health must never touch the database — a liveness probe that fails on a
transient DB blip gets a healthy container restarted. /ready must fail closed
when the database is unreachable or the schema isn't migrated.
"""
import pytest

from backend import readiness


def test_health_is_ok_and_does_not_touch_the_database(client, monkeypatch):
    def explode():
        raise AssertionError("/health must not open a database session")

    monkeypatch.setattr(readiness, "get_session_factory", explode)

    resp = client.get("/health")

    assert resp.status_code == 200
    assert resp.json() == {"status": "ok"}


def test_expected_revisions_includes_the_baseline():
    revisions = readiness.expected_revisions()

    assert revisions, "no migration revisions found on disk"
    assert "25d65b9ab024" in revisions, "baseline revision missing from migrations/"


@pytest.mark.parametrize(
    "db_revision, expected_status, expected_migrations",
    [
        ("25d65b9ab024", 200, "ok"),
        (None, 503, "not_applied"),
        ("deadbeefcafe", 503, "unknown_revision"),
    ],
)
def test_ready_reflects_migration_state(
    client, monkeypatch, db_revision, expected_status, expected_migrations
):
    class _Result:
        def scalar_one_or_none(self):
            return db_revision

    class _Session:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *_):
            return False

        async def execute(self, *_a, **_k):
            return _Result()

    monkeypatch.setattr(readiness, "get_session_factory", lambda: (lambda: _Session()))

    resp = client.get("/ready")

    assert resp.status_code == expected_status
    body = resp.json()
    assert body["database"] == "ok"
    assert body["migrations"] == expected_migrations
    assert body["status"] == ("ready" if expected_status == 200 else "not_ready")


def test_ready_fails_closed_when_the_database_is_unreachable(client, monkeypatch):
    class _Session:
        async def __aenter__(self):
            raise OSError("connection refused")

        async def __aexit__(self, *_):
            return False

    monkeypatch.setattr(readiness, "get_session_factory", lambda: (lambda: _Session()))

    resp = client.get("/ready")

    assert resp.status_code == 503
    body = resp.json()
    assert body["status"] == "not_ready"
    assert body["database"] == "unreachable"
    assert body["error"] == "OSError"
