"""Throttle-window edge cases in NotificationService.

Split out from test_notifications.py because these drive `_can_notify` directly
with a controlled clock, rather than going through the DB.
"""
import time

from backend.notifications.service import NotificationService


def test_first_notification_allowed_on_a_freshly_booted_host(monkeypatch):
    """Regression: uptime shorter than the throttle interval must not mute sends.

    `time.monotonic()` counts from boot on Linux. `_can_notify` used to default a
    never-seen recipient's last-notified time to 0.0 and test
    `monotonic() - 0.0 >= interval`, which is False for the whole first
    `interval` seconds of uptime — silently dropping the first sighting after
    every reboot, and failing the notification suite on fresh CI runners.
    """
    svc = NotificationService(min_interval_seconds=60)

    # Host booted 3 seconds ago.
    monkeypatch.setattr(time, "monotonic", lambda: 3.0)

    assert svc._can_notify(user_id=1, device_id=1, interval=60) is True


def test_throttle_still_suppresses_a_rapid_repeat(monkeypatch):
    svc = NotificationService(min_interval_seconds=60)
    clock = {"now": 3.0}
    monkeypatch.setattr(time, "monotonic", lambda: clock["now"])

    assert svc._can_notify(1, 1, 60) is True
    svc._mark_notified(1, 1)

    clock["now"] = 10.0  # 7s later — inside the quiet window
    assert svc._can_notify(1, 1, 60) is False


def test_throttle_expires_after_the_interval(monkeypatch):
    svc = NotificationService(min_interval_seconds=60)
    clock = {"now": 3.0}
    monkeypatch.setattr(time, "monotonic", lambda: clock["now"])

    svc._mark_notified(1, 1)
    clock["now"] = 63.0  # exactly 60s later
    assert svc._can_notify(1, 1, 60) is True


def test_a_marked_recipient_does_not_mute_a_different_one(monkeypatch):
    svc = NotificationService(min_interval_seconds=60)
    monkeypatch.setattr(time, "monotonic", lambda: 5.0)

    svc._mark_notified(1, 1)

    assert svc._can_notify(1, 1, 60) is False   # same recipient+device
    assert svc._can_notify(2, 1, 60) is True    # different recipient
    assert svc._can_notify(1, 2, 60) is True    # same recipient, other device
