"""The free disk and CPU temperature this Pi reports in its heartbeat.

Either one stops a Pi without warning. A full SD card fails every capture and
every queue write, and a hot Pi 5 throttles until classification falls behind.
"""
import shutil
from pathlib import Path

THERMAL_ZONE = Path("/sys/class/thermal/thermal_zone0/temp")


def disk_free_bytes(path: str) -> int | None:
    """Free bytes on the file system that holds ``path``, or None."""
    try:
        return shutil.disk_usage(path).free
    except OSError:
        return None


def cpu_temp_c(path: Path = THERMAL_ZONE) -> float | None:
    """The CPU temperature in °C, or None off a Pi.

    The kernel writes millidegrees, such as ``52312``.
    """
    try:
        return round(int(path.read_text().strip()) / 1000, 1)
    except (OSError, ValueError):
        return None


def read_vitals(cache_dir: str) -> dict:
    """Both readings as heartbeat fields. Reads files, so call it off the loop."""
    return {"disk_free_bytes": disk_free_bytes(cache_dir), "cpu_temp_c": cpu_temp_c()}
