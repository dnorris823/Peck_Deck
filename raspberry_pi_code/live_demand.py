"""Hold the live demand socket open while MediaMTX has viewers.

MediaMTX runs this through ``runOnDemand`` when the first viewer of the
``feeder`` path arrives, and stops it with SIGINT once the last viewer has been
gone for ``runOnDemandCloseAfter``. While it holds a connection, the Pi service
encodes and publishes the feed.

    python -m raspberry_pi_code.live_demand

Exits 1 when the service refuses or drops the connection, so MediaMTX tells the
viewer the feed is not streaming instead of waiting for nothing.
"""
import os
import signal
import socket
import sys


def main() -> int:
    # Read the setting without importing Config, which parses the whole .env
    # and could refuse on an unrelated value. The dotenv load keeps a
    # LIVE_DEMAND_SOCKET set in .env in step with the service.
    from pathlib import Path

    from dotenv import load_dotenv

    # The same file Config reads, by the same path. See ENV_PATH in config.py.
    load_dotenv(Path(__file__).with_name(".env"))
    path = os.getenv("LIVE_DEMAND_SOCKET", "/run/peck-deck/live.sock")
    signal.signal(signal.SIGINT, lambda *_: sys.exit(0))
    signal.signal(signal.SIGTERM, lambda *_: sys.exit(0))
    try:
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as sock:
            sock.connect(path)
            # The service sends nothing. An empty read means it closed the
            # connection: the encoder failed, or the service stopped.
            while sock.recv(1024):
                pass
    except OSError as exc:
        print(f"live_demand: {path}: {exc}", file=sys.stderr)
        return 1
    print("live_demand: the Pi service closed the connection", file=sys.stderr)
    return 1


if __name__ == "__main__":
    sys.exit(main())
