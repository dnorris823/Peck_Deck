"""scripts/install_pi.sh, run off a Pi.

The script runs for real in bash. Every command that would touch the Pi is a
stub on PATH: sudo runs its command as the test user, and apt-get, systemctl,
nmcli, tailscale, curl and the venv's python log their arguments. The root
paths point into tmp_path. What this cannot show is listed in the PR: a real
apt, pip, MediaMTX download, NetworkManager, and systemd.
"""
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts" / "install_pi.sh"


BASH = shutil.which("bash")
# The script targets Linux. Git Bash on Windows cannot set the file modes it
# sets, so these run in CI and in a Linux container.
pytestmark = pytest.mark.skipif(
    BASH is None or sys.platform == "win32", reason="needs bash on Linux",
)

TAILNET_IP = "100.101.102.103"
PASSWORD = "app-password-1"
LIVE_PASSWORD = "live-password-1"
HOME_PSK = "home-wifi-psk"
RESCUE_PSK = "rescue-hotspot-psk"

FRESH_ANSWERS = [
    "100.64.0.1",        # gaming PC
    "peck-lakehouse",    # feeder name
    "kin@example.com",   # account email
    PASSWORD,
    "peck-live",         # live user
    LIVE_PASSWORD,
    "Lakehouse WiFi",    # home Wi-Fi
    HOME_PSK,
    "Dad's iPhone",      # rescue hotspot
    RESCUE_PSK,
]
# Enter at every prompt keeps every saved answer.
KEEP_ANSWERS = [""] * 10

STUBS = {
    "sudo": """
        [ "$1" = -v ] && exit 0
        exec "$@"
    """,
    "apt-get": "",
    "systemctl": """
        [ "$1" = is-active ] && echo active
        exit 0
    """,
    "tailscale": f'[ "$1 $2" = "ip -4" ] && echo {TAILNET_IP}',
    "hostname": "echo peck-test",
    "rpicam-hello": "echo 'Available cameras'; echo '0 : imx708_wide'",
    "curl": """
        for a in "$@"; do
          case "$a" in *"$CURL_FAIL"*) [ -n "$CURL_FAIL" ] && exit 22 ;; esac
        done
        exit 0
    """,
    # python3 -m venv makes a venv whose python is the next stub.
    "python3": """
        if [ "$1" = -m ] && [ "$2" = venv ]; then
          for last in "$@"; do :; done
          mkdir -p "$last/bin"
          cp "$STUB_DIR/venv-python" "$last/bin/python"
        fi
    """,
    "venv-python": """
        case "$*" in *provision_device.py*)
          echo "provision: email=$PECK_OWNER_EMAIL name=$DEVICE_NAME password_set=${PECK_OWNER_PASSWORD:+yes}"
          echo "${PROVISION_SAYS:-provision: matched existing device '$DEVICE_NAME' (id 7)}"
          exit "${PROVISION_EXIT:-0}" ;;
        esac
    """,
    # Profiles live in $NM_STATE as name|ssid lines.
    "nmcli": """
        touch "$NM_STATE"
        if [ "$1 $2 $3 $4" = "-t -f NAME connection" ]; then cut -d'|' -f1 "$NM_STATE"; exit 0; fi
        if [ "$1" = -g ]; then grep "^$5|" "$NM_STATE" | cut -d'|' -f2; exit 0; fi
        name=""; ssid=""; prev=""
        for a in "$@"; do
          case "$prev" in con-name) name=$a ;; ssid|802-11-wireless.ssid) ssid=$a ;; esac
          prev=$a
        done
        if [ "$2" = modify ]; then
          name=$3
          grep -v "^$name|" "$NM_STATE" > "$NM_STATE.tmp" || true
          mv "$NM_STATE.tmp" "$NM_STATE"
        fi
        echo "$name|$ssid" >> "$NM_STATE"
    """,
}


