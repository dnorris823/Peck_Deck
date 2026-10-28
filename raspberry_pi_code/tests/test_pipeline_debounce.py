"""``Pipeline.handle_trigger`` debounce at boot.

``loop.time()`` is monotonic time since boot on Linux, so it reads close to zero
when the service starts. The first trigger must capture whatever the clock says.
"""
import asyncio

from raspberry_pi_code.config import Config
from raspberry_pi_code.pipeline import Pipeline


def _triggers_at(tmp_path, times: list[float]) -> int:
    """Fire one trigger at each loop time in ``times``. Return the capture count."""
    pipeline = Pipeline(
        Config(cache_dir=str(tmp_path / "cache"), device_token="t", debounce_seconds=30)
    )
    captures: list = []

    async def fake_capture():
        captures.append(1)

    pipeline._capture_and_process = fake_capture

    async def run():
        loop = asyncio.get_running_loop()
        real_time = loop.time
        try:
            for t in times:
                loop.time = lambda t=t: t
                await pipeline.handle_trigger()
        finally:
            loop.time = real_time

    asyncio.run(run())
    return len(captures)


def test_first_trigger_after_boot_is_not_debounced(tmp_path):
    # Five seconds after boot, inside the 30 second window.
    assert _triggers_at(tmp_path, [5.0]) == 1


def test_second_trigger_inside_the_window_is_dropped(tmp_path):
    # 5.0 captures. 10.0 is 5 s later and is dropped. 40.0 is 35 s later and captures.
    assert _triggers_at(tmp_path, [5.0, 10.0, 40.0]) == 2
