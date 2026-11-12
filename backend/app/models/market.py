import uuid
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any
from sqlalchemy import (
    BigInteger,
    Boolean,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class MarketReferencePrice(Base):
    __tablename__ = "market_reference_prices"
    __table_args__ = (UniqueConstraint("game_id", "stock_id", name="uq_market_ref_game_stock"),)

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    game_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("games.id", ondelete="CASCADE"), nullable=False)
    stock_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("stocks.id", ondelete="CASCADE"), nullable=False)

    fundamental_ref_price: Mapped[Decimal] = mapped_column(Numeric(18, 4), nullable=False, default=Decimal("1000.0000"))
    permanent_log_shift: Mapped[Decimal] = mapped_column(Numeric(12, 6), nullable=False, default=Decimal("0.000000"))
    transient_impulses: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, nullable=False, default=list)
    chain_priced_impulses: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    event_applied_impulses: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)

    last_traded_price: Mapped[Decimal] = mapped_column(Numeric(18, 4), nullable=False, default=Decimal("1000.0000"))
    has_trades: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    best_bid: Mapped[Decimal | None] = mapped_column(Numeric(18, 4), nullable=True)
    best_ask: Mapped[Decimal | None] = mapped_column(Numeric(18, 4), nullable=True)
    official_mtm_price: Mapped[Decimal] = mapped_column(Numeric(18, 4), nullable=False, default=Decimal("1000.0000"))
    final_settlement_price: Mapped[Decimal | None] = mapped_column(Numeric(18, 4), nullable=True)

    day_high: Mapped[Decimal] = mapped_column(Numeric(18, 4), nullable=False, default=Decimal("1000.0000"))
    day_low: Mapped[Decimal] = mapped_column(Numeric(18, 4), nullable=False, default=Decimal("1000.0000"))
    total_volume: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    total_notional: Mapped[Decimal] = mapped_column(Numeric(20, 4), nullable=False, default=Decimal("0.0000"))
    rolling_vwap: Mapped[Decimal | None] = mapped_column(Numeric(18, 4), nullable=True)
    realized_volatility_pct: Mapped[Decimal] = mapped_column(Numeric(8, 4), nullable=False, default=Decimal("0.0000"))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utcnow, onupdate=utcnow)


class MarketPriceHistory(Base):
    __tablename__ = "market_price_history"
    __table_args__ = (
        UniqueConstraint("game_id", "stock_id", "interval_sec", "bucket_start", name="uq_market_candle_bucket"),
        Index("ix_market_candles_query", "game_id", "stock_id", "interval_sec", "bucket_start"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    game_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("games.id", ondelete="CASCADE"), nullable=False)
    stock_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("stocks.id", ondelete="CASCADE"), nullable=False)
    interval_sec: Mapped[int] = mapped_column(Integer, nullable=False)
    bucket_start: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    open_price: Mapped[Decimal] = mapped_column(Numeric(18, 4), nullable=False)
    high_price: Mapped[Decimal] = mapped_column(Numeric(18, 4), nullable=False)
    low_price: Mapped[Decimal] = mapped_column(Numeric(18, 4), nullable=False)
    close_price: Mapped[Decimal] = mapped_column(Numeric(18, 4), nullable=False)
    ref_price_close: Mapped[Decimal] = mapped_column(Numeric(18, 4), nullable=False)
    mtm_price_close: Mapped[Decimal] = mapped_column(Numeric(18, 4), nullable=False)
    volume: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    trade_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
