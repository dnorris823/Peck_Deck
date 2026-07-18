from datetime import datetime, timedelta, timezone

from litestar import Controller, Request, delete, get, post, put
from litestar.exceptions import HTTPException, NotFoundException
from litestar.di import NamedDependency
from litestar.params import FromPath
from sqlalchemy.ext.asyncio import AsyncSession

from ..auth.guards import device_guard, user_guard
from ..users.operations import get_or_create_preferences
from .operations import (
    add_device_user,
    create_device,
    get_device,
    get_devices_for_user,
    get_sighting_counts,
    remove_device_user,
    update_device,
    update_device_telemetry,
)
from .schemas import (
    AddDeviceUser,
    DeviceHeartbeat,
    DeviceResponse,
    RegisterDevice,
    UpdateDevice,
)


def _derive_status(device) -> str:
    """online|warn|offline from last_seen recency plus battery/signal health."""
    if device.last_seen is None:
        return "offline"
    last_seen = device.last_seen
    if last_seen.tzinfo is None:
        last_seen = last_seen.replace(tzinfo=timezone.utc)
    age = datetime.now(timezone.utc) - last_seen
    if age > timedelta(minutes=30):
        return "offline"
    unhealthy = (device.battery is not None and device.battery < 0.2) or (
        device.signal == "weak"
    )
    if age > timedelta(minutes=5) or unhealthy:
        return "warn"
    return "online"


async def _to_response(db: AsyncSession, device) -> DeviceResponse:
    counts = await get_sighting_counts(db, device.id)
    return DeviceResponse(
        id=device.id,
        name=device.name,
        city=device.city,
        state=device.state,
        owner_id=device.owner_id,
        classification_tier=device.classification_tier,
        feed_type=device.feed_type,
        token=device.token,
        battery=device.battery,
        signal=device.signal,
        last_seen=device.last_seen.isoformat() if device.last_seen else None,
        status=_derive_status(device),
        today_sightings=counts["today"],
        week_sightings=counts["week"],
        all_time_sightings=counts["all_time"],
    )


def _assert_owner(request: Request, device) -> None:
    if device.owner_id != request.state.user_id and request.state.role != "owner":
        raise HTTPException(status_code=403, detail="Forbidden")


class DeviceController(Controller):
    path = "/devices"

    # Guards are per-handler (not class-level) so the Pi-facing heartbeat can use
    # device_guard without also running user_guard — Litestar stacks the two.

    @get("/", guards=[user_guard])
    async def list_devices(self, request: Request, db: NamedDependency[AsyncSession]) -> list[DeviceResponse]:
        devices = await get_devices_for_user(db, request.state.user_id)
        return [await _to_response(db, d) for d in devices]

    @post("/", guards=[user_guard], status_code=201)
    async def register(
        self, data: RegisterDevice, request: Request, db: NamedDependency[AsyncSession]
    ) -> DeviceResponse:
        # When the request omits a tier, inherit the owner's default_tier pref.
        tier = data.classification_tier
        if tier is None:
            prefs = await get_or_create_preferences(db, request.state.user_id)
            tier = prefs.default_tier
        device = await create_device(
            db,
            name=data.name,
            city=data.city,
            state=data.state,
            owner_id=request.state.user_id,
            classification_tier=tier,
            feed_type=data.feed_type,
        )
        return await _to_response(db, device)

    @put("/{device_id:int}", guards=[user_guard])
    async def update(
        self, device_id: FromPath[int], data: UpdateDevice, request: Request, db: NamedDependency[AsyncSession]
    ) -> DeviceResponse:
        device = await get_device(db, device_id)
        if device is None:
            raise NotFoundException()
        _assert_owner(request, device)
        device = await update_device(
            db,
            device,
            name=data.name,
            city=data.city,
            state=data.state,
            classification_tier=data.classification_tier,
            feed_type=data.feed_type,
        )
        return await _to_response(db, device)

    @post("/{device_id:int}/heartbeat", guards=[device_guard], status_code=200)
    async def heartbeat(
        self, device_id: FromPath[int], data: DeviceHeartbeat, request: Request, db: NamedDependency[AsyncSession]
    ) -> DeviceResponse:
        # The Pi authenticates with its device token; it may only report for itself.
        if request.state.device_id != device_id:
            raise HTTPException(status_code=403, detail="Forbidden")
        device = await get_device(db, device_id)
        if device is None:
            raise NotFoundException()
        device = await update_device_telemetry(
            db, device, battery=data.battery, signal=data.signal
        )
        return await _to_response(db, device)

    @post("/{device_id:int}/users", guards=[user_guard], status_code=204)
    async def add_user(
        self, device_id: FromPath[int], data: AddDeviceUser, request: Request, db: NamedDependency[AsyncSession]
    ) -> None:
        device = await get_device(db, device_id)
        if device is None:
            raise NotFoundException()
        _assert_owner(request, device)
        await add_device_user(db, device_id, data.user_id)

    @delete("/{device_id:int}/users/{uid:int}", guards=[user_guard], status_code=204)
    async def remove_user(
        self, device_id: FromPath[int], uid: FromPath[int], request: Request, db: NamedDependency[AsyncSession]
    ) -> None:
        device = await get_device(db, device_id)
        if device is None:
            raise NotFoundException()
        _assert_owner(request, device)
        removed = await remove_device_user(db, device_id, uid)
        if not removed:
            raise NotFoundException()
