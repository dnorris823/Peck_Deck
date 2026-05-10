from litestar import Controller, Request, delete, get, post, put
from litestar.exceptions import HTTPException, NotFoundException
from sqlalchemy.ext.asyncio import AsyncSession

from ..auth.guards import user_guard
from ..auth.jwt_utils import create_user_token
from .operations import (
    authenticate,
    create_user,
    delete_user,
    get_user_by_email,
    get_user_by_id,
    update_user,
)
from .schemas import LoginRequest, RegisterUser, TokenResponse, UpdateUser, UserResponse


def _to_response(user) -> UserResponse:
    return UserResponse(
        id=user.id,
        name=user.name,
        email=user.email,
        phone=user.phone,
        notify_email=user.notify_email,
        notify_sms=user.notify_sms,
        role=user.role,
    )


@post("/login")
async def login(data: LoginRequest, db: AsyncSession) -> TokenResponse:
    user = await authenticate(db, data.email, data.password)
    if user is None:
        raise HTTPException(status_code=401, detail="Invalid email or password")
    return TokenResponse(access_token=create_user_token(user.id, user.role))


class UserController(Controller):
    path = "/users"

    @post("/", status_code=201)
    async def register(self, data: RegisterUser, db: AsyncSession) -> UserResponse:
        existing = await get_user_by_email(db, data.email)
        if existing is not None:
            raise HTTPException(status_code=409, detail="Email already registered")
        user = await create_user(
            db,
            name=data.name,
            email=data.email,
            password=data.password,
            phone=data.phone,
            role=data.role,
        )
        return _to_response(user)

    @get("/{user_id:int}", guards=[user_guard])
    async def get_user(self, user_id: int, request: Request, db: AsyncSession) -> UserResponse:
        if request.state.user_id != user_id and request.state.role != "owner":
            raise HTTPException(status_code=403, detail="Forbidden")
        user = await get_user_by_id(db, user_id)
        if user is None:
            raise NotFoundException()
        return _to_response(user)

    @put("/{user_id:int}", guards=[user_guard])
    async def update(
        self, user_id: int, data: UpdateUser, request: Request, db: AsyncSession
    ) -> UserResponse:
        if request.state.user_id != user_id and request.state.role != "owner":
            raise HTTPException(status_code=403, detail="Forbidden")
        user = await get_user_by_id(db, user_id)
        if user is None:
            raise NotFoundException()
        user = await update_user(
            db,
            user,
            name=data.name,
            phone=data.phone,
            notify_email=data.notify_email,
            notify_sms=data.notify_sms,
        )
        return _to_response(user)

    @delete("/{user_id:int}", guards=[user_guard], status_code=204)
    async def remove(self, user_id: int, request: Request, db: AsyncSession) -> None:
        if request.state.user_id != user_id and request.state.role != "owner":
            raise HTTPException(status_code=403, detail="Forbidden")
        user = await get_user_by_id(db, user_id)
        if user is None:
            raise NotFoundException()
        await delete_user(db, user)
