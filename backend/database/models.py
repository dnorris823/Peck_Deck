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
