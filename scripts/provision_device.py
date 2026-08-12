#!/usr/bin/env python3
"""Put a valid ``DEVICE_TOKEN`` in the Pi's ``.env``, unattended.

Decided in *How the Pi gets a device token, this time and next* (#38). The Pi runs
this on itself as a systemd ``ExecStartPre``; there is no enrolment endpoint and no
hand-paste over SSH.

Why it exists: ``device_guard`` is a plain equality match on ``Device.token`` with no
expiry or rotation, so a stale token is indistinguishable from a wrong one — 401
forever, with the offline queue filling silently behind it. Tokens go stale because
``backend/seed.py`` mints a fresh ``secrets.token_urlsafe(32)`` on every seed, so
wiping the database volume orphans whatever the Pi is holding. Rather than make tokens
survive a reseed, re-provisioning costs one command that runs itself.

    python scripts/provision_device.py

Credentials come from the environment, never from ``argv`` — a password on the command
line lands in shell history and in ``ps``:

    PECK_OWNER_EMAIL      owner account email
    PECK_OWNER_PASSWORD   owner account password
    BACKEND_URL           defaults to the Pi's own .env value, else http://localhost:8000
    DEVICE_NAME           defaults to the hostname

Keep those in a root-owned 0600 file wired in as ``EnvironmentFile=`` — deliberately
*not* the Pi's ``.env``, which this script rewrites and the pipeline reads. **The
escalation is accepted knowingly** (#38): the owner account can mint users, and this
puts it on the most physically exposed machine in the system.

Only the standard library, on purpose. It runs before the service starts, so it must
not depend on the app's async stack being importable.
"""

import json
import os
import socket
import sys
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ENV_PATH = ROOT / "raspberry_pi_code" / ".env"
TIMEOUT = 15


def fail(message: str) -> None:
    """Exit non-zero without touching .env.

    `ExecStartPre` carries a leading `-` so this is non-fatal to the unit: a Pi
    booting while the gaming PC is switched off must still start and capture into
    the offline queue. That is the queue's entire purpose, so a failure here has to
    leave the existing token exactly as it was.
    """
    print(f"provision: {message}", file=sys.stderr)
    print("provision: .env left untouched", file=sys.stderr)
    sys.exit(1)


def request(method: str, url: str, *, token: str = None, body: dict = None) -> tuple[int, dict]:
    data = json.dumps(body).encode() if body is not None else None
    headers = {"Accept": "application/json"}
    if data is not None:
        headers["Content-Type"] = "application/json"
    if token:
        headers["Authorization"] = f"Bearer {token}"

    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT) as response:
            raw = response.read().decode() or "{}"
            return response.status, json.loads(raw)
    except urllib.error.HTTPError as exc:
        raw = exc.read().decode() or "{}"
        try:
            return exc.code, json.loads(raw)
        except json.JSONDecodeError:
            return exc.code, {"detail": raw[:200]}
    except (urllib.error.URLError, socket.timeout) as exc:
        fail(f"cannot reach {url}: {exc}")


def read_env(path: Path) -> dict:
    values = {}
    if not path.exists():
        return values
    for line in path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        values[key.strip()] = value.strip()
    return values


def write_token(path: Path, token: str) -> None:
    """Replace DEVICE_TOKEN in place, preserving every other line.

    Written to a temp file and moved over the original, so an interruption cannot
    leave a truncated .env behind — the file the pipeline reads at import.
    """
    lines = path.read_text().splitlines() if path.exists() else []
    replaced = False
    for i, line in enumerate(lines):
        if line.strip().startswith("DEVICE_TOKEN="):
            lines[i] = f"DEVICE_TOKEN={token}"
            replaced = True
            break
    if not replaced:
        lines.append(f"DEVICE_TOKEN={token}")

    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".provision-tmp")
    tmp.write_text("\n".join(lines) + "\n")
    tmp.replace(path)


def main() -> None:
    # stderr is unbuffered and stdout is not, so without this the failure lines
    # land in journald *above* the banner saying which backend was being talked
    # to — which is the one piece of context a 401 in the logs needs.
    sys.stdout.reconfigure(line_buffering=True)

    if len(sys.argv) > 1:
        fail(
            "takes no arguments — credentials come from PECK_OWNER_EMAIL / "
            "PECK_OWNER_PASSWORD so they stay out of shell history and ps"
        )

    existing = read_env(ENV_PATH)
    api = (os.getenv("BACKEND_URL") or existing.get("BACKEND_URL") or "http://localhost:8000").rstrip("/")
    name = os.getenv("DEVICE_NAME") or existing.get("DEVICE_NAME") or socket.gethostname()
    email = os.getenv("PECK_OWNER_EMAIL")
    password = os.getenv("PECK_OWNER_PASSWORD")

    if not email or not password:
        fail("PECK_OWNER_EMAIL and PECK_OWNER_PASSWORD must be set")

    print(f"provision: backend {api}, device name {name!r}")

    status, payload = request("POST", f"{api}/login", body={"email": email, "password": password})
    if status == 429:
        fail(f"login throttled — {payload.get('detail', 'try again later')}")
    if status not in (200, 201):
        fail(f"login failed ({status}): {payload.get('detail', payload)}")
    jwt = payload.get("access_token")
    if not jwt:
        fail("login succeeded but returned no access_token")

    status, devices = request("GET", f"{api}/devices", token=jwt)
    if status != 200:
        fail(f"GET /devices failed ({status}): {devices}")

    match = next((d for d in devices if d.get("name") == name), None)

    if match is not None:
        # Printed loudly because a DEVICE_NAME typo otherwise registers a second
        # device silently, and sightings split across two rows that both look
        # healthy in the app (#38).
        print(f"provision: matched existing device {name!r} (id {match['id']})")
        device = match
    else:
        known = ", ".join(repr(d.get("name")) for d in devices) or "none visible"
        print(f"provision: no device named {name!r} — registering. Visible: {known}")
        status, device = request("POST", f"{api}/devices", token=jwt, body={"name": name})
        if status == 403:
            fail(
                f"registration refused (403). POST /devices is deliberately not on the "
                f"DEMO_MODE allowlist, so against a demo instance this can only match an "
                f"existing device — and none is named {name!r}. Create it in the web app, "
                f"or set DEVICE_NAME to one of: {known}"
            )
        if status != 201:
            fail(f"POST /devices failed ({status}): {device}")
        print(f"provision: registered new device {name!r} (id {device['id']})")

    token = device.get("token")
    if not token:
        fail(f"device {device.get('id')} came back without a token")

    # Prove the token is accepted before writing it. The heartbeat is the cheapest
    # device-authenticated call there is, and it is on the DEMO_MODE allowlist, so
    # this works everywhere the Pi itself would.
    status, body = request("POST", f"{api}/devices/{device['id']}/heartbeat", token=token, body={})
    if status != 200:
        fail(f"token was refused by the heartbeat check ({status}): {body}")
    print("provision: token accepted by POST /devices/{id}/heartbeat")

    if existing.get("DEVICE_TOKEN") == token:
        print("provision: .env already holds this token — nothing to do")
        return

    write_token(ENV_PATH, token)
    print(f"provision: wrote DEVICE_TOKEN to {ENV_PATH}")
    print("provision: the service reads .env at import — restart it to pick this up")


if __name__ == "__main__":
    main()
