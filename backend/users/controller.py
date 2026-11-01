from litestar import Controller, Request, delete, get, post, put
from litestar.di import NamedDependency
from litestar.exceptions import HTTPException, NotFoundException
from litestar.params import FromPath
from sqlalchemy.ext.asyncio import AsyncSession

from ..animals.groups import GROUPS, resolved_alerts
from ..auth.guards import USER_JWT, owner_guard, user_guard
from ..auth.jwt_utils import create_user_token, verify_password
from ..auth.rate_limit import login_rate_limiter
from ..notifications.digest import parse_time
from ..stats.operations import parse_zone
from .operations import (
    authenticate,
    create_user,
    delete_user,
    get_or_create_preferences,
    get_user_by_email,
    get_user_by_id,
    is_last_owner,
    list_users,
    owned_device_names,
    revoke_tokens,
    set_password,
    set_role,
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
    UpdateRole,
    UpdateUser,
    UserResponse,
)

# Roles a client may ask for. Anything else is rejected rather than silently
# stored — role is what the guards key off, so an unexpected value is a bug.
_ALLOWED_ROLES = {"owner", "viewer"}


# Animal pushes come at most once per this many seconds per feeder and group.
ANIMAL_INTERVAL_RANGE = (60, 86400)


def _prefs_response(prefs) -> PreferencesResponse:
    return PreferencesResponse(
        quiet_interval_seconds=prefs.quiet_interval_seconds,
        notify_new_species_only=prefs.notify_new_species_only,
        notify_first_ever=prefs.notify_first_ever,
        notify_first_at_feeder=prefs.notify_first_at_feeder,
        notify_first_this_year=prefs.notify_first_this_year,
        animal_alerts=resolved_alerts(prefs.animal_alerts),
        animal_quiet_interval_seconds=prefs.animal_quiet_interval_seconds or 1800,
        time_zone=prefs.time_zone,
        digest_push=bool(prefs.digest_push),
        digest_push_time=prefs.digest_push_time or "19:00",
        digest_email=bool(prefs.digest_email),
    )


def _to_response(user) -> UserResponse:
    return UserResponse(
        id=user.id,
        name=user.name,
        email=user.email,
        notify_email=user.notify_email,
        role=user.role,
    )


@post("/login")
async def login(
    data: LoginRequest, request: Request, db: NamedDependency[AsyncSession]
) -> TokenResponse:
    """Authenticate and issue a JWT.

    Throttled per account *and* per client IP — this is the only unauthenticated
    endpoint that checks a secret, and bcrypt verification is expensive enough
    that unlimited attempts are a denial-of-service as well as a brute-force
    risk.
    """
    account_key = f"account:{data.email.lower()}"
    client_ip = request.client.host if request.client else "unknown"
    ip_key = f"ip:{client_ip}"

    for key in (account_key, ip_key):
        if login_rate_limiter.is_locked(key):
            raise HTTPException(
                status_code=429,
                detail="Too many failed login attempts. Try again later.",
                headers={"Retry-After": str(login_rate_limiter.retry_after(key))},
            )

    user = await authenticate(db, data.email, data.password)
    if user is None:
        login_rate_limiter.record_failure(account_key)
        login_rate_limiter.record_failure(ip_key)
        # Deliberately identical for unknown-email and wrong-password so the
        # response can't be used to enumerate which accounts exist.
        raise HTTPException(status_code=401, detail="Invalid email or password")

    login_rate_limiter.reset(account_key)
    login_rate_limiter.reset(ip_key)
    return TokenResponse(
        access_token=create_user_token(user.id, user.role, user.token_version)
    )


@post("/logout", guards=[user_guard], security=USER_JWT, status_code=204)
async def logout(request: Request, db: NamedDependency[AsyncSession]) -> None:
    """Sign out. Revokes every token the caller holds, on every device.

    A JWT lasts 30 days, so dropping it from the browser is not enough. A copy
    would stay valid. The cost is that signing out on one device signs out the
    others too.
    """
    user = await get_user_by_id(db, request.state.user_id)
    if user is not None:
        await revoke_tokens(db, user)


