"""Which ``live_url`` a feeder may report.

The backend POSTs browser offers to this URL, so a device token must not be able
to point it at an arbitrary host. Only an IP literal on a private network is
accepted. A hostname is refused, because it could resolve somewhere else by the
time the relay connects.
"""
from ipaddress import IPv4Address, ip_address, ip_network
from urllib.parse import urlsplit

# RFC 1918 LAN ranges, and 100.64/10 for Tailscale.
ALLOWED_NETWORKS = [
    ip_network("10.0.0.0/8"),
    ip_network("172.16.0.0/12"),
    ip_network("192.168.0.0/16"),
    ip_network("100.64.0.0/10"),
]

MAX_LIVE_URL_LENGTH = 2048


def check_live_url(url: str) -> str | None:
    """The reason ``url`` is refused, or None if a feeder may report it."""
    if len(url) > MAX_LIVE_URL_LENGTH:
        return "live_url is too long"
    try:
        parts = urlsplit(url)
        parts.port  # raises on a port that is not a number
    except ValueError:
        return "live_url is not a valid URL"
    if parts.scheme not in ("http", "https"):
        return "live_url must be http or https"
    if parts.username is not None or parts.password is not None:
        return "live_url must not carry credentials"
    try:
        host = ip_address(parts.hostname or "")
    except ValueError:
        return "live_url host must be an IP address"
    if not isinstance(host, IPv4Address) or not any(host in n for n in ALLOWED_NETWORKS):
        return "live_url host must be a private address"
    return None
