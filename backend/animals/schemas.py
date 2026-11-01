from dataclasses import dataclass, field


@dataclass
class CreateMeasure:
    name: str
    # ISO-8601. Defaults to now. A naive time is read as UTC.
    started_at: str | None = None
    note: str | None = None


@dataclass
class UpdateMeasure:
    """Fields to change. A field left out stays as it is.

    ``ended_at`` ends the measure. An empty string clears it, so the measure is
    in place again.
    """

    name: str | None = None
    started_at: str | None = None
    ended_at: str | None = None
    note: str | None = None


@dataclass
class MeasureResponse:
    id: int
    device_id: int
    name: str
    started_at: str
    ended_at: str | None
    note: str | None


@dataclass
class RateRatioResponse:
    # Visits in the window before the measure, and in the window after.
    before: int
    after: int
    # Visits per camera-up hour. Null when the window has no camera-up hours.
    before_rate: float | None
    after_rate: float | None
    # After rate over before rate. Null when the before rate is zero or unknown.
    ratio: float | None
    # The 95% interval for the ratio. Null when either count is zero.
    low: float | None
    high: float | None


@dataclass
class MeasureEffectResponse:
    before_start: str
    after_start: str
    after_end: str
    # Camera-up hours. Offline hours and the hours before the first sighting
    # are left out.
    before_hours: float
    after_hours: float
    # True once the after window ran its 14 days, or to the measure's end.
    complete: bool
    # One entry per animal group seen in either window.
    groups: dict[str, RateRatioResponse]
    # Birds over the same two windows. A drop here as large as the animals'
    # points to weather or empty feed, not the measure.
    birds: RateRatioResponse


@dataclass
class MeasureWithEffect(MeasureResponse):
    effect: MeasureEffectResponse | None = None


@dataclass
class AnimalDay:
    date: str  # local date, YYYY-MM-DD
    animals: dict[str, int]  # visits per animal group
    birds: int


@dataclass
class AnimalStatsResponse:
    device_id: int
    tz: str
    from_date: str
    to_date: str
    days: list[AnimalDay]
    # Animal groups with a visit in range, most visits first.
    groups: list[str] = field(default_factory=list)
    measures: list[MeasureWithEffect] = field(default_factory=list)
