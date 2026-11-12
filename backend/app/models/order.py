import uuid
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any
from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Numeric,
    String,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class Order(Base):
    __tablename__ = "orders"
    __table_args__ = (
        UniqueConstraint("game_participant_id", "client_order_id", name="uq_orders_participant_client_id"),
        CheckConstraint("quantity > 0", name="order_qty_positive"),
        CheckConstraint("filled_quantity >= 0", name="order_filled_nonneg"),
        CheckConstraint("remaining_quantity >= 0", name="order_remaining_nonneg"),
        CheckConstraint("filled_quantity + remaining_quantity = quantity", name="order_qty_sum_exact"),
        CheckConstraint("reserved_cash >= 0", name="order_res_cash_nonneg"),
        CheckConstraint("reserved_long_shares >= 0", name="order_res_long_nonneg"),
        CheckConstraint("reserved_borrow_shares >= 0", name="order_res_borrow_nonneg"),
        Index(
            "ix_orders_active_bids",
            "game_id",
            "stock_id",
            "side",
            text("limit_price DESC"),
            "sequence_num",
            postgresql_where=text("status IN ('OPEN', 'PARTIALLY_FILLED')"),
        ),
        Index(
            "ix_orders_active_asks",
            "game_id",
            "stock_id",
            "side",
            "limit_price",
            "sequence_num",
            postgresql_where=text("status IN ('OPEN', 'PARTIALLY_FILLED')"),
        ),
        Index("ix_orders_participant_created", "game_participant_id", "created_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    game_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("games.id", ondelete="CASCADE"), nullable=False)
    game_participant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("game_participants.id", ondelete="CASCADE"),
        nullable=False,
    )
    stock_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("stocks.id", ondelete="CASCADE"), nullable=False)
    client_order_id: Mapped[str] = mapped_column(String(128), nullable=False)
    sequence_num: Mapped[int] = mapped_column(BigInteger, nullable=False)

    intent: Mapped[str] = mapped_column(String(24), nullable=False)
    side: Mapped[str] = mapped_column(String(8), nullable=False)
    price_type: Mapped[str] = mapped_column(String(12), nullable=False)
    time_in_force: Mapped[str] = mapped_column(String(8), nullable=False, default="GTC")

    limit_price: Mapped[Decimal | None] = mapped_column(Numeric(18, 4), nullable=True)
    collar_price: Mapped[Decimal | None] = mapped_column(Numeric(18, 4), nullable=True)

    quantity: Mapped[int] = mapped_column(BigInteger, nullable=False)
    filled_quantity: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    remaining_quantity: Mapped[int] = mapped_column(BigInteger, nullable=False)
    avg_fill_price: Mapped[Decimal | None] = mapped_column(Numeric(18, 4), nullable=True)

    reserved_cash: Mapped[Decimal] = mapped_column(Numeric(18, 4), nullable=False, default=Decimal("0.0000"))
    reserved_short_margin: Mapped[Decimal] = mapped_column(Numeric(18, 4), nullable=False, default=Decimal("0.0000"))
    reserved_long_shares: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    reserved_borrow_shares: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    reserved_cover_shares: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)

    status: Mapped[str] = mapped_column(String(24), nullable=False)
    cancel_reason: Mapped[str | None] = mapped_column(String(160), nullable=True)
    replaces_order_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("orders.id"), nullable=True)
    replaced_by_order_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("orders.id"), nullable=True)
    is_forced_liquidation: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)

    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utcnow, onupdate=utcnow)


class Trade(Base):
    __tablename__ = "trades"
    __table_args__ = (
        CheckConstraint("price > 0", name="trade_price_positive"),
        CheckConstraint("quantity > 0", name="trade_qty_positive"),
        Index("ix_trades_game_stock_ts", "game_id", "stock_id", "executed_at"),
        Index("ix_trades_buyer_ts", "buyer_participant_id", "executed_at"),
        Index("ix_trades_seller_ts", "seller_participant_id", "executed_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    game_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("games.id", ondelete="CASCADE"), nullable=False)
    stock_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("stocks.id", ondelete="CASCADE"), nullable=False)
    trade_seq: Mapped[int] = mapped_column(BigInteger, nullable=False)

    buy_order_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("orders.id"), nullable=False)
    sell_order_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("orders.id"), nullable=False)
    buyer_participant_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("game_participants.id"), nullable=False)
    seller_participant_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("game_participants.id"), nullable=False)
    aggressor_side: Mapped[str] = mapped_column(String(8), nullable=False)

    price: Mapped[Decimal] = mapped_column(Numeric(18, 4), nullable=False)
    quantity: Mapped[int] = mapped_column(BigInteger, nullable=False)
    notional_value: Mapped[Decimal] = mapped_column(Numeric(18, 4), nullable=False)
    executed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utcnow)


class OrderExecution(Base):
    __tablename__ = "order_executions"
    __table_args__ = (Index("ix_order_exec_part_ts", "game_participant_id", "executed_at"),)

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    game_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("games.id", ondelete="CASCADE"), nullable=False)
    stock_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("stocks.id", ondelete="CASCADE"), nullable=False)
    game_participant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("game_participants.id", ondelete="CASCADE"),
        nullable=False,
    )
    order_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("orders.id"), nullable=True)
    trade_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("trades.id"), nullable=True)

    execution_kind: Mapped[str] = mapped_column(String(40), nullable=False)
    intent: Mapped[str] = mapped_column(String(32), nullable=False)
    side: Mapped[str] = mapped_column(String(8), nullable=False)
    price: Mapped[Decimal] = mapped_column(Numeric(18, 4), nullable=False)
    quantity: Mapped[int] = mapped_column(BigInteger, nullable=False)
    gross_amount: Mapped[Decimal] = mapped_column(Numeric(18, 4), nullable=False)
    fee_amount: Mapped[Decimal] = mapped_column(Numeric(18, 4), nullable=False, default=Decimal("0.0000"))
    realized_pnl_delta: Mapped[Decimal] = mapped_column(Numeric(18, 4), nullable=False, default=Decimal("0.0000"))
    counterparty_code: Mapped[str] = mapped_column(String(48), nullable=False)
    executed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utcnow)


class OrderBookSnapshot(Base):
    __tablename__ = "order_book_snapshots"
    __table_args__ = (Index("ix_ob_snapshots_game_stock_ts", "game_id", "stock_id", "captured_at"),)

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    game_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("games.id", ondelete="CASCADE"), nullable=False)
    stock_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("stocks.id", ondelete="CASCADE"), nullable=False)
    bids_json: Mapped[list[Any]] = mapped_column(JSONB, nullable=False, default=list)
    asks_json: Mapped[list[Any]] = mapped_column(JSONB, nullable=False, default=list)
    best_bid: Mapped[Decimal | None] = mapped_column(Numeric(18, 4), nullable=True)
    best_ask: Mapped[Decimal | None] = mapped_column(Numeric(18, 4), nullable=True)
    spread: Mapped[Decimal | None] = mapped_column(Numeric(18, 4), nullable=True)
    captured_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utcnow)
