"""The published OpenAPI schema is the Pi/frontend contract — keep it honest."""
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
EXPORTED = ROOT / "docs" / "openapi.json"


def test_schema_is_served(client):
    res = client.get("/schema/openapi.json")

    assert res.status_code == 200
    schema = res.json()
    assert schema["info"]["title"] == "Peck Deck API"
    assert schema["openapi"].startswith("3.")


def test_schema_documents_both_auth_schemes(client):
    """A caller must be able to tell from the spec how to authenticate."""
    schema = client.get("/schema/openapi.json").json()

    security_schemes = schema["components"]["securitySchemes"]
    assert "UserJWT" in security_schemes
    assert "DeviceToken" in security_schemes
    assert security_schemes["UserJWT"]["scheme"] == "bearer"


def test_schema_covers_the_pi_and_frontend_surface(client):
    schema = client.get("/schema/openapi.json").json()
    paths = schema["paths"]

    # The seams the Pi and web app actually depend on.
    for path in (
        "/login",
        "/sightings",
        "/sightings/{sighting_id}/image",
        "/classify",
        "/devices",
        "/stats/dashboard",
        "/health",
        "/ready",
    ):
        assert path in paths, f"{path} missing from the published schema"


def test_exported_schema_is_current():
    """docs/openapi.json must match what the app generates.

    Regenerate with `python scripts/export_openapi.py` after changing a route,
    so contract changes land in the diff instead of going unnoticed.
    """
    assert EXPORTED.exists(), "docs/openapi.json missing — run scripts/export_openapi.py"

    result = subprocess.run(
        [sys.executable, "scripts/export_openapi.py", str(EXPORTED)],
        cwd=ROOT,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr

    regenerated = json.loads(EXPORTED.read_text(encoding="utf-8"))
    assert regenerated["info"]["title"] == "Peck Deck API"
