import uuid
from fastapi import Depends, Header
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.exceptions import (
    AuthenticationError,
    ForbiddenActionError,
    RateLimitExceededError,
)
from app.core.redis_bus import redis_bus
from app.core.security import decode_access_token
from app.db.session import get_db_session
from app.models.enums import UserRole
from app.models.game import GameParticipant
from app.models.user import User
from app.modules.auth.service import get_user_by_id

bearer_scheme = HTTPBearer(auto_error=False)


async def get_current_user(
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer_scheme),
    session: AsyncSession = Depends(get_db_session),
) -> User:
    if credentials is None or not credentials.credentials:
        raise AuthenticationError("Missing Authorization Bearer token.")
    claims = decode_access_token(credentials.credentials)
    sub = claims.get("sub")
    if not sub:
        raise AuthenticationError("Malformed token subject.")
    return await get_user_by_id(session, uuid.UUID(sub))


async def require_admin(user: User = Depends(get_current_user)) -> User:
    if user.role != UserRole.ADMIN.value:
        raise ForbiddenActionError("Administrator privileges required for this action.")
    return user


async def get_active_participant_seat(
    game_id: uuid.UUID,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_db_session),
) -> GameParticipant:
    gp = (
        await session.execute(
            select(GameParticipant).where(
                GameParticipant.game_id == game_id,
                GameParticipant.user_id == user.id,
            )
        )
    ).scalar_one_or_none()
    if gp is None or not gp.allocation_initialized:
        raise ForbiddenActionError("You have not joined or been initialized in this tournament game.")
    if gp.is_disqualified:
        raise ForbiddenActionError("Your tournament seat has been disqualified.")
    return gp


async def enforce_order_rate_limit(user: User = Depends(get_current_user)) -> None:
    settings = get_settings()
    allowed = await redis_bus.check_rate_limit(
        f"mtt:ratelimit:orders:{user.id}",
        limit=settings.ORDER_RATE_LIMIT_PER_10S,
        window_sec=10,
    )
    if not allowed:
        raise RateLimitExceededError("Order rate limit exceeded; slow down order submissions.")


def get_idempotency_key(
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
) -> str | None:
    return idempotency_key