class UserController(Controller):
    path = "/users"

    @get("/", guards=[owner_guard], security=USER_JWT)
    async def list_all(self, db: NamedDependency[AsyncSession]) -> list[UserResponse]:
        """Every user and their email. **Owner only.** A viewer reads `/users/me`."""
        return [_to_response(u) for u in await list_users(db)]

    @post("/", status_code=201, guards=[owner_guard], security=USER_JWT)
    async def register(self, data: RegisterUser, db: NamedDependency[AsyncSession]) -> UserResponse:
        """Invite a new user. **Owner only.**

        This was unauthenticated, and `RegisterUser.role` is client-supplied —
        so anyone who could reach the API could POST role="owner" and mint
        themselves a full-privilege account, then enumerate every user's email
        address. It is an invite flow driven from the settings screen
        (frontend `UsersSettings.jsx`), so it requires an owner.
        """
        if data.role not in _ALLOWED_ROLES:
            raise HTTPException(
                status_code=400,
                detail=f"role must be one of {sorted(_ALLOWED_ROLES)}",
            )
        existing = await get_user_by_email(db, data.email)
        if existing is not None:
            raise HTTPException(status_code=409, detail="Email already registered")
        user = await create_user(
            db,
            name=data.name,
            email=data.email,
            password=data.password,
            role=data.role,
        )
        return _to_response(user)

    @get("/me", guards=[user_guard], security=USER_JWT)
    async def me(self, request: Request, db: NamedDependency[AsyncSession]) -> UserResponse:
        user = await get_user_by_id(db, request.state.user_id)
        if user is None:
            raise NotFoundException()
        return _to_response(user)

    @get("/me/preferences", guards=[user_guard], security=USER_JWT)
    async def get_preferences(
        self, request: Request, db: NamedDependency[AsyncSession]
    ) -> PreferencesResponse:
        prefs = await get_or_create_preferences(db, request.state.user_id)
        return _prefs_response(prefs)

    @put("/me/preferences", guards=[user_guard], security=USER_JWT)
    async def put_preferences(
        self, data: UpdatePreferences, request: Request, db: NamedDependency[AsyncSession]
    ) -> PreferencesResponse:
        if data.quiet_interval_seconds is not None and not (
            10 <= data.quiet_interval_seconds <= 600
        ):
            raise HTTPException(
                status_code=400, detail="quiet_interval_seconds must be 10–600"
            )
        if data.animal_alerts is not None:
            unknown = sorted(set(data.animal_alerts) - set(GROUPS))
            if unknown or not all(isinstance(v, bool) for v in data.animal_alerts.values()):
                raise HTTPException(
                    status_code=400,
                    detail=f"animal_alerts maps a group ({', '.join(GROUPS)}) to true or false",
                )
        low, high = ANIMAL_INTERVAL_RANGE
        if data.animal_quiet_interval_seconds is not None and not (
            low <= data.animal_quiet_interval_seconds <= high
        ):
            raise HTTPException(
                status_code=400, detail=f"animal_quiet_interval_seconds must be {low}–{high}"
            )
        if data.time_zone is not None:
            try:
                parse_zone(data.time_zone)
            except ValueError as exc:
                raise HTTPException(status_code=400, detail=str(exc))
        if data.digest_push_time is not None and parse_time(data.digest_push_time) is None:
            raise HTTPException(status_code=400, detail="digest_push_time must be HH:MM, between 00:00 and 23:59")
        prefs = await get_or_create_preferences(db, request.state.user_id)
        prefs = await update_preferences(
            db,
            prefs,
            quiet_interval_seconds=data.quiet_interval_seconds,
            notify_new_species_only=data.notify_new_species_only,
            new_species_alerts={
                "notify_first_ever": data.notify_first_ever,
                "notify_first_at_feeder": data.notify_first_at_feeder,
                "notify_first_this_year": data.notify_first_this_year,
            },
            animal_alerts=data.animal_alerts,
            animal_quiet_interval_seconds=data.animal_quiet_interval_seconds,
            digests={
                "time_zone": data.time_zone,
                "digest_push": data.digest_push,
                "digest_push_time": data.digest_push_time,
                "digest_email": data.digest_email,
            },
        )
        return _prefs_response(prefs)

    @get("/{user_id:int}", guards=[user_guard], security=USER_JWT)
    async def get_user(self, user_id: FromPath[int], request: Request, db: NamedDependency[AsyncSession]) -> UserResponse:
        if request.state.user_id != user_id and request.state.role != "owner":
            raise HTTPException(status_code=403, detail="Forbidden")
        user = await get_user_by_id(db, user_id)
        if user is None:
            raise NotFoundException()
        return _to_response(user)

    @put("/{user_id:int}", guards=[user_guard], security=USER_JWT)
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
            notify_email=data.notify_email,
            email=data.email,
        )
        return _to_response(user)

    @post("/{user_id:int}/password", guards=[user_guard], security=USER_JWT, status_code=204)
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
        # An owner resetting someone else's password is how an owner cuts a
        # user off without deleting them, so it signs that user out everywhere.
        if not is_self:
            await revoke_tokens(db, user)

    @put("/{user_id:int}/role", guards=[owner_guard], security=USER_JWT)
    async def change_role(
        self, user_id: FromPath[int], data: UpdateRole, db: NamedDependency[AsyncSession]
    ) -> UserResponse:
        """Make a user an owner or a viewer. **Owner only.**

        It applies on the user's next request, because `user_guard` reads the
        role from the database. Refuses to demote the last owner.
        """
        if data.role not in _ALLOWED_ROLES:
            raise HTTPException(
                status_code=400,
                detail=f"role must be one of {sorted(_ALLOWED_ROLES)}",
            )
        user = await get_user_by_id(db, user_id)
        if user is None:
            raise NotFoundException()
        if data.role != "owner" and await is_last_owner(db, user):
            raise HTTPException(status_code=409, detail="The last owner cannot be demoted.")
        return _to_response(await set_role(db, user, data.role))

    @post("/{user_id:int}/logout", guards=[owner_guard], security=USER_JWT, status_code=204)
    async def logout_user(self, user_id: FromPath[int], db: NamedDependency[AsyncSession]) -> None:
        """Sign a user out on every device. **Owner only.** For a lost phone.

        Unlike a password reset, the user's password still works.
        """
        user = await get_user_by_id(db, user_id)
        if user is None:
            raise NotFoundException()
        await revoke_tokens(db, user)

    @delete("/{user_id:int}", guards=[user_guard], security=USER_JWT, status_code=204)
    async def remove(self, user_id: FromPath[int], request: Request, db: NamedDependency[AsyncSession]) -> None:
        """Delete a user, their feeder memberships and their preferences.

        Refused with 409 while the user owns a feeder, since the feeder's
        sightings hold the only copy of each image. Refused for the last owner.
        """
        if request.state.user_id != user_id and request.state.role != "owner":
            raise HTTPException(status_code=403, detail="Forbidden")
        user = await get_user_by_id(db, user_id)
        if user is None:
            raise NotFoundException()
        feeders = await owned_device_names(db, user_id)
        if feeders:
            raise HTTPException(
                status_code=409,
                detail=f"{user.name} owns {', '.join(feeders)}. "
                "A user who owns a feeder cannot be removed.",
            )
        if await is_last_owner(db, user):
            raise HTTPException(status_code=409, detail="The last owner cannot be removed.")
        await delete_user(db, user)