@pytest.fixture
def pi(tmp_path):
    """A copy of the repo's Pi files, the stubs, and the root dirs."""
    repo = tmp_path / "repo"
    (repo / "scripts").mkdir(parents=True)
    (repo / "raspberry_pi_code").mkdir()
    shutil.copy(SCRIPT, repo / "scripts" / "install_pi.sh")
    shutil.copy(ROOT / "raspberry_pi_code" / ".env.example", repo / "raspberry_pi_code" / ".env.example")

    stubs = tmp_path / "stubs"
    stubs.mkdir()
    for name, body in STUBS.items():
        path = stubs / name
        lines = [line[8:] if line.startswith(" " * 8) else line for line in body.splitlines()]
        log = f'echo "{name} $*" >> "$STUB_LOG"\n'
        path.write_text("#!/usr/bin/env bash\n" + log + "\n".join(lines) + "\n", newline="\n")
        path.chmod(0o755)

    mediamtx = tmp_path / "opt"
    mediamtx.mkdir()
    (mediamtx / "mediamtx").write_text("#!/usr/bin/env bash\necho v1.21.3\n", newline="\n")
    (mediamtx / "mediamtx").chmod(0o755)

    home = tmp_path / "home"
    home.mkdir()
    env = {
        **os.environ,
        "PATH": f"{stubs}{os.pathsep}{os.environ['PATH']}",
        "HOME": str(home),
        "STUB_DIR": stubs.as_posix(),
        "STUB_LOG": (tmp_path / "calls.log").as_posix(),
        "NM_STATE": (tmp_path / "nm.state").as_posix(),
        "PECK_ETC_DIR": (tmp_path / "etc").as_posix(),
        "PECK_UNIT_DIR": (tmp_path / "units").as_posix(),
        "PECK_MEDIAMTX_DIR": mediamtx.as_posix(),
        "CURL_FAIL": "",
    }
    (tmp_path / "units").mkdir()

    class Pi:
        root = tmp_path
        pi_env = repo / "raspberry_pi_code" / ".env"
        etc = tmp_path / "etc"
        units = tmp_path / "units"

        def run(self, answers, *args, **extra_env):
            (tmp_path / "calls.log").write_text("")
            # Bytes in and out, so Windows does not turn \n into \r\n.
            result = subprocess.run(
                [BASH, (repo / "scripts" / "install_pi.sh").as_posix(), *args],
                input=("\n".join(answers) + "\n").encode(),
                capture_output=True,
                env={**env, **extra_env},
                timeout=60,
            )
            result.stdout = result.stdout.decode()
            result.stderr = result.stderr.decode()
            return result

        def calls(self):
            return (tmp_path / "calls.log").read_text().splitlines()

        def profiles(self):
            path = tmp_path / "nm.state"
            return path.read_text().splitlines() if path.exists() else []

    return Pi()


def _ok(result):
    assert result.returncode == 0, result.stdout + result.stderr
    return result


def _env(path):
    return dict(
        line.split("=", 1) for line in path.read_text().splitlines()
        if "=" in line and not line.startswith("#")
    )


def test_fresh_install_writes_every_file(pi):
    _ok(pi.run(FRESH_ANSWERS))

    env = _env(pi.pi_env)
    assert env["BACKEND_URL"] == "http://100.64.0.1:8000"
    assert env["INFERENCE_SERVER_URL"] == "http://100.64.0.1:8001"
    assert env["CACHE_DIR"].endswith("/peck_deck_cache")
    # Keys the script does not own come from the example, untouched.
    assert env["TIER_PREFERENCE"] == "gpu"
    assert env["DEVICE_TOKEN"] == "your_device_token_here"

    assert (pi.etc / "owner.env").read_text() == (
        f"PECK_OWNER_EMAIL=kin@example.com\nPECK_OWNER_PASSWORD={PASSWORD}\nDEVICE_NAME=peck-lakehouse\n"
    )
    assert (pi.etc / "mediamtx.env").read_text() == (
        f"MTX_AUTHINTERNALUSERS_1_USER=peck-live\nMTX_AUTHINTERNALUSERS_1_PASS={LIVE_PASSWORD}\n"
        f"MTX_WEBRTCADDITIONALHOSTS={TAILNET_IP}\n"
    )
    assert (pi.etc / "owner.env").stat().st_mode & 0o777 == 0o600
    assert (pi.etc / "mediamtx.env").stat().st_mode & 0o777 == 0o600
    assert pi.pi_env.stat().st_mode & 0o777 == 0o600


def test_units_run_as_the_installing_user_from_the_repo(pi):
    _ok(pi.run(FRESH_ANSWERS))
    user = subprocess.run([BASH, "-c", "id -un"], capture_output=True, text=True).stdout.strip()

    service = (pi.units / "peck-deck.service").read_text()
    assert f"User={user}\n" in service
    assert "/repo/.venv/bin/python -m raspberry_pi_code.main" in service
    # Both leading dashes keep a Pi with the gaming PC off starting up.
    assert "\nEnvironmentFile=-" in service
    assert "\nExecStartPre=-" in service

    mediamtx = (pi.units / "mediamtx.service").read_text()
    assert f"User={user}\n" in mediamtx
    assert "\nEnvironmentFile=" in mediamtx and "\nEnvironmentFile=-" not in mediamtx
    assert "/repo/raspberry_pi_code/live/mediamtx.yml" in mediamtx

    calls = pi.calls()
    assert "systemctl daemon-reload" in calls
    assert "systemctl enable peck-deck mediamtx" in calls
    assert "systemctl restart peck-deck mediamtx" in calls


def test_provisioning_gets_credentials_from_the_environment(pi):
    result = _ok(pi.run(FRESH_ANSWERS))
    assert "email=kin@example.com name=peck-lakehouse password_set=yes" in result.stdout
    provision = [c for c in pi.calls() if "provision_device.py" in c]
    assert provision == ["venv-python scripts/provision_device.py"]


def test_no_secret_reaches_a_command_line(pi):
    _ok(pi.run(FRESH_ANSWERS))
    # sudo logs its command line to the journal, and argv shows in ps.
    # nmcli inside the root shell is the one place a Wi-Fi password is an argument.
    for call in pi.calls():
        if call.startswith("nmcli "):
            continue
        for secret in (PASSWORD, LIVE_PASSWORD, HOME_PSK, RESCUE_PSK):
            assert secret not in call, call


