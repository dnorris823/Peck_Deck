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
class LoginRequest:
    email: str
    password: str


@dataclass
class TokenResponse:
    access_token: str
    token_type: str = "bearer"
