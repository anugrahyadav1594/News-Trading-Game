import secrets
import uuid
from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.exceptions import AuthenticationError, DuplicateAccountError
from app.core.security import create_access_token, hash_password, verify_password
from app.models.enums import AdminLevel, UserRole
from app.models.user import AdministratorAccount, Participant, User
from app.modules.auth.schemas import (
    AuthTokenResponse,
    LoginRequest,
    RegisterPlayerRequest,
    UserProfileResponse,
)


async def _generate_unique_tournament_code(session: AsyncSession) -> str:
    for _ in range(25):
        code = f"MTT-{secrets.randbelow(900000) + 100000}"
        exists = (
            await session.execute(select(Participant.id).where(Participant.tournament_code == code))
        ).scalar_one_or_none()
        if exists is None:
            return code
    return f"MTT-{uuid.uuid4().hex[:8].upper()}"


def build_user_profile(user: User) -> UserProfileResponse:
    part = user.participant
    return UserProfileResponse(
        user_id=user.id,
        email=user.email,
        username=user.username,
        role=user.role,
        participant_id=part.id if part else None,
        tournament_code=part.tournament_code if part else None,
        display_name=part.display_name if part else user.username,
        institution=part.institution if part else None,
        created_at=user.created_at,
    )


async def register_player(session: AsyncSession, req: RegisterPlayerRequest) -> AuthTokenResponse:
    email_norm = req.email.strip().lower()
    username_norm = req.username.strip()

    existing = (
        await session.execute(
            select(User).where(
                or_(
                    func.lower(User.email) == email_norm,
                    func.lower(User.username) == username_norm.lower(),
                )
            )
        )
    ).scalar_one_or_none()
    if existing is not None:
        raise DuplicateAccountError("An account with that email or username already exists.")

    user = User(
        email=email_norm,
        username=username_norm,
        password_hash=hash_password(req.password),
        role=UserRole.PLAYER.value,
        is_active=True,
    )
    session.add(user)
    await session.flush()

    t_code = await _generate_unique_tournament_code(session)
    participant = Participant(
        user_id=user.id,
        tournament_code=t_code,
        display_name=req.display_name.strip(),
        institution=req.institution.strip() if req.institution else None,
    )
    session.add(participant)
    await session.flush()
    user.participant = participant

    token = create_access_token(user.id, user.role, {"tournament_code": t_code})
    return AuthTokenResponse(access_token=token, user=build_user_profile(user))


async def ensure_admin_user(
    session: AsyncSession,
    *,
    email: str,
    username: str,
    password: str,
    admin_level: str = AdminLevel.TOURNAMENT_DIRECTOR.value,
) -> User:
    email_norm = email.strip().lower()
    stmt = (
        select(User)
        .options(selectinload(User.participant), selectinload(User.admin_account))
        .where(func.lower(User.email) == email_norm)
    )
    existing = (await session.execute(stmt)).scalar_one_or_none()
    if existing is not None:
        return existing

    user = User(
        email=email_norm,
        username=username,
        password_hash=hash_password(password),
        role=UserRole.ADMIN.value,
        is_active=True,
    )
    session.add(user)
    await session.flush()

    admin_acc = AdministratorAccount(
        user_id=user.id,
        admin_level=admin_level,
        can_emergency_halt=True,
    )
    session.add(admin_acc)
    await session.flush()
    user.admin_account = admin_acc
    user.participant = None
    return user


async def authenticate_user(session: AsyncSession, req: LoginRequest) -> AuthTokenResponse:
    ident = req.identifier.strip().lower()
    stmt = (
        select(User)
        .options(selectinload(User.participant), selectinload(User.admin_account))
        .where(or_(func.lower(User.email) == ident, func.lower(User.username) == ident))
    )
    user = (await session.execute(stmt)).scalar_one_or_none()
    if user is None or not user.is_active or not verify_password(req.password, user.password_hash):
        raise AuthenticationError("Invalid email/username or password.")

    extra = {}
    if user.participant:
        extra["tournament_code"] = user.participant.tournament_code
    token = create_access_token(user.id, user.role, extra)
    return AuthTokenResponse(access_token=token, user=build_user_profile(user))


async def get_user_by_id(session: AsyncSession, user_id: uuid.UUID) -> User:
    stmt = (
        select(User)
        .options(selectinload(User.participant), selectinload(User.admin_account))
        .where(User.id == user_id)
    )
    user = (await session.execute(stmt)).scalar_one_or_none()
    if user is None or not user.is_active:
        raise AuthenticationError("User account not found or inactive.")
    return user
