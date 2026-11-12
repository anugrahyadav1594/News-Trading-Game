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
    String,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.models.enums import MarginStatus


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class BorrowingPoolInventory(Base):
    __tablename__ = "borrowing_pool_inventory"
    __table_args__ = (
        UniqueConstraint("game_id", "stock_id", name="uq_borrowing_pool_game_stock"),
        CheckConstraint("total_pool_shares >= 0", name="pool_total_nonneg"),
        CheckConstraint("available_pool_shares >= 0", name="pool_avail_nonneg"),
        CheckConstraint("reserved_pool_shares >= 0", name="pool_res_nonneg"),
        CheckConstraint("borrowed_shares >= 0", name="pool_borrowed_nonneg"),
        CheckConstraint(
            "available_pool_shares + reserved_pool_shares + borrowed_shares = total_pool_shares",
            name="pool_conservation_exact",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    game_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("games.id", ondelete="CASCADE"), nullable=False)
    stock_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("stocks.id", ondelete="CASCADE"), nullable=False)

    total_pool_shares: Mapped[int] = mapped_column(BigInteger, nullable=False)
    available_pool_shares: Mapped[int] = mapped_column(BigInteger, nullable=False)
    reserved_pool_shares: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    borrowed_shares: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utcnow, onupdate=utcnow)


class ShortPosition(Base):
    __tablename__ = "short_positions"
    __table_args__ = (
        UniqueConstraint("game_participant_id", "stock_id", name="uq_short_positions_part_stock"),
        CheckConstraint("borrowed_shares >= 0", name="short_borrowed_nonneg"),
        CheckConstraint("pending_cover_shares >= 0", name="short_pending_cover_nonneg"),
        CheckConstraint("pending_cover_shares <= borrowed_shares", name="short_cover_le_borrowed"),
        CheckConstraint("sale_proceeds_locked >= 0", name="short_proceeds_nonneg"),
        CheckConstraint("margin_collateral_locked >= 0", name="short_margin_collat_nonneg"),
        Index("ix_short_positions_game_stock", "game_id", "stock_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    game_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("games.id", ondelete="CASCADE"), nullable=False)
    game_participant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("game_participants.id", ondelete="CASCADE"),
        nullable=False,
    )
    stock_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("stocks.id", ondelete="CASCADE"), nullable=False)

    borrowed_shares: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    pending_cover_shares: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    weighted_avg_open_price: Mapped[Decimal] = mapped_column(Numeric(18, 4), nullable=False, default=Decimal("0.0000"))
    sale_proceeds_locked: Mapped[Decimal] = mapped_column(Numeric(18, 4), nullable=False, default=Decimal("0.0000"))
    margin_collateral_locked: Mapped[Decimal] = mapped_column(Numeric(18, 4), nullable=False, default=Decimal("0.0000"))
    realized_pnl: Mapped[Decimal] = mapped_column(Numeric(18, 4), nullable=False, default=Decimal("0.0000"))

    margin_status: Mapped[str] = mapped_column(String(24), nullable=False, default=MarginStatus.HEALTHY.value)
    margin_call_triggered_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utcnow, onupdate=utcnow)


class MarginRecord(Base):
    __tablename__ = "margin_records"
    __table_args__ = (Index("ix_margin_records_game_part_ts", "game_id", "game_participant_id", "created_at"),)

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    game_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("games.id", ondelete="CASCADE"), nullable=False)
    game_participant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("game_participants.id", ondelete="CASCADE"),
        nullable=False,
    )
    stock_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("stocks.id", ondelete="CASCADE"), nullable=False)
    short_position_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("short_positions.id", ondelete="CASCADE"),
        nullable=False,
    )

    mark_price: Mapped[Decimal] = mapped_column(Numeric(18, 4), nullable=False)
    current_liability: Mapped[Decimal] = mapped_column(Numeric(18, 4), nullable=False)
    position_equity: Mapped[Decimal] = mapped_column(Numeric(18, 4), nullable=False)
    margin_ratio_actual: Mapped[Decimal] = mapped_column(Numeric(10, 4), nullable=False)
    maintenance_ratio_req: Mapped[Decimal] = mapped_column(Numeric(8, 4), nullable=False)
    event_type: Mapped[str] = mapped_column(String(40), nullable=False)
    notes: Mapped[str | None] = mapped_column(String(255), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utcnow)
