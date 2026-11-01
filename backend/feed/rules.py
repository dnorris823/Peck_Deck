"""The two feed rules, as plain functions over timestamps and counts.

The visit drop compares the last 3 hours with the same 3 hours on each of the
past 14 days. The mean of those past counts is ``E``, the expected count, and
the count in the last 3 hours is ``O``. Summing per-hour means over 3 clock
hours gives the same ``E``. Sliding the whole window keeps it aligned when the
check does not run on the hour. A past window that overlaps an outage or an
empty spell is left out, so an empty week does not lower the bar.

Hours are UTC. Comparing the same UTC window across days is the same as
comparing the same local hour, except across a daylight saving change.

The forecast takes the median visits per fill over the recent fills of the
current feed type, and warns at 85% of it.
"""
import bisect
import math
import statistics
from dataclasses import dataclass
from datetime import datetime, timedelta

WINDOW = timedelta(hours=3)
BASELINE_DAYS = 14
# Fewer qualifying past windows than this, and the check does not run. A new
# feeder needs a week of visits before its baseline means anything.
BASELINE_MIN_DAYS = 7
# Below this many expected visits the check stays silent. With E = 6 the rule
# fires on 0 or 1 visits, which normal feed shows about 1.7% of the time.
MIN_EXPECTED = 6
# Visits count as back to normal at half of E or more.
RECOVERY_SHARE = 0.5

FORECAST_MIN_FILLS = 3
FORECAST_MAX_FILLS = 8
FORECAST_SHARE = 0.85

Span = tuple[datetime, datetime]


@dataclass(frozen=True)
class VisitCheck:
    expected: float  # E, the mean count in the same window on past days
    observed: int  # O, the count in the last 3 hours
    days: int  # past windows that went into E

    @property
    def dropped(self) -> bool:
        """The feed is probably gone: E >= 6 and O <= floor(E / 4)."""
        return self.expected >= MIN_EXPECTED and self.observed <= math.floor(self.expected / 4)

    @property
    def normal(self) -> bool:
        return self.expected >= MIN_EXPECTED and self.observed >= self.expected * RECOVERY_SHARE


def _count(visits: list[datetime], start: datetime, end: datetime) -> int:
    """Visits in ``[start, end)``. ``visits`` is sorted."""
    return bisect.bisect_left(visits, end) - bisect.bisect_left(visits, start)


def _overlaps(start: datetime, end: datetime, spans: list[Span]) -> bool:
    return any(s < end and e > start for s, e in spans)


def visit_check(
    visits: list[datetime],
    now: datetime,
    *,
    history_start: datetime | None,
    excluded: list[Span],
) -> VisitCheck | None:
    """E and O for the window ending at ``now``. None with too little history.

    ``visits`` is the sorted sighting times. ``history_start`` is the device's
    first sighting, so days before the feeder had any visits stay out of E.
    """
    if history_start is None:
        return None
    observed = _count(visits, now - WINDOW, now)
    past = []
    for days_back in range(1, BASELINE_DAYS + 1):
        end = now - timedelta(days=days_back)
        start = end - WINDOW
        if start < history_start or _overlaps(start, end, excluded):
            continue
        past.append(_count(visits, start, end))
    if len(past) < BASELINE_MIN_DAYS:
        return None
    return VisitCheck(expected=sum(past) / len(past), observed=observed, days=len(past))


def visits_per_fill(fill_counts: list[int]) -> float | None:
    """The median visits per fill, or None before ``FORECAST_MIN_FILLS`` fills.

    A refill logged late inflates one count. The median keeps one late refill
    from moving the forecast much.
    """
    if len(fill_counts) < FORECAST_MIN_FILLS:
        return None
    return float(statistics.median(fill_counts))


def forecast_low(per_fill: float | None, since_refill: int) -> bool:
    return per_fill is not None and per_fill > 0 and since_refill >= FORECAST_SHARE * per_fill


def ago(delta: timedelta) -> str:
    """"40 min", "3 h", "2 days". Rounds down, never below 1."""
    minutes = int(delta.total_seconds() // 60)
    if minutes < 60:
        return f"{max(minutes, 1)} min"
    hours = minutes // 60
    if hours < 48:
        return f"{hours} h"
    return f"{hours // 24} days"


def out_line(last_visit: datetime | None, now: datetime) -> str:
    if last_visit is None:
        return f"Feed may be out. No visits in the last {ago(WINDOW)}."
    return f"Feed may be out. Visits stopped about {ago(now - last_visit)} ago."


def low_line(since_refill: int, per_fill: float) -> str:
    return (
        f"Feed may be low. {since_refill} visits since the last refill, "
        f"and a fill usually lasts about {round(per_fill)}."
    )
