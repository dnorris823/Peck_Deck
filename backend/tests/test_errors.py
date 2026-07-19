"""Tests for the uniform error envelope and request-id propagation."""
from backend.tests.conftest import IDS  # noqa: F401  (ensures seeding import order)

_DEVICE_AUTH = {"Authorization": "Bearer dev1-token"}


def _assert_envelope(body, status_code):
    # Every error body carries the same four keys (extra is optional).
    assert body["status_code"] == status_code
    assert isinstance(body["type"], str) and body["type"]
    assert "detail" in body  # preserved for frontend api.js compatibility
    assert isinstance(body["request_id"], str) and body["request_id"] != "-"


def test_401_uses_uniform_envelope(client):
    res = client.get("/species")
    assert res.status_code == 401
    _assert_envelope(res.json(), 401)


def test_404_uses_uniform_envelope(client, owner_headers):
    res = client.get("/sightings/999999", headers=owner_headers)
    assert res.status_code == 404
    _assert_envelope(res.json(), 404)


def test_validation_error_uses_uniform_envelope(client, owner_headers):
    # Missing required fields on device registration → Litestar 400 validation error.
    res = client.post("/devices", headers=owner_headers, json={})
    assert res.status_code in (400, 500)  # validation → 400
    assert res.status_code == 400
    body = res.json()
    _assert_envelope(body, 400)
    assert "extra" in body  # validation errors carry field-level detail


def test_bad_date_filter_returns_400(client, owner_headers):
    res = client.get("/sightings?from_date=not-a-date", headers=owner_headers)
    assert res.status_code == 400
    _assert_envelope(res.json(), 400)


def test_request_id_echoed_on_success(client, owner_headers):
    res = client.get("/species", headers=owner_headers)
    assert res.status_code == 200
    assert res.headers.get("x-request-id")  # generated and echoed


def test_inbound_request_id_is_preserved(client, owner_headers):
    res = client.get(
        "/species",
        headers={**owner_headers, "X-Request-Id": "my-trace-123"},
    )
    assert res.status_code == 200
    assert res.headers.get("x-request-id") == "my-trace-123"


def test_inbound_request_id_shows_in_error_envelope(client):
    res = client.get("/species", headers={"X-Request-Id": "trace-err-9"})
    assert res.status_code == 401
    assert res.json()["request_id"] == "trace-err-9"
    assert res.headers.get("x-request-id") == "trace-err-9"
