from datetime import datetime

from sqlalchemy import (
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    LargeBinary,
    String,
    UniqueConstraint,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    pass


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String, nullable=False)
    email: Mapped[str] = mapped_column(String, unique=True, nullable=False)
    password_hash: Mapped[str] = mapped_column(String, nullable=False)
    phone: Mapped[str | None] = mapped_column(String, nullable=True)
    notify_email: Mapped[bool] = mapped_column(Boolean, default=True)
    notify_sms: Mapped[bool] = mapped_column(Boolean, default=False)
    role: Mapped[str] = mapped_column(String, default="viewer")  # owner|viewer

    owned_devices: Mapped[list["Device"]] = relationship(
        "Device", foreign_keys="Device.owner_id", back_populates="owner"
    )
    device_memberships: Mapped[list["DeviceUser"]] = relationship(
        "DeviceUser", back_populates="user"
    )


class UserPreferences(Base):
    """Per-user notification + classification preferences.

    One row per user (user_id is the PK). Rows are created lazily the first
    time a user reads or writes their preferences — see
    users.operations.get_or_create_preferences.
    """

    __tablename__ = "user_preferences"

    user_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("users.id"), primary_key=True
    )
    # Minimum seconds between notifications per device (anti-spam).
    quiet_interval_seconds: Mapped[int] = mapped_column(Integer, default=60)
    # Only alert the first time a species is seen.
    notify_new_species_only: Mapped[bool] = mapped_column(Boolean, default=False)
    # Default tier for new stations: local|gpu|cloud|auto.
    default_tier: Mapped[str] = mapped_column(String, default="auto")
    # In Auto mode, escalate below this confidence (percent, 40–95).
    escalation_threshold: Mapped[int] = mapped_column(Integer, default=70)
    # Skip duplicate captures within this window of a confirmed sighting.
    debounce_seconds: Mapped[int] = mapped_column(Integer, default=30)

    user: Mapped["User"] = relationship("User")


class PushSubscription(Base):
    """A browser's web-push endpoint — FLEDGE Phase 7.

    One row per (user, browser). The row's *existence* is the opt-in: web push
    can't be sent without the endpoint and keys the browser hands out at
    subscribe time, so there is no separate "push enabled" flag to keep in sync
    with it. Deleting the row is how a user turns push off.

    ``endpoint`` is unique because the push service's URL identifies the browser
    installation — re-subscribing (after a key rotation or a permission reset)
    must update the existing row rather than accumulate duplicates that would
    each deliver the same alert.
    """

    __tablename__ = "push_subscriptions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("users.id"), nullable=False, index=True
    )
    # The push service URL to POST the encrypted payload to.
    endpoint: Mapped[str] = mapped_column(String, unique=True, nullable=False)
    # Client keys from the PushSubscription, base64url (RFC 8291):
    # p256dh is the browser's ECDH public key, auth is a 16-byte shared secret.
    p256dh: Mapped[str] = mapped_column(String, nullable=False)
    auth: Mapped[str] = mapped_column(String, nullable=False)
    # Free-text label so a user can tell their phone from their laptop.
    user_agent: Mapped[str | None] = mapped_column(String, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )

    user: Mapped["User"] = relationship("User")


class Device(Base):
    __tablename__ = "devices"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String, nullable=False)
    city: Mapped[str | None] = mapped_column(String, nullable=True)
    state: Mapped[str | None] = mapped_column(String, nullable=True)
    owner_id: Mapped[int] = mapped_column(Integer, ForeignKey("users.id"), nullable=False)
    classification_tier: Mapped[str] = mapped_column(String, default="auto")
    feed_type: Mapped[str | None] = mapped_column(String, nullable=True)
    token: Mapped[str] = mapped_column(String, unique=True, nullable=False)

    # Runtime telemetry reported by the Pi via POST /devices/{id}/heartbeat.
    # All nullable — a freshly registered device has never checked in yet.
    battery: Mapped[float | None] = mapped_column(Float, nullable=True)  # 0.0–1.0
    signal: Mapped[str | None] = mapped_column(String, nullable=True)  # good|weak|none
    last_seen: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    owner: Mapped["User"] = relationship(
        "User", foreign_keys=[owner_id], back_populates="owned_devices"
    )
    members: Mapped[list["DeviceUser"]] = relationship("DeviceUser", back_populates="device")
    sightings: Mapped[list["Sighting"]] = relationship("Sighting", back_populates="device")


class DeviceUser(Base):
    __tablename__ = "device_users"

    device_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("devices.id"), primary_key=True
    )
    user_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("users.id"), primary_key=True
    )

    device: Mapped["Device"] = relationship("Device", back_populates="members")
    user: Mapped["User"] = relationship("User", back_populates="device_memberships")


class Species(Base):
    __tablename__ = "species"
    __table_args__ = (UniqueConstraint("common_name", "genus", "species_name"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    common_name: Mapped[str] = mapped_column(String, nullable=False)
    genus: Mapped[str] = mapped_column(String, nullable=False)
    species_name: Mapped[str] = mapped_column(String, nullable=False)
    order_name: Mapped[str | None] = mapped_column(String, nullable=True)
    wiki_url: Mapped[str | None] = mapped_column(String, nullable=True)

    # Field-guide enrichment (FLEDGE Phase 6), cached on first sighting of a
    # species so the Species Library reads like a field guide rather than a
    # bare name. `description` is the Wikipedia summary extract; `family` comes
    # from GBIF's taxonomy match.
    description: Mapped[str | None] = mapped_column(String, nullable=True)
    family: Mapped[str | None] = mapped_column(String, nullable=True)

    # Field-guide presentation metadata used to render the stylized SVG plates
    # in the web app. `palette` is a JSON-encoded list of hex colors.
    palette: Mapped[str | None] = mapped_column(String, nullable=True)
    silhouette: Mapped[str | None] = mapped_column(String, nullable=True)
    note: Mapped[str | None] = mapped_column(String, nullable=True)

    sightings: Mapped[list["Sighting"]] = relationship("Sighting", back_populates="species")


class Sighting(Base):
    __tablename__ = "sightings"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    species_id: Mapped[int] = mapped_column(Integer, ForeignKey("species.id"), nullable=False)
    device_id: Mapped[int] = mapped_column(Integer, ForeignKey("devices.id"), nullable=False)
    datetime: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    image_data: Mapped[bytes | None] = mapped_column(LargeBinary, nullable=True)
    video_data: Mapped[bytes | None] = mapped_column(LargeBinary, nullable=True)
    classification_tier_used: Mapped[str] = mapped_column(String, nullable=False)
    confidence_score: Mapped[float] = mapped_column(Float, nullable=False)
    weather_conditions: Mapped[str | None] = mapped_column(String, nullable=True)
    delayed: Mapped[bool] = mapped_column(Boolean, default=False)

    species: Mapped["Species"] = relationship("Species", back_populates="sightings")
    device: Mapped["Device"] = relationship("Device", back_populates="sightings")
