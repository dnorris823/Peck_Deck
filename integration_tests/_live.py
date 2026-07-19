"""Run an ASGI app under a real uvicorn server in a background thread.

Used by the contract tests so the actual client code (the Raspberry Pi
``aiohttp`` clients) talks to a real socket instead of an in-process transport.
Kept separate from ``conftest`` so it imports without a database configured.
"""
import contextlib
import socket
import threading
import time

import uvicorn


def free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


class _ThreadedServer(uvicorn.Server):
    # Don't let uvicorn hijack SIGINT/SIGTERM from a background thread.
    def install_signal_handlers(self) -> None:
        pass


@contextlib.contextmanager
def run_server(target_app, *, host: str = "127.0.0.1", port: int | None = None):
    """Serve ``target_app`` with uvicorn; yield its base URL, then shut down.

    Blocks until the server reports started so callers can connect immediately.
    """
    port = port or free_port()
    config = uvicorn.Config(
        target_app, host=host, port=port, log_level="warning", lifespan="on"
    )
    server = _ThreadedServer(config)
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    try:
        deadline = time.monotonic() + 15
        while not server.started:
            if time.monotonic() > deadline:
                raise RuntimeError("uvicorn server failed to start in time")
            time.sleep(0.05)
        yield f"http://{host}:{port}"
    finally:
        server.should_exit = True
        thread.join(timeout=10)
