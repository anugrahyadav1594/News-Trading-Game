import uuid
from datetime import datetime, timezone
from decimal import Decimal
from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Numeric,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class PlayerPortfolio(Base):
    __tablename__ = "player_portfolios"
    __table_args__ = (
        CheckConstraint("available_cash >= 0", name="available_cash_nonneg"),
        CheckConstraint("order_reserved_cash >= 0", name="order_reserved_cash_nonneg"),
        CheckConstraint("short_margin_locked >= 0", name="short_margin_locked_nonneg"),
        CheckConstraint("short_proceeds_locked >= 0", name="short_proceeds_locked_nonneg"),
        CheckConstraint("unfunded_settlement_debt >= 0", name="unfunded_settlement_debt_nonneg"),
        Index("ix_player_portfolios_game_id", "game_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    game_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("games.id", ondelete="CASCADE"), nullable=False)
    game_participant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("game_participants.id", ondelete="CASCADE"),
        unique=True,
        nullable=False,
    )

    available_cash: Mapped[Decimal] = mapped_column(Numeric(18, 4), nullable=False, default=Decimal("0.0000"))
    order_reserved_cash: Mapped[Decimal] = mapped_column(Numeric(18, 4), nullable=False, default=Decimal("0.0000"))
    short_margin_locked: Mapped[Decimal] = mapped_column(Numeric(18, 4), nullable=False, default=Decimal("0.0000"))
    short_proceeds_locked: Mapped[Decimal] = mapped_column(Numeric(18, 4), nullable=False, default=Decimal("0.0000"))
    unfunded_settlement_debt: Mapped[Decimal] = mapped_column(Numeric(18, 4), nullable=False, default=Decimal("0.0000"))

    realized_pnl: Mapped[Decimal] = mapped_column(Numeric(18, 4), nullable=False, default=Decimal("0.0000"))
    last_net_worth: Mapped[Decimal] = mapped_column(Numeric(18, 4), nullable=False, default=Decimal("0.0000"))
    net_worth_achieved_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utcnow)

    version: Mapped[int] = mapped_column(BigInteger, nullable=False, default=1)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utcnow, onupdate=utcnow)


class PlayerStockHolding(Base):
    __tablename__ = "player_stock_holdings"
    __table_args__ = (
        UniqueConstraint("game_participant_id", "stock_id", name="uq_player_stock_holdings_part_stock"),
        CheckConstraint("available_shares >= 0", name="available_shares_nonneg"),
        CheckConstraint("reserved_shares >= 0", name="reserved_shares_nonneg"),
        Index("ix_player_stock_holdings_game_part", "game_id", "game_participant_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    game_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("games.id", ondelete="CASCADE"), nullable=False)
    game_participant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("game_participants.id", ondelete="CASCADE"),
        nullable=False,
    )
    stock_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("stocks.id", ondelete="CASCADE"), nullable=False)

    available_shares: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    reserved_shares: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    avg_entry_price: Mapped[Decimal] = mapped_column(Numeric(18, 4), nullable=False, default=Decimal("1000.0000"))
    realized_pnl: Mapped[Decimal] = mapped_column(Numeric(18, 4), nullable=False, default=Decimal("0.0000"))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utcnow, onupdate=utcnow)
