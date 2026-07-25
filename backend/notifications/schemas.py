from dataclasses import dataclass


@dataclass
class PushKeys:
    """The ``keys`` object of a browser PushSubscription, base64url-encoded."""

    p256dh: str
    auth: str


@dataclass
class SubscribeRequest:
    """A browser's ``PushSubscription.toJSON()``, plus an optional label.

    Shaped to match the Push API output so the frontend can post the
    subscription almost verbatim rather than reassembling it.
    """

    endpoint: str
    keys: PushKeys
    user_agent: str | None = None


@dataclass
class SubscriptionResponse:
    id: int
    created_at: str
    user_agent: str | None
    # Origin + a short tail of the endpoint path. Enough to tell two browsers
    # apart in the UI without echoing the whole endpoint, which is a capability
    # URL for pushing to that browser.
    endpoint_hint: str


@dataclass
class PushConfigResponse:
    """What the frontend needs before it can call ``pushManager.subscribe``."""

    enabled: bool
    # base64url VAPID public key, or None when the server has no keys — the
    # frontend uses this to hide the opt-in instead of failing at subscribe time.
    public_key: str | None
