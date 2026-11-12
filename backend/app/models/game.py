import uuid
from datetime import datetime, timezone
from decimal import Decimal
from sqlalchemy import (
    BigInteger,
    Boolean,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.models.enums import GameStatus


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class Game(Base):
    __tablename__ = "games"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    code: Mapped[str] = mapped_column(String(32), unique=True, nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(160), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default=GameStatus.DRAFT.value, index=True)
    previous_active_phase: Mapped[str | None] = mapped_column(String(32), nullable=True)

    # Phase timing & authoritative clock fields
    trading_duration_sec: Mapped[int] = mapped_column(Integer, nullable=False, default=2700)
    settlement_duration_sec: Mapped[int] = mapped_column(Integer, nullable=False, default=300)
    scheduled_start_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    trading_started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    settlement_started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    paused_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    accumulated_pause_ms: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    settlement_pause_ms: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    news_halted: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)

    # Initial allocation & risk rules (Admin configurable pre-game)
    initial_cash: Mapped[Decimal] = mapped_column(Numeric(18, 4), nullable=False, default=Decimal("500000.0000"))
    default_opening_price: Mapped[Decimal] = mapped_column(Numeric(18, 4), nullable=False, default=Decimal("1000.0000"))
    default_shares_per_stock: Mapped[int] = mapped_column(BigInteger, nullable=False, default=100)
    initial_net_worth: Mapped[Decimal] = mapped_column(Numeric(18, 4), nullable=False, default=Decimal("1000000.0000"))

    initial_margin_ratio: Mapped[Decimal] = mapped_column(Numeric(8, 4), nullable=False, default=Decimal("0.5000"))
    maintenance_margin_ratio: Mapped[Decimal] = mapped_column(Numeric(8, 4), nullable=False, default=Decimal("0.2500"))
    critical_margin_ratio: Mapped[Decimal] = mapped_column(Numeric(8, 4), nullable=False, default=Decimal("0.1250"))
    margin_call_grace_sec: Mapped[int] = mapped_column(Integer, nullable=False, default=60)
    default_short_pool_shares: Mapped[int] = mapped_column(BigInteger, nullable=False, default=15000)
    short_position_limit_per_stock: Mapped[int] = mapped_column(BigInteger, nullable=False, default=500)
    allow_simultaneous_long_short: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)

    # Market & settlement valuation model config
    market_order_collar_pct: Mapped[Decimal] = mapped_column(Numeric(8, 4), nullable=False, default=Decimal("0.1000"))
    settlement_vwap_window_sec: Mapped[int] = mapped_column(Integer, nullable=False, default=300)
    settlement_liquidity_pivot_shares: Mapped[int] = mapped_column(BigInteger, nullable=False, default=500)
    settlement_collar_pct: Mapped[Decimal] = mapped_column(Numeric(8, 4), nullable=False, default=Decimal("0.1500"))
    transaction_fee_bps: Mapped[Decimal] = mapped_column(Numeric(8, 4), nullable=False, default=Decimal("0.0000"))
    max_single_event_log_move: Mapped[Decimal] = mapped_column(Numeric(8, 4), nullable=False, default=Decimal("0.1800"))
    overlap_dampening_eta: Mapped[Decimal] = mapped_column(Numeric(8, 4), nullable=False, default=Decimal("2.5000"))

    created_by_admin_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utcnow, onupdate=utcnow)


class GamePhase(Base):
    __tablename__ = "game_phases"
    __table_args__ = (Index("ix_game_phases_game_entered", "game_id", "entered_at"),)

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    game_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("games.id", ondelete="CASCADE"), nullable=False)
    phase: Mapped[str] = mapped_column(String(32), nullable=False)
    entered_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utcnow)
    exited_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    triggered_by: Mapped[str] = mapped_column(String(32), nullable=False, default="SYSTEM_CLOCK")
    actor_user_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)


class GameParticipant(Base):
    __tablename__ = "game_participants"
    __table_args__ = (
        UniqueConstraint("game_id", "participant_id", name="uq_game_participants_game_participant"),
        UniqueConstraint("game_id", "user_id", name="uq_game_participants_game_user"),
        Index("ix_game_participants_game_id", "game_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    game_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("games.id", ondelete="CASCADE"), nullable=False)
    participant_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("participants.id", ondelete="CASCADE"), nullable=False)
    user_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    allocation_initialized: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    allocation_idempotency_key: Mapped[str] = mapped_column(String(128), unique=True, nullable=False)
    is_disqualified: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    joined_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utcnow)


class InitialAllocation(Base):
    __tablename__ = "initial_allocations"
    __table_args__ = (
        UniqueConstraint("game_participant_id", "allocation_key", name="uq_initial_allocations_participant_key"),
        Index("ix_initial_allocations_game", "game_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    game_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("games.id", ondelete="CASCADE"), nullable=False)
    game_participant_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("game_participants.id", ondelete="CASCADE"), nullable=False)
    stock_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("stocks.id", ondelete="CASCADE"), nullable=True)
    allocation_key: Mapped[str] = mapped_column(String(64), nullable=False)  # "CASH" or stock symbol
    asset_type: Mapped[str] = mapped_column(String(16), nullable=False)
    quantity: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    cash_amount: Mapped[Decimal | None] = mapped_column(Numeric(18, 4), nullable=True)
    valuation_at_open: Mapped[Decimal] = mapped_column(Numeric(18, 4), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utcnow)
