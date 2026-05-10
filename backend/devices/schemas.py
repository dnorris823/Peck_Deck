from dataclasses import dataclass


@dataclass
class RegisterDevice:
    name: str
    city: str | None = None
    state: str | None = None
    classification_tier: str = "auto"
    feed_type: str | None = None


@dataclass
class UpdateDevice:
    name: str | None = None
    city: str | None = None
    state: str | None = None
    classification_tier: str | None = None
    feed_type: str | None = None


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
