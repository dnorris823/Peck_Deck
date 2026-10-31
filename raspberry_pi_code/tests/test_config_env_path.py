"""Which ``.env`` the Pi reads.

The Pi reads ``raspberry_pi_code/.env`` and nothing else. A bare ``load_dotenv()``
searched upward and stopped at the first file. Provisioning writes a token-only
``raspberry_pi_code/.env``, so it hid the repo root ``.env`` and every other
setting fell back to its default. Uploads then went to ``192.168.1.100`` and
queued, with nothing failing loudly.

Each case copies ``config.py`` into a scratch tree with a ``.env`` beside it and
one above it, and imports it in a fresh interpreter. ``load_dotenv`` writes to
``os.environ``, so a subprocess keeps one case from leaking into the next.
"""
import os
import shutil
import subprocess
import sys
from pathlib import Path

import raspberry_pi_code.config as config

DEFAULT_BACKEND = "http://192.168.1.100:8000"


def _backend_url(tmp_path: Path, *, package_env: str | None, root_env: str | None) -> str:
    package = tmp_path / "pkg"
    package.mkdir(parents=True)
    shutil.copy(config.__file__, package / "config.py")
    if package_env is not None:
        (package / ".env").write_text(package_env)
    if root_env is not None:
        (tmp_path / ".env").write_text(root_env)

    env = {k: v for k, v in os.environ.items() if k != "BACKEND_URL"}
    result = subprocess.run(
        [sys.executable, "-c", "import config; print(config.Config().backend_url)"],
        cwd=package,
        env=env,
        capture_output=True,
        text=True,
        check=True,
    )
    return result.stdout.strip()


def test_reads_the_package_env(tmp_path):
    url = _backend_url(tmp_path, package_env="BACKEND_URL=http://pkg:8000\n", root_env=None)

    assert url == "http://pkg:8000"


def test_ignores_a_root_env(tmp_path):
    """A root ``.env`` must not count, with or without a package one.

    Before the fix this returned ``http://root:8000`` while the package file was
    missing, and the default once provisioning created it. The answer depended
    on whether provisioning had ever succeeded.
    """
    alone = _backend_url(tmp_path / "a", package_env=None, root_env="BACKEND_URL=http://root:8000\n")
    beside_token = _backend_url(
        tmp_path / "b", package_env="DEVICE_TOKEN=abc\n", root_env="BACKEND_URL=http://root:8000\n"
    )

    assert alone == DEFAULT_BACKEND
    assert beside_token == DEFAULT_BACKEND


def test_env_path_is_beside_config():
    assert config.ENV_PATH == Path(config.__file__).with_name(".env")
