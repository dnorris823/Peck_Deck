import logging
from datetime import datetime, timedelta, timezone

from litestar import Controller, Request, delete, get, post, put
from litestar.background_tasks import BackgroundTask
from litestar.exceptions import HTTPException, NotFoundException
from litestar.di import NamedDependency
from litestar.params import FromPath, FromQuery
from litestar.response import Response
from sqlalchemy.ext.asyncio import AsyncSession

from ..auth.guards import DEVICE_TOKEN, USER_JWT, device_guard, user_guard
from ..events.hub import SightingsDeleted, sighting_hub
from ..feed.operations import get_feed_status, log_refill
from ..live.address import check_live_url
from ..sightings.operations import count_sightings_before, delete_sightings_before
from ..users.operations import get_user_by_email, get_user_by_id
from .operations import (
    OFFLINE_AFTER,
    add_device_user,
    create_device,
    delete_device,
    get_device,
    get_device_members,
    get_devices_for_user,
    get_sighting_counts,
    get_tier_mix,
    remove_device_user,
    rotate_device_token,
    transfer_device,
    update_device,
    update_device_telemetry,
)
from .schemas import (
    AddDeviceUser,
    DeviceAccessResponse,
    DeviceHeartbeat,
    DeviceMember,
    DeviceResponse,
    DeviceTokenResponse,
    FeedStatus,
    RegisterDevice,
    RegisteredDeviceResponse,
    SightingCount,
    TierMix,
    UpdateDevice,
)

logger = logging.getLogger("peckdeck.devices")


def _derive_status(device) -> str:
    """online|warn|offline from last_seen recency plus battery/signal health."""
    if device.last_seen is None:
        return "offline"
    last_seen = device.last_seen
    if last_seen.tzinfo is None:
        last_seen = last_seen.replace(tzinfo=timezone.utc)
    age = datetime.now(timezone.utc) - last_seen
    if age > OFFLINE_AFTER:
        return "offline"
    low_battery = (
        device.power_source != "mains"
        and device.battery is not None
        and device.battery < 0.2
    )
    unhealthy = low_battery or device.signal == "weak"
    if age > timedelta(minutes=5) or unhealthy:
        return "warn"
    return "online"


def live_available(device) -> bool:
    """Whether the relay should try this device's MediaMTX."""
    return device.live_url is not None and _derive_status(device) != "offline"


async def _to_response(db: AsyncSession, device) -> DeviceResponse:
    counts = await get_sighting_counts(db, device.id)
    return DeviceResponse(
        id=device.id,
        name=device.name,
        city=device.city,
        state=device.state,
        owner_id=device.owner_id,
        feed_type=device.feed_type,
        battery=device.battery,
        power_source=device.power_source,
        signal=device.signal,
        last_seen=device.last_seen.isoformat() if device.last_seen else None,
        status=_derive_status(device),
        today_sightings=counts["today"],
        week_sightings=counts["week"],
        all_time_sightings=counts["all_time"],
        tier_mix=TierMix(**await get_tier_mix(db, device.id)),
        live_available=live_available(device),
        feed=FeedStatus(**await get_feed_status(db, device.id)),
    )


POWER_SOURCES = ("mains", "battery")


async def _record_heartbeat(db: AsyncSession, device, data: DeviceHeartbeat):
    if data.live_url is not None:
        problem = check_live_url(data.live_url)
        if problem:
            raise HTTPException(status_code=400, detail=problem)
    if data.power_source is not None and data.power_source not in POWER_SOURCES:
        raise HTTPException(
            status_code=400,
            detail=f"power_source must be one of: {', '.join(POWER_SOURCES)}",
        )
    if data.trigger_age_seconds is not None and data.trigger_age_seconds < 0:
        raise HTTPException(status_code=400, detail="trigger_age_seconds must be 0 or more")
    return await update_device_telemetry(
        db, device, battery=data.battery, signal=data.signal, live_url=data.live_url,
        power_source=data.power_source, trigger_age_seconds=data.trigger_age_seconds,
    )


def _member(user) -> DeviceMember:
    return DeviceMember(
        id=user.id, name=user.name, email=user.email, notify_email=user.notify_email
    )


def _assert_owner(request: Request, device) -> None:
    if device.owner_id != request.state.user_id and request.state.role != "owner":
        raise HTTPException(status_code=403, detail="Forbidden")


def _parse_before(before: str) -> datetime:
    """An ISO-8601 instant. A value with no offset counts as UTC."""
    try:
        parsed = datetime.fromisoformat(before)
    except ValueError:
        raise HTTPException(
            status_code=400,
            detail="before must be ISO-8601 (e.g. 2026-10-28 or 2026-10-28T07:00:00Z)",
        )
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


