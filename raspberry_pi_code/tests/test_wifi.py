"""The Wi-Fi signal in the heartbeat, read from /proc/net/wireless."""
from raspberry_pi_code.wifi import read_signal, signal_dbm

HEADER = (
    "Inter-| sta-|   Quality        |   Discarded packets               | Missed | WE\n"
    " face | tus | link level noise |  nwid  crypt   frag  retry   misc | beacon | 22\n"
)


def _proc(tmp_path, body):
    path = tmp_path / "wireless"
    path.write_text(HEADER + body)
    return path


def test_strong_link_is_good(tmp_path):
    path = _proc(tmp_path, " wlan0: 0000   54.  -56.  -256        0      0      0      0      0        0\n")
    assert signal_dbm(path) == -56.0
    assert read_signal(path) == "good"


def test_poor_link_is_weak(tmp_path):
    path = _proc(tmp_path, " wlan0: 0000   20.  -78.  -256        0      0      0      0      0        0\n")
    assert read_signal(path) == "weak"


def test_unsigned_level_is_read_as_dbm(tmp_path):
    # 200 as an unsigned byte is -56 dBm.
    path = _proc(tmp_path, " wlan0: 0000   54.  200.  -256        0      0      0      0      0        0\n")
    assert signal_dbm(path) == -56.0


def test_no_wireless_interface_reports_nothing(tmp_path):
    # Ethernet only: the header and no interface lines.
    assert read_signal(_proc(tmp_path, "")) is None


def test_missing_file_reports_nothing(tmp_path):
    assert read_signal(tmp_path / "absent") is None
