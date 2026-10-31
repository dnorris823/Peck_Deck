"""Run the live encoder while someone watches.

Each open connection on the demand socket is one ``live_demand`` helper, which
MediaMTX keeps alive while the feed has viewers. The first connection starts the
encoder and the last one to close stops it, so a feeder nobody watches spends no
CPU on encoding.

Nothing here may stop capture, classification or upload. Every encoder start
and stop is caught, and a socket that cannot open only turns live video off.
"""
import asyncio
import logging
import os
import stat
from collections.abc import Callable
from pathlib import Path

logger = logging.getLogger(__name__)


class LiveDemandServer:
    """Listens on a Unix socket and runs ``start``/``stop`` on demand.

    ``start`` and ``stop`` are blocking calls. They run in a worker thread, one
    at a time, so a slow encoder start never blocks the event loop.
    """

    def __init__(self, socket_path: str, start: Callable[[], None], stop: Callable[[], None]):
        self._path = Path(socket_path)
        self._start = start
        self._stop = stop
        self._server: asyncio.AbstractServer | None = None
        self._writers: set[asyncio.StreamWriter] = set()
        self._connections = 0
        self._running = False
        self._start_failed = False
        self._lock = asyncio.Lock()

    @property
    def listening(self) -> bool:
        return self._server is not None

    @property
    def encoding(self) -> bool:
        return self._running

    async def __aenter__(self) -> "LiveDemandServer":
        try:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            self._remove_stale_socket()
            self._server = await asyncio.start_unix_server(self.handle, path=str(self._path))
            # MediaMTX runs as the same user. Nobody else may start the encoder.
            os.chmod(self._path, 0o600)
            logger.info("Live video on demand: listening on %s", self._path)
        except Exception as exc:
            self._server = None
            logger.warning("Live video off: cannot listen on %s (%s)", self._path, exc)
        return self

    async def __aexit__(self, *args) -> None:
        if self._server is not None:
            self._server.close()
            self._server = None
            self._remove_stale_socket()
        for writer in list(self._writers):
            writer.close()
        async with self._lock:
            await self._stop_encoder()

    async def handle(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        """Serve one demand connection until the helper goes away."""
        self._connections += 1
        self._writers.add(writer)
        try:
            if await self._ensure_started():
                # The helper sends nothing. EOF means MediaMTX killed it.
                while await reader.read(1024):
                    pass
        except Exception:
            logger.debug("Live demand connection ended with an error", exc_info=True)
        finally:
            self._connections -= 1
            self._writers.discard(writer)
            try:
                writer.close()
            except Exception:
                pass
            async with self._lock:
                if self._connections == 0:
                    await self._stop_encoder()

    async def _ensure_started(self) -> bool:
        async with self._lock:
            if self._running:
                return True
            try:
                await asyncio.to_thread(self._start)
            except Exception as exc:
                # Log the first failure with its traceback. A viewer retrying
                # every few seconds must not fill the journal.
                if not self._start_failed:
                    logger.warning("Live encoder failed to start: %s", exc, exc_info=True)
                else:
                    logger.debug("Live encoder failed to start again: %s", exc)
                self._start_failed = True
                return False
            self._running = True
            self._start_failed = False
            logger.info("Live encoder started")
            return True

    async def _stop_encoder(self) -> None:
        """Stop the encoder if it runs. The caller holds the lock."""
        if not self._running:
            return
        self._running = False
        try:
            await asyncio.to_thread(self._stop)
            logger.info("Live encoder stopped")
        except Exception:
            logger.warning("Live encoder failed to stop cleanly", exc_info=True)

    def _remove_stale_socket(self) -> None:
        # A socket left by a crashed run blocks the bind. Remove only a socket,
        # never a regular file someone pointed LIVE_DEMAND_SOCKET at.
        try:
            if stat.S_ISSOCK(self._path.lstat().st_mode):
                self._path.unlink()
        except FileNotFoundError:
            pass
