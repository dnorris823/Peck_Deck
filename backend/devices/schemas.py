from dataclasses import dataclass


@dataclass
class RegisterDevice:
    name: str
    city: str | None = None
    state: str | None = None
    feed_type: str | None = None


@dataclass
class UpdateDevice:
    name: str | None = None
    city: str | None = None
    state: str | None = None
    feed_type: str | None = None


@dataclass
class DeviceHeartbeat:
    battery: float | None = None
    signal: str | None = None


@dataclass
class AddDeviceUser:
    user_id: int


@dataclass
class TierMix:
    """Which tier named the device's recent captures, and the Tier 2 warning.

    The four counts come from ``classification_tier_used``. ``tier2_asked`` and
    ``tier2_missed`` come from the trace: captures that asked Tier 2, and those
    that got no answer. See ``tier2_missed`` in devices/operations.py.
    """

    window_hours: int
    gpu: int
    local: int
    cloud: int
    none: int
    tier2_asked: int
    tier2_missed: int
    tier2_warning: bool


@dataclass
class DeviceResponse:
    id: int
    name: str
    city: str | None
    state: str | None
    owner_id: int
    feed_type: str | None
    battery: float | None
    signal: str | None
    last_seen: str | None
    status: str  # online|warn|offline — derived from last_seen/battery/signal
    today_sightings: int
    week_sightings: int
    all_time_sightings: int
    tier_mix: TierMix


@dataclass
class RegisteredDeviceResponse(DeviceResponse):
    """Only `POST /devices` returns this. The token never rides on a shared response."""

    token: str


@dataclass
class DeviceTokenResponse:
    id: int
    token: str
