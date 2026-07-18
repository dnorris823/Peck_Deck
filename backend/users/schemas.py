from dataclasses import dataclass, field


@dataclass
class RegisterUser:
    name: str
    email: str
    password: str
    phone: str | None = None
    role: str = "viewer"


@dataclass
class UpdateUser:
    name: str | None = None
    phone: str | None = None
    notify_email: bool | None = None
    notify_sms: bool | None = None
    email: str | None = None


@dataclass
class UpdatePassword:
    new_password: str
    # Required when changing your own password; ignored on an owner-initiated
    # reset of another user (see controller).
    current_password: str | None = None


@dataclass
class UserResponse:
    id: int
    name: str
    email: str
    phone: str | None
    notify_email: bool
    notify_sms: bool
    role: str


@dataclass
class PreferencesResponse:
    quiet_interval_seconds: int
    notify_new_species_only: bool
    default_tier: str
    escalation_threshold: int
    debounce_seconds: int


@dataclass
class UpdatePreferences:
    quiet_interval_seconds: int | None = None
    notify_new_species_only: bool | None = None
    default_tier: str | None = None
    escalation_threshold: int | None = None
    debounce_seconds: int | None = None


@dataclass
class LoginRequest:
    email: str
    password: str


@dataclass
class TokenResponse:
    access_token: str
    token_type: str = "bearer"
