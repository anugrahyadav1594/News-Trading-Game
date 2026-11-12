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
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class Stock(Base):
    __tablename__ = "stocks"
    __table_args__ = (
        UniqueConstraint("game_id", "symbol", name="uq_stocks_game_symbol"),
        Index("ix_stocks_game_id", "game_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    game_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("games.id", ondelete="CASCADE"), nullable=False)
    symbol: Mapped[str] = mapped_column(String(20), nullable=False)
    company_name: Mapped[str] = mapped_column(String(160), nullable=False)
    sector: Mapped[str] = mapped_column(String(100), nullable=False)
    opening_price: Mapped[Decimal] = mapped_column(Numeric(18, 4), nullable=False, default=Decimal("1000.0000"))
    initial_allocation_shares: Mapped[int] = mapped_column(BigInteger, nullable=False, default=100)
    tick_size: Mapped[Decimal] = mapped_column(Numeric(18, 4), nullable=False, default=Decimal("0.0500"))
    lot_size: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    short_limit_per_player: Mapped[int] = mapped_column(BigInteger, nullable=False, default=500)
    trading_enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    halt_reason: Mapped[str | None] = mapped_column(String(255), nullable=True)
    next_order_seq: Mapped[int] = mapped_column(BigInteger, nullable=False, default=1)
    next_trade_seq: Mapped[int] = mapped_column(BigInteger, nullable=False, default=1)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utcnow)

    profile: Mapped["CompanyProfile | None"] = relationship("CompanyProfile", back_populates="stock", uselist=False)


class CompanyProfile(Base):
    __tablename__ = "company_profiles"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    stock_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("stocks.id", ondelete="CASCADE"), unique=True, nullable=False)
    sub_sectors: Mapped[list[str]] = mapped_column(JSONB, nullable=False, default=list)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    factor_exposures: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    competitor_symbols: Mapped[list[str]] = mapped_column(JSONB, nullable=False, default=list)
    supply_chain_links: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    base_volatility: Mapped[Decimal] = mapped_column(Numeric(8, 4), nullable=False, default=Decimal("0.0200"))
    simulated_market_cap_cr: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False, default=Decimal("500000.00"))
    simulated_pe_ratio: Mapped[Decimal] = mapped_column(Numeric(8, 2), nullable=False, default=Decimal("24.00"))

    stock: Mapped["Stock"] = relationship("Stock", back_populates="profile")
