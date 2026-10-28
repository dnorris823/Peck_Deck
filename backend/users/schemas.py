from dataclasses import dataclass, field


@dataclass
class RegisterUser:
    name: str
    email: str
    password: str
    role: str = "viewer"


@dataclass
class UpdateUser:
    name: str | None = None
    notify_email: bool | None = None
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
    notify_email: bool
    role: str


@dataclass
class PreferencesResponse:
    quiet_interval_seconds: int
    notify_new_species_only: bool


@dataclass
class UpdatePreferences:
    quiet_interval_seconds: int | None = None
    notify_new_species_only: bool | None = None


@dataclass
class LoginRequest:
    email: str
    password: str


@dataclass
class TokenResponse:
    access_token: str
    token_type: str = "bearer"
