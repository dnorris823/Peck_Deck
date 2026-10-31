from dataclasses import dataclass


@dataclass
class RegisterDevice:
    name: str
    city: str | None = None
    state: str | None = None
    feed_type: str | None = None


@dataclass
class UpdateDevice:
    """Fields to change. A missing field stays. An empty city, state or feed
    type clears it."""

    name: str | None = None
    city: str | None = None
    state: str | None = None
    feed_type: str | None = None


@dataclass
class DeviceHeartbeat:
    battery: float | None = None
    signal: str | None = None
    # Where the Pi's MediaMTX answers WHEP offers. A private IP literal only,
    # see backend/live/address.py. Omitting it clears the stored address.
    live_url: str | None = None


@dataclass
class AddDeviceUser:
    """The user to add, by id or by email. Send exactly one.

    Email is for a feeder owner with the viewer role, who cannot list users.
    """

    user_id: int | None = None
    email: str | None = None


@dataclass
class DeviceMember:
    id: int
    name: str
    email: str
    notify_email: bool


@dataclass
class DeviceAccessResponse:
    """Who sees the feeder and gets its alerts: the owner and the members."""

    owner: DeviceMember
    members: list[DeviceMember]


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
    # A live_url is stored and the device is not offline. The URL stays private.
    live_available: bool


@dataclass
class RegisteredDeviceResponse(DeviceResponse):
    """Only `POST /devices` returns this. The token never rides on a shared response."""

    token: str


@dataclass
class DeviceTokenResponse:
    id: int
    token: str