def test_wifi_is_saved_and_never_brought_up(pi):
    _ok(pi.run(FRESH_ANSWERS))
    assert pi.profiles() == ["peck-home|Lakehouse WiFi", "peck-rescue|Dad's iPhone"]
    nmcli = [c for c in pi.calls() if c.startswith("nmcli connection ")]
    assert [c.split()[2] for c in nmcli] == ["add", "add"]
    assert "connection.autoconnect-priority 0" in nmcli[0]
    assert "connection.autoconnect-priority -10" in nmcli[1]
    assert not any(" up " in c or " down " in c for c in nmcli)


def test_second_run_keeps_every_answer_and_the_token(pi):
    _ok(pi.run(FRESH_ANSWERS))
    # Provisioning writes the token between runs.
    pi.pi_env.write_text(pi.pi_env.read_text().replace("your_device_token_here", "tok-123"))
    before = {p: p.read_text() for p in [pi.pi_env, pi.etc / "owner.env", pi.etc / "mediamtx.env",
                                         pi.units / "peck-deck.service", pi.units / "mediamtx.service"]}

    result = _ok(pi.run(KEEP_ANSWERS))

    assert {p: p.read_text() for p in before} == before
    assert _env(pi.pi_env)["DEVICE_TOKEN"] == "tok-123"
    calls = pi.calls()
    assert "systemctl daemon-reload" not in calls
    assert not any(c.startswith("nmcli connection ") for c in calls)
    assert "kept Home Wi-Fi" in result.stdout
    assert pi.profiles() == ["peck-home|Lakehouse WiFi", "peck-rescue|Dad's iPhone"]


def test_a_new_home_wifi_modifies_the_profile(pi):
    _ok(pi.run(FRESH_ANSWERS))
    _ok(pi.run(["New Router", "new-router-psk", "", ""], "--wifi"))
    assert pi.profiles() == ["peck-rescue|Dad's iPhone", "peck-home|New Router"]
    nmcli = [c for c in pi.calls() if c.startswith("nmcli connection ")]
    assert [c.split()[2] for c in nmcli] == ["modify"]
    # --wifi touches nothing else.
    assert not any(c.startswith(("apt-get", "systemctl")) for c in pi.calls())


def test_dry_run_changes_nothing_and_prints_no_secret(pi):
    result = _ok(pi.run(FRESH_ANSWERS, "--dry-run"))

    assert not pi.pi_env.exists()
    assert not (pi.etc / "owner.env").exists()
    assert list(pi.units.iterdir()) == []
    assert pi.profiles() == []
    calls = pi.calls()
    assert not any(c.startswith(("apt-get", "systemctl", "venv-python", "python3")) for c in calls)
    assert not any(c.startswith("nmcli connection ") for c in calls)

    out = result.stdout + result.stderr
    assert "would run: sudo systemctl restart peck-deck mediamtx" in out
    assert "PECK_OWNER_PASSWORD=********" in out
    for secret in (PASSWORD, LIVE_PASSWORD, HOME_PSK, RESCUE_PSK):
        assert secret not in out


def test_an_unreachable_backend_stops_before_the_services_start(pi):
    result = pi.run(FRESH_ANSWERS, CURL_FAIL="/ready")
    assert result.returncode != 0
    assert "does not answer /ready" in result.stderr
    assert not any(c.startswith(("systemctl enable", "systemctl restart")) for c in pi.calls())
    assert not any("provision_device.py" in c for c in pi.calls())


def test_tier2_down_is_only_a_warning(pi):
    result = _ok(pi.run(FRESH_ANSWERS, CURL_FAIL="/health"))
    assert "Tier 2 at http://100.64.0.1:8001 does not answer" in result.stderr
    assert "systemctl restart peck-deck mediamtx" in pi.calls()


def test_failed_provisioning_stops_the_install(pi):
    result = pi.run(FRESH_ANSWERS, PROVISION_EXIT="1", PROVISION_SAYS="provision: login failed (401)")
    assert result.returncode != 0
    assert "login failed (401)" in result.stdout
    assert "systemctl restart peck-deck mediamtx" not in pi.calls()


def test_a_new_registration_is_flagged(pi):
    result = _ok(pi.run(FRESH_ANSWERS, PROVISION_SAYS="provision: registered new device 'peck-lakehouse' (id 9)"))
    assert "remove the extra feeder" in result.stderr


def test_bad_answers_ask_again(pi):
    answers = list(FRESH_ANSWERS)
    answers[0:1] = ["http://100.64.0.1:8000", "100.64.0.1"]
    answers[4:5] = ['has"quote', PASSWORD]  # account password, shifted by one
    answers[9:10] = ["short", HOME_PSK]     # home Wi-Fi password, shifted by two
    result = _ok(pi.run(answers))
    assert "no http:// and no port" in result.stderr
    assert "Quotes and backslashes" in result.stderr
    assert "8 to 63 characters" in result.stderr
    assert _env(pi.etc / "owner.env")["PECK_OWNER_PASSWORD"] == PASSWORD
