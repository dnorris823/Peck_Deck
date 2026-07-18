from litestar import Controller, Request, delete, get, post, put
from litestar.di import NamedDependency
from litestar.exceptions import HTTPException, NotFoundException
from litestar.params import FromPath
from sqlalchemy.ext.asyncio import AsyncSession

from ..auth.guards import user_guard
from ..auth.jwt_utils import create_user_token, verify_password
from .operations import (
    authenticate,
    create_user,
    delete_user,
    get_or_create_preferences,
    get_user_by_email,
    get_user_by_id,
    list_users,
    set_password,
    update_preferences,
    update_user,
)
from .schemas import (
    LoginRequest,
    PreferencesResponse,
    RegisterUser,
    TokenResponse,
    UpdatePassword,
    UpdatePreferences,
    UpdateUser,
    UserResponse,
)

_ALLOWED_TIERS = {"local", "gpu", "cloud", "auto"}


def _prefs_response(prefs) -> PreferencesResponse:
    return PreferencesResponse(
        quiet_interval_seconds=prefs.quiet_interval_seconds,
        notify_new_species_only=prefs.notify_new_species_only,
        default_tier=prefs.default_tier,
        escalation_threshold=prefs.escalation_threshold,
        debounce_seconds=prefs.debounce_seconds,
    )


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
async def login(data: LoginRequest, db: NamedDependency[AsyncSession]) -> TokenResponse:
    user = await authenticate(db, data.email, data.password)
    if user is None:
        raise HTTPException(status_code=401, detail="Invalid email or password")
    return TokenResponse(access_token=create_user_token(user.id, user.role))


class UserController(Controller):
    path = "/users"

    @get("/", guards=[user_guard])
    async def list_all(self, db: NamedDependency[AsyncSession]) -> list[UserResponse]:
        return [_to_response(u) for u in await list_users(db)]

    @post("/", status_code=201)
    async def register(self, data: RegisterUser, db: NamedDependency[AsyncSession]) -> UserResponse:
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

    @get("/me", guards=[user_guard])
    async def me(self, request: Request, db: NamedDependency[AsyncSession]) -> UserResponse:
        user = await get_user_by_id(db, request.state.user_id)
        if user is None:
            raise NotFoundException()
        return _to_response(user)

    @get("/me/preferences", guards=[user_guard])
    async def get_preferences(
        self, request: Request, db: NamedDependency[AsyncSession]
    ) -> PreferencesResponse:
        prefs = await get_or_create_preferences(db, request.state.user_id)
        return _prefs_response(prefs)

    @put("/me/preferences", guards=[user_guard])
    async def put_preferences(
        self, data: UpdatePreferences, request: Request, db: NamedDependency[AsyncSession]
    ) -> PreferencesResponse:
        if data.default_tier is not None and data.default_tier not in _ALLOWED_TIERS:
            raise HTTPException(status_code=400, detail="Invalid default_tier")
        if data.escalation_threshold is not None and not (
            40 <= data.escalation_threshold <= 95
        ):
            raise HTTPException(
                status_code=400, detail="escalation_threshold must be 40–95"
            )
        if data.quiet_interval_seconds is not None and not (
            10 <= data.quiet_interval_seconds <= 600
        ):
            raise HTTPException(
                status_code=400, detail="quiet_interval_seconds must be 10–600"
            )
        if data.debounce_seconds is not None and data.debounce_seconds < 0:
            raise HTTPException(
                status_code=400, detail="debounce_seconds must be non-negative"
            )
        prefs = await get_or_create_preferences(db, request.state.user_id)
        prefs = await update_preferences(
            db,
            prefs,
            quiet_interval_seconds=data.quiet_interval_seconds,
            notify_new_species_only=data.notify_new_species_only,
            default_tier=data.default_tier,
            escalation_threshold=data.escalation_threshold,
            debounce_seconds=data.debounce_seconds,
        )
        return _prefs_response(prefs)

    @get("/{user_id:int}", guards=[user_guard])
    async def get_user(self, user_id: FromPath[int], request: Request, db: NamedDependency[AsyncSession]) -> UserResponse:
        if request.state.user_id != user_id and request.state.role != "owner":
            raise HTTPException(status_code=403, detail="Forbidden")
        user = await get_user_by_id(db, user_id)
        if user is None:
            raise NotFoundException()
        return _to_response(user)

    @put("/{user_id:int}", guards=[user_guard])
    async def update(
        self, user_id: FromPath[int], data: UpdateUser, request: Request, db: NamedDependency[AsyncSession]
    ) -> UserResponse:
        if request.state.user_id != user_id and request.state.role != "owner":
            raise HTTPException(status_code=403, detail="Forbidden")
        user = await get_user_by_id(db, user_id)
        if user is None:
            raise NotFoundException()
        # Email is the login identity and is UNIQUE — reject a collision with 409.
        if data.email is not None and data.email != user.email:
            existing = await get_user_by_email(db, data.email)
            if existing is not None and existing.id != user_id:
                raise HTTPException(status_code=409, detail="Email already registered")
        user = await update_user(
            db,
            user,
            name=data.name,
            phone=data.phone,
            notify_email=data.notify_email,
            notify_sms=data.notify_sms,
            email=data.email,
        )
        return _to_response(user)

    @post("/{user_id:int}/password", guards=[user_guard], status_code=204)
    async def change_password(
        self, user_id: FromPath[int], data: UpdatePassword, request: Request, db: NamedDependency[AsyncSession]
    ) -> None:
        is_self = request.state.user_id == user_id
        is_owner = request.state.role == "owner"
        if not is_self and not is_owner:
            raise HTTPException(status_code=403, detail="Forbidden")
        user = await get_user_by_id(db, user_id)
        if user is None:
            raise NotFoundException()
        # Self change requires the current password; an owner resetting someone
        # else's password does not (standard admin-reset behavior).
        if is_self:
            if not data.current_password or not verify_password(
                data.current_password, user.password_hash
            ):
                raise HTTPException(status_code=400, detail="Current password is incorrect")
        if not data.new_password:
            raise HTTPException(status_code=400, detail="New password is required")
        await set_password(db, user, data.new_password)

    @delete("/{user_id:int}", guards=[user_guard], status_code=204)
    async def remove(self, user_id: FromPath[int], request: Request, db: NamedDependency[AsyncSession]) -> None:
        if request.state.user_id != user_id and request.state.role != "owner":
            raise HTTPException(status_code=403, detail="Forbidden")
        user = await get_user_by_id(db, user_id)
        if user is None:
            raise NotFoundException()
        await delete_user(db, user)
