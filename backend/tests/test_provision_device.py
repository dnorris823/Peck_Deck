"""scripts/provision_device.py against the real app.

The script talks urllib to a live backend. Here its one HTTP helper is routed
into the Litestar TestClient, so the routes it depends on are the real ones.
"""
import importlib.util
import secrets
from pathlib import Path

import pytest

from backend.auth.jwt_utils import create_user_token
from backend.tests.conftest import IDS

_SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "provision_device.py"


@pytest.fixture
def provision(client, tmp_path, monkeypatch):
    spec = importlib.util.spec_from_file_location("provision_device", _SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    def request(method, url, *, token=None, body=None):
        headers = {"Authorization": f"Bearer {token}"} if token else {}
        res = client.request(method, url.removeprefix("http://api"), headers=headers, json=body)
        return res.status_code, res.json() if res.content else {}

    env_path = tmp_path / ".env"
    monkeypatch.setattr(module, "request", request)
    monkeypatch.setattr(module, "ENV_PATH", env_path)
    monkeypatch.setattr("sys.argv", ["provision_device.py"])
    monkeypatch.setenv("BACKEND_URL", "http://api")

    # A throwaway owner with a known password, so the script can sign in.
    email = f"prov_{secrets.token_hex(4)}@test.dev"
    seeded_owner = {"Authorization": f"Bearer {create_user_token(IDS['owner_id'], 'owner')}"}
    client.post("/users", headers=seeded_owner, json={
        "name": "Provisioner", "email": email, "password": "pw", "role": "owner",
    })
    monkeypatch.setenv("PECK_OWNER_EMAIL", email)
    monkeypatch.setenv("PECK_OWNER_PASSWORD", "pw")
    return module, env_path


def _token_in(env_path: Path) -> str:
    line = next(l for l in env_path.read_text().splitlines() if l.startswith("DEVICE_TOKEN="))
    return line.partition("=")[2]


def test_provisions_a_new_device_then_the_existing_one(client, provision, monkeypatch):
    module, env_path = provision
    monkeypatch.setenv("DEVICE_NAME", f"pi-{secrets.token_hex(4)}")

    module.main()  # no device by that name, so it registers one
    first = _token_in(env_path)

    module.main()  # now it matches the device and reads the token back
    assert _token_in(env_path) == first

    beat = client.post("/devices/me/heartbeat", json={},
                       headers={"Authorization": f"Bearer {first}"})
    assert beat.status_code == 200
