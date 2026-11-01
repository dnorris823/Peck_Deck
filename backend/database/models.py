from datetime import datetime

from sqlalchemy import (
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    JSON,
    LargeBinary,
    String,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    pass


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String, nullable=False)
    email: Mapped[str] = mapped_column(String, unique=True, nullable=False)
    password_hash: Mapped[str] = mapped_column(String, nullable=False)
    notify_email: Mapped[bool] = mapped_column(Boolean, default=True)
    role: Mapped[str] = mapped_column(String, default="viewer")  # owner|viewer
    # Every user JWT carries the version it was issued at. Bumping this revokes
    # every token the user holds, so a 30-day token can still be cut off.
    token_version: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default="0"
    )

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
    feed_type: Mapped[str | None] = mapped_column(String, nullable=True)
    token: Mapped[str] = mapped_column(String, unique=True, nullable=False)

    # Runtime telemetry reported by the Pi via POST /devices/{id}/heartbeat.
    # All nullable — a freshly registered device has never checked in yet.
    battery: Mapped[float | None] = mapped_column(Float, nullable=True)  # 0.0–1.0
    # mains|battery, from the Pi's POWER_SOURCE. Null for a Pi on older code.
    power_source: Mapped[str | None] = mapped_column(String, nullable=True)
    signal: Mapped[str | None] = mapped_column(String, nullable=True)  # good|weak|none
    last_seen: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    # Where the Pi's MediaMTX answers WHEP offers, from the latest heartbeat.
    # Null when the last heartbeat sent none. Never sent to the browser.
    live_url: Mapped[str | None] = mapped_column(String, nullable=True)

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
    # "bird" or "animal". An animal row is a squirrel, raccoon or other feeder
    # mammal that Tier 2 named. Every bird count filters on kind = 'bird'.
    kind: Mapped[str] = mapped_column(
        String, nullable=False, default="bird", server_default="bird"
    )
    # The animal's group from machine_learning/feeder_animals.csv, such as
    # "squirrel". Null for a bird.
    animal_group: Mapped[str | None] = mapped_column(String, nullable=True)

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

    sightings: Mapped[list["Sighting"]] = relationship(
        "Sighting", back_populates="species", foreign_keys="Sighting.species_id"
    )


class Sighting(Base):
    __tablename__ = "sightings"
    __table_args__ = (
        # The re-check loop asks for pending rows every minute. Done and null
        # rows are nearly every row, so the index holds only the pending ones.
        Index(
            "ix_sightings_tier2_recheck_pending",
            "datetime",
            postgresql_where=text("tier2_recheck = 'pending'"),
            sqlite_where=text("tier2_recheck = 'pending'"),
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    species_id: Mapped[int] = mapped_column(Integer, ForeignKey("species.id"), nullable=False)
    device_id: Mapped[int] = mapped_column(Integer, ForeignKey("devices.id"), nullable=False)
    datetime: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    image_data: Mapped[bytes | None] = mapped_column(LargeBinary, nullable=True)
    # About 400 px on the long side, made at upload. Null when there is no image,
    # or when Pillow could not decode it. The image route then serves the full
    # image in its place. Deferred with raiseload, so no query reads it unless it
    # asks, and a stray touch raises instead of loading it one row at a time.
    thumbnail_data: Mapped[bytes | None] = mapped_column(
        LargeBinary, nullable=True, deferred=True, deferred_raiseload=True
    )
    video_data: Mapped[bytes | None] = mapped_column(LargeBinary, nullable=True)
    classification_tier_used: Mapped[str] = mapped_column(String, nullable=False)
    confidence_score: Mapped[float] = mapped_column(Float, nullable=False)
    weather_conditions: Mapped[str | None] = mapped_column(String, nullable=True)
    delayed: Mapped[bool] = mapped_column(Boolean, default=False)
    # One entry per tier the Pi's chain held, in chain order. See TierAttempt in
    # sightings/schemas.py. Null for rows and Pi builds from before the trace.
    tier_trace: Mapped[list | None] = mapped_column(
        JSON().with_variant(JSONB(), "postgresql"), nullable=True
    )
    # Set when a person corrects the species through PATCH /sightings/{id}.
    # `species_id` then holds their answer, and `original_species_id` keeps the
    # species the Pi's chain named, next to its tier and confidence. All three
    # are null on a sighting nobody has corrected.
    original_species_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("species.id"), nullable=True
    )
    corrected_by: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("users.id"), nullable=True
    )
    corrected_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    # The Tier 2 re-check. See backend/sightings/recheck.py. "pending" when the
    # Pi's trace shows Tier 2 gave no answer, "done" once the backend asked it.
    # Null on a sighting Tier 2 already answered, or that never had Tier 2.
    tier2_recheck: Mapped[str | None] = mapped_column(String, nullable=True)
    # The species the Pi named, set only when a re-check replaced it.
    provisional_species_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("species.id"), nullable=True
    )
    rechecked_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    # Pixel edges [left, top, right, bottom] of the square the Pi classified.
    # Null when the Pi classified the full frame, or sent no box.
    crop_box: Mapped[list | None] = mapped_column(
        JSON().with_variant(JSONB(), "postgresql"), nullable=True
    )

    species: Mapped["Species"] = relationship(
        "Species", back_populates="sightings", foreign_keys=[species_id]
    )
    device: Mapped["Device"] = relationship("Device", back_populates="sightings")
