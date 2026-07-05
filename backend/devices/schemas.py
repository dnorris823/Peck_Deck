from dataclasses import dataclass


@dataclass
class RegisterDevice:
    name: str
    city: str | None = None
    state: str | None = None
    # Omit to inherit the owner's default_tier preference (see controller).
    classification_tier: str | None = None
    feed_type: str | None = None


@dataclass
class UpdateDevice:
    name: str | None = None
    city: str | None = None
    state: str | None = None
    classification_tier: str | None = None
    feed_type: str | None = None


@dataclass
class DeviceHeartbeat:
    battery: float | None = None
    signal: str | None = None


@dataclass
class AddDeviceUser:
    user_id: int


@dataclass
class DeviceResponse:
    id: int
    name: str
    city: str | None
    state: str | None
    owner_id: int
    classification_tier: str
    feed_type: str | None
    token: str
    battery: float | None
    signal: str | None
    last_seen: str | None
    status: str  # online|warn|offline — derived from last_seen/battery/signal
    today_sightings: int
    week_sightings: int
    all_time_sightings: int
