from litestar.connection import ASGIConnection
from litestar.exceptions import NotAuthorizedException, PermissionDeniedException
from litestar.handlers import BaseRouteHandler
from sqlalchemy import select

from ..database.connection import get_session_factory
from ..database.models import Device, User
from .jwt_utils import decode_user_token


# OpenAPI security requirements, named after the schemes in backend/main.py.
# Put one beside every guard. Swagger UI's Authorize button sends a token only
# to routes that declare a scheme, so a guarded route without one gets 401 there.
USER_JWT = [{"UserJWT": []}]
DEVICE_TOKEN = [{"DeviceToken": []}]


def _bearer_token(connection: ASGIConnection) -> str:
    header = connection.headers.get("Authorization", "")
    if not header.startswith("Bearer "):
        raise NotAuthorizedException("Missing or malformed Authorization header")
    return header[7:].strip()


async def user_guard(connection: ASGIConnection, _: BaseRouteHandler) -> None:
    """Accept a user JWT whose user still exists at the same token_version.

    A token lasts JWT_EXPIRE_HOURS, 30 days by default, so the signature alone
    is not enough. Signing out or an owner password reset bumps the user's
    token_version, and deleting the user removes the row. Either one rejects
    the token on its next request. Role comes from the row, not the claim, so a
    role change also applies at once.

    The guard opens its own short session, as device_guard does. The SSE stream
    is guarded by this and must not hold a request-long DB session.
    """
    token = _bearer_token(connection)
    try:
        payload = decode_user_token(token)
        user_id = int(payload["sub"])
        version = int(payload.get("ver", 0))
    except Exception:
        raise NotAuthorizedException("Invalid or expired token")
    async with get_session_factory()() as db:
        result = await db.execute(
            select(User.role, User.token_version).where(User.id == user_id)
        )
        row = result.one_or_none()
    if row is None or row.token_version != version:
        raise NotAuthorizedException("Invalid or expired token")
    connection.state.user_id = user_id
    connection.state.role = row.role or "viewer"


async def owner_guard(connection: ASGIConnection, handler: BaseRouteHandler) -> None:
    """Accept a user JWT whose user has the owner role.

    A viewer gets 403, not 401. The web app treats 401 as an expired session
    and signs the user out, so a viewer who hit an owner route would lose their
    session for it.
    """
    await user_guard(connection, handler)
    if connection.state.role != "owner":
        raise PermissionDeniedException("Owner role required")


async def device_guard(connection: ASGIConnection, _: BaseRouteHandler) -> None:
    token = _bearer_token(connection)
    async with get_session_factory()() as db:
        result = await db.execute(select(Device).where(Device.token == token))
        device = result.scalar_one_or_none()
        if device is None:
            raise NotAuthorizedException("Invalid device token")
        connection.state.device_id = device.id
