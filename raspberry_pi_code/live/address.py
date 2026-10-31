"""The live_url this Pi reports in its heartbeat.

The backend POSTs WHEP offers to this URL, so it accepts only http or https on a
private IPv4 host. A URL it refuses fails the whole heartbeat, and the station
would read offline. So the Pi applies the same rule and sends no URL instead.
"""
import ipaddress
import logging
import socket
from urllib.parse import urlsplit

logger = logging.getLogger(__name__)

WHEP_PORT = 8889
WHEP_PATH = "/feeder/whep"

# The backend's list. 100.64/10 is the Tailscale range.
_ALLOWED_NETWORKS = tuple(
    ipaddress.ip_network(n)
    for n in ("10.0.0.0/8", "172.16.0.0/12", "192.168.0.0/16", "100.64.0.0/10")
)


def is_acceptable(url: str) -> bool:
    """True when the backend will accept ``url`` as a live_url."""
    try:
        parts = urlsplit(url)
        host = ipaddress.ip_address(parts.hostname or "")
    except ValueError:
        return False
    if parts.scheme not in ("http", "https"):
        return False
    return any(host in net for net in _ALLOWED_NETWORKS)


def local_address_toward(url: str) -> str | None:
    """This host's IPv4 address on the route to ``url``'s host.

    A UDP connect picks the route and the source address without sending a
    packet. Returns None when there is no route, or the name does not resolve.
    """
    parts = urlsplit(url)
    if not parts.hostname:
        return None
    port = parts.port or (443 if parts.scheme == "https" else 80)
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
            sock.connect((parts.hostname, port))
            return sock.getsockname()[0]
    except OSError:
        return None


def derive_live_url(backend_url: str) -> str | None:
    """``http://<lan-ip>:8889/feeder/whep``, where the backend can reach <lan-ip>."""
    ip = local_address_toward(backend_url)
    if ip is None:
        return None
    return f"http://{ip}:{WHEP_PORT}{WHEP_PATH}"


class LiveUrl:
    """Works out the live_url for each heartbeat.

    Derives it again on every call, because the Pi's address comes from DHCP and
    may change under a running service. Logs a URL the backend would refuse once
    per distinct value, not once per heartbeat.
    """

    def __init__(self, explicit: str, backend_url: str):
        self._explicit = explicit.strip()
        self._backend_url = backend_url
        self._warned: str | None = None

    def __call__(self) -> str | None:
        url = self._explicit or derive_live_url(self._backend_url)
        if url is None:
            return None
        if not is_acceptable(url):
            if url != self._warned:
                source = "LIVE_URL" if self._explicit else "The derived live URL"
                logger.warning(
                    "%s %r is not http(s) on a private IPv4 address. The backend "
                    "would refuse it, so the heartbeat sends no live_url",
                    source, url,
                )
                self._warned = url
            return None
        return url
