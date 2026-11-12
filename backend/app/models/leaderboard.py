import uuid
from datetime import datetime, timezone
from decimal import Decimal
from sqlalchemy import Boolean, DateTime, ForeignKey, Index, Integer, Numeric, String
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class LeaderboardSnapshot(Base):
    __tablename__ = "leaderboard_snapshots"
    __table_args__ = (
        Index("ix_leaderboard_game_type_rank", "game_id", "snapshot_type", "rank"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    game_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("games.id", ondelete="CASCADE"), nullable=False)
    game_participant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("game_participants.id", ondelete="CASCADE"),
        nullable=False,
    )
    snapshot_type: Mapped[str] = mapped_column(String(32), nullable=False)
    rank: Mapped[int] = mapped_column(Integer, nullable=False)

    tournament_code: Mapped[str] = mapped_column(String(32), nullable=False)
    display_name: Mapped[str] = mapped_column(String(120), nullable=False)

    available_cash: Mapped[Decimal] = mapped_column(Numeric(18, 4), nullable=False)
    reserved_cash_total: Mapped[Decimal] = mapped_column(Numeric(18, 4), nullable=False)
    long_market_value: Mapped[Decimal] = mapped_column(Numeric(18, 4), nullable=False)
    short_liability: Mapped[Decimal] = mapped_column(Numeric(18, 4), nullable=False)
    unfunded_debt: Mapped[Decimal] = mapped_column(Numeric(18, 4), nullable=False, default=Decimal("0.0000"))

    final_net_worth: Mapped[Decimal] = mapped_column(Numeric(18, 4), nullable=False)
    net_pnl: Mapped[Decimal] = mapped_column(Numeric(18, 4), nullable=False)
    return_pct: Mapped[Decimal] = mapped_column(Numeric(10, 4), nullable=False)
    realized_pnl: Mapped[Decimal] = mapped_column(Numeric(18, 4), nullable=False)
    achieved_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    is_immutable: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    captured_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utcnow)
