from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user
from app.db.session import get_db_session
from app.models.user import User
from app.modules.auth.schemas import (
    AuthTokenResponse,
    LoginRequest,
    RegisterPlayerRequest,
    UserProfileResponse,
)
from app.modules.auth.service import (
    authenticate_user,
    build_user_profile,
    register_player,
)

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post("/register", response_model=AuthTokenResponse)
async def api_register_player(
    req: RegisterPlayerRequest,
    session: AsyncSession = Depends(get_db_session),
) -> AuthTokenResponse:
    async with session.begin():
        return await register_player(session, req)


@router.post("/login", response_model=AuthTokenResponse)
async def api_login(
    req: LoginRequest,
    session: AsyncSession = Depends(get_db_session),
) -> AuthTokenResponse:
    async with session.begin():
        return await authenticate_user(session, req)


@router.get("/me", response_model=UserProfileResponse)
async def api_me(user: User = Depends(get_current_user)) -> UserProfileResponse:
    return build_user_profile(user)