async def _announce(event: SightingsDeleted) -> None:
    sighting_hub.publish(event)


class DeviceController(Controller):
    path = "/devices"

    # Guards are per-handler (not class-level) so the Pi-facing heartbeat can use
    # device_guard without also running user_guard — Litestar stacks the two.

    @get("/", guards=[user_guard], security=USER_JWT)
    async def list_devices(self, request: Request, db: NamedDependency[AsyncSession]) -> list[DeviceResponse]:
        devices = await get_devices_for_user(db, request.state.user_id)
        return [await _to_response(db, d) for d in devices]

    @post("/", guards=[user_guard], security=USER_JWT, status_code=201)
    async def register(
        self, data: RegisterDevice, request: Request, db: NamedDependency[AsyncSession]
    ) -> RegisteredDeviceResponse:
        device = await create_device(
            db,
            name=data.name,
            city=data.city,
            state=data.state,
            owner_id=request.state.user_id,
            feed_type=data.feed_type,
        )
        response = await _to_response(db, device)
        return RegisteredDeviceResponse(**vars(response), token=device.token)

    @get("/{device_id:int}/token", guards=[user_guard], security=USER_JWT)
    async def get_token(
        self, device_id: FromPath[int], request: Request, db: NamedDependency[AsyncSession]
    ) -> DeviceTokenResponse:
        # Owner only. A viewer on the device sees its sightings but must not be
        # able to act as the feeder. scripts/provision_device.py reads this.
        device = await get_device(db, device_id)
        if device is None:
            raise NotFoundException()
        _assert_owner(request, device)
        return DeviceTokenResponse(id=device.id, token=device.token)

    @post("/{device_id:int}/token", guards=[user_guard], security=USER_JWT, status_code=200)
    async def rotate_token(
        self, device_id: FromPath[int], request: Request, db: NamedDependency[AsyncSession]
    ) -> DeviceTokenResponse:
        # Owner only, like the read above. The old token fails from the commit
        # on. The Pi picks up the new one through scripts/provision_device.py,
        # which reads it from the GET route on its next start.
        device = await get_device(db, device_id)
        if device is None:
            raise NotFoundException()
        _assert_owner(request, device)
        device = await rotate_device_token(db, device)
        return DeviceTokenResponse(id=device.id, token=device.token)

    @delete("/{device_id:int}", guards=[user_guard], security=USER_JWT, status_code=204)
    async def remove(
        self,
        device_id: FromPath[int],
        request: Request,
        db: NamedDependency[AsyncSession],
        delete_sightings: FromQuery[bool] = False,
    ) -> None:
        """Delete a feeder. **Feeder owner or owner role only.**

        Refused with 409 while sightings exist, unless `delete_sightings=true`.
        The sightings hold the only copy of each image, so the caller must ask
        for them to go. A plain delete must never destroy the feeder's history.
        """
        device = await get_device(db, device_id)
        if device is None:
            raise NotFoundException()
        _assert_owner(request, device)
        sightings = await delete_device(db, device_id, with_sightings=delete_sightings)
        if sightings and not delete_sightings:
            raise HTTPException(
                status_code=409,
                detail=f"Device has {sightings} sightings. Delete them before the device, "
                "or send delete_sightings=true.",
            )
        logger.info(
            "device %d deleted with %d sightings by user %d",
            device_id, sightings, request.state.user_id,
        )

    @get("/{device_id:int}/sightings/count", guards=[user_guard], security=USER_JWT)
    async def count_old_sightings(
        self,
        device_id: FromPath[int],
        before: FromQuery[str],
        request: Request,
        db: NamedDependency[AsyncSession],
    ) -> SightingCount:
        """How many sightings `DELETE /devices/{id}/sightings` would remove.

        Feeder owner or owner role only, like the delete it previews.
        """
        device = await get_device(db, device_id)
        if device is None:
            raise NotFoundException()
        _assert_owner(request, device)
        return SightingCount(count=await count_sightings_before(db, device_id, _parse_before(before)))

    @delete("/{device_id:int}/sightings", guards=[user_guard], security=USER_JWT, status_code=204)
    async def delete_old_sightings(
        self,
        device_id: FromPath[int],
        before: FromQuery[str],
        request: Request,
        db: NamedDependency[AsyncSession],
    ) -> Response[None]:
        """Delete the feeder's sightings older than `before`, with their images.

        **Feeder owner or owner role only.** `before` is required, so no request
        clears a feeder's whole history by leaving it out.
        """
        device = await get_device(db, device_id)
        if device is None:
            raise NotFoundException()
        _assert_owner(request, device)
        cutoff = _parse_before(before)
        count = await delete_sightings_before(db, device_id, cutoff)
        logger.info(
            "%d sightings before %s deleted from device %d by user %d",
            count, cutoff.isoformat(), device_id, request.state.user_id,
        )
        # Published after the commit, like DELETE /sightings/{id}.
        return Response(
            content=None,
            status_code=204,
            background=BackgroundTask(_announce, SightingsDeleted(device_id=device_id, count=count))
            if count else None,
        )

    @put("/{device_id:int}", guards=[user_guard], security=USER_JWT)
    async def update(
        self, device_id: FromPath[int], data: UpdateDevice, request: Request, db: NamedDependency[AsyncSession]
    ) -> DeviceResponse:
        device = await get_device(db, device_id)
        if device is None:
            raise NotFoundException()
        _assert_owner(request, device)
        if data.name is not None and not data.name.strip():
            raise HTTPException(status_code=400, detail="A feeder needs a name.")
        if data.owner_id is not None and data.owner_id != device.owner_id:
            if await get_user_by_id(db, data.owner_id) is None:
                raise HTTPException(status_code=400, detail="No such user.")
            device = await transfer_device(db, device, data.owner_id)
        device = await update_device(
            db,
            device,
            name=data.name,
            city=data.city,
            state=data.state,
            feed_type=data.feed_type,
        )
        return await _to_response(db, device)

    @post("/{device_id:int}/refills", guards=[user_guard], security=USER_JWT, status_code=201)
    async def refill(
        self, device_id: FromPath[int], request: Request, db: NamedDependency[AsyncSession]
    ) -> DeviceResponse:
        """Log that the feeder was just filled. **Feeder owner or owner role only.**

        Ends any low or out alert, and starts the next fill for the forecast.
        """
        device = await get_device(db, device_id)
        if device is None:
            raise NotFoundException()
        _assert_owner(request, device)
        await log_refill(db, device, request.state.user_id, datetime.now(timezone.utc))
        return await _to_response(db, device)

    @post("/me/heartbeat", guards=[device_guard], security=DEVICE_TOKEN, status_code=200)
    async def heartbeat_self(
        self, data: DeviceHeartbeat, request: Request, db: NamedDependency[AsyncSession]
    ) -> DeviceResponse:
        # The Pi holds only its token, not its id. The token names the device.
        device = await get_device(db, request.state.device_id)
        if device is None:
            raise NotFoundException()
        device = await _record_heartbeat(db, device, data)
        return await _to_response(db, device)

    @post("/{device_id:int}/heartbeat", guards=[device_guard], security=DEVICE_TOKEN, status_code=200)
    async def heartbeat(
        self, device_id: FromPath[int], data: DeviceHeartbeat, request: Request, db: NamedDependency[AsyncSession]
    ) -> DeviceResponse:
        # The Pi authenticates with its device token; it may only report for itself.
        if request.state.device_id != device_id:
            raise HTTPException(status_code=403, detail="Forbidden")
        device = await get_device(db, device_id)
        if device is None:
            raise NotFoundException()
        device = await _record_heartbeat(db, device, data)
        return await _to_response(db, device)

    @get("/{device_id:int}/users", guards=[user_guard], security=USER_JWT)
    async def list_access(
        self, device_id: FromPath[int], request: Request, db: NamedDependency[AsyncSession]
    ) -> DeviceAccessResponse:
        """The feeder's owner and members. These are its alert recipients."""
        device = await get_device(db, device_id)
        if device is None:
            raise NotFoundException()
        _assert_owner(request, device)
        owner = await get_user_by_id(db, device.owner_id)
        members = await get_device_members(db, device_id)
        return DeviceAccessResponse(owner=_member(owner), members=[_member(u) for u in members])

    @post("/{device_id:int}/users", guards=[user_guard], security=USER_JWT, status_code=204)
    async def add_user(
        self, device_id: FromPath[int], data: AddDeviceUser, request: Request, db: NamedDependency[AsyncSession]
    ) -> None:
        device = await get_device(db, device_id)
        if device is None:
            raise NotFoundException()
        _assert_owner(request, device)
        if (data.user_id is None) == (data.email is None):
            raise HTTPException(status_code=400, detail="Send one of user_id or email.")
        if data.user_id is not None:
            user = await get_user_by_id(db, data.user_id)
        else:
            user = await get_user_by_email(db, data.email.strip())
        if user is None:
            detail = "No user has that email." if data.email is not None else "No such user."
            raise HTTPException(status_code=404, detail=detail)
        if user.id == device.owner_id:
            raise HTTPException(status_code=400, detail=f"{user.name} owns this feeder.")
        await add_device_user(db, device_id, user.id)

    @delete("/{device_id:int}/users/{uid:int}", guards=[user_guard], security=USER_JWT, status_code=204)
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
