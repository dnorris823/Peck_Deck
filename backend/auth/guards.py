from litestar.connection import ASGIConnection
from litestar.exceptions import NotAuthorizedException
from litestar.handlers import BaseRouteHandler
from sqlalchemy import select

from ..database.connection import get_session_factory
from ..database.models import Device
from .jwt_utils import decode_user_token


def _bearer_token(connection: ASGIConnection) -> str:
    header = connection.headers.get("Authorization", "")
    if not header.startswith("Bearer "):
        raise NotAuthorizedException("Missing or malformed Authorization header")
    return header[7:].strip()


def user_guard(connection: ASGIConnection, _: BaseRouteHandler) -> None:
    token = _bearer_token(connection)
    try:
        payload = decode_user_token(token)
        connection.state.user_id = int(payload["sub"])
        connection.state.role = payload.get("role", "viewer")
    except Exception:
        raise NotAuthorizedException("Invalid or expired token")


def owner_guard(connection: ASGIConnection, handler: BaseRouteHandler) -> None:
    user_guard(connection, handler)
    if connection.state.role != "owner":
        raise NotAuthorizedException("Owner role required")


async def device_guard(connection: ASGIConnection, _: BaseRouteHandler) -> None:
    token = _bearer_token(connection)
    async with get_session_factory()() as db:
        result = await db.execute(select(Device).where(Device.token == token))
        device = result.scalar_one_or_none()
        if device is None:
            raise NotAuthorizedException("Invalid device token")
        connection.state.device_id = device.id
