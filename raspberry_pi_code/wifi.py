"""The Wi-Fi signal this Pi reports in its heartbeat.

The kernel lists every wireless interface in /proc/net/wireless, with the
signal level in dBm. Reading the file needs no subprocess and no root.
"""
from pathlib import Path

PROC_WIRELESS = Path("/proc/net/wireless")

# Below this the link drops frames and an upload can stall. -70 dBm is the
# usual line between a usable and a poor Wi-Fi link.
WEAK_BELOW_DBM = -70.0


def signal_dbm(path: Path = PROC_WIRELESS) -> float | None:
    """The first wireless interface's signal level, or None.

    None means no wireless interface, for example a Pi on Ethernet, or a file
    this code cannot parse.
    """
    try:
        lines = path.read_text().splitlines()
    except OSError:
        return None
    # Two header lines, then one line per interface:
    #   wlan0: 0000   54.  -56.  -256   0 0 0 0 0   0
    for line in lines[2:]:
        _, sep, rest = line.partition(":")
        fields = rest.split()
        if not sep or len(fields) < 3:
            continue
        try:
            level = float(fields[2].rstrip("."))
        except ValueError:
            continue
        # Some drivers report the level as an unsigned byte.
        return level - 256 if level > 0 else level
    return None


def read_signal(path: Path = PROC_WIRELESS) -> str | None:
    """'good' or 'weak' for the backend, or None when there is no Wi-Fi."""
    dbm = signal_dbm(path)
    if dbm is None:
        return None
    return "weak" if dbm < WEAK_BELOW_DBM else "good"
