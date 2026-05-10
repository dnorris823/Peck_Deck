from litestar import Controller, Request, delete, get, post, put
from litestar.exceptions import HTTPException, NotFoundException
from sqlalchemy.ext.asyncio import AsyncSession

from ..auth.guards import user_guard
from .operations import (
    add_device_user,
    create_device,
    get_device,
    get_devices_for_user,
    remove_device_user,
    update_device,
)
from .schemas import AddDeviceUser, DeviceResponse, RegisterDevice, UpdateDevice


def _to_response(device) -> DeviceResponse:
    return DeviceResponse(
        id=device.id,
        name=device.name,
        city=device.city,
        state=device.state,
        owner_id=device.owner_id,
        classification_tier=device.classification_tier,
        feed_type=device.feed_type,
        token=device.token,
    )


def _assert_owner(request: Request, device) -> None:
    if device.owner_id != request.state.user_id and request.state.role != "owner":
        raise HTTPException(status_code=403, detail="Forbidden")


class DeviceController(Controller):
    path = "/devices"
    guards = [user_guard]

    @get("/")
    async def list_devices(self, request: Request, db: AsyncSession) -> list[DeviceResponse]:
        devices = await get_devices_for_user(db, request.state.user_id)
        return [_to_response(d) for d in devices]

    @post("/", status_code=201)
    async def register(
        self, data: RegisterDevice, request: Request, db: AsyncSession
    ) -> DeviceResponse:
        device = await create_device(
            db,
            name=data.name,
            city=data.city,
            state=data.state,
            owner_id=request.state.user_id,
            classification_tier=data.classification_tier,
            feed_type=data.feed_type,
        )
        return _to_response(device)

    @put("/{device_id:int}")
    async def update(
        self, device_id: int, data: UpdateDevice, request: Request, db: AsyncSession
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
        return _to_response(device)

    @post("/{device_id:int}/users", status_code=204)
    async def add_user(
        self, device_id: int, data: AddDeviceUser, request: Request, db: AsyncSession
    ) -> None:
        device = await get_device(db, device_id)
        if device is None:
            raise NotFoundException()
        _assert_owner(request, device)
        await add_device_user(db, device_id, data.user_id)

    @delete("/{device_id:int}/users/{uid:int}", status_code=204)
    async def remove_user(
        self, device_id: int, uid: int, request: Request, db: AsyncSession
    ) -> None:
        device = await get_device(db, device_id)
        if device is None:
            raise NotFoundException()
        _assert_owner(request, device)
        removed = await remove_device_user(db, device_id, uid)
        if not removed:
            raise NotFoundException()
