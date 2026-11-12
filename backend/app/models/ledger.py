import uuid
from datetime import datetime, timezone
from decimal import Decimal
from sqlalchemy import BigInteger, DateTime, ForeignKey, Index, Numeric, String
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class CashLedgerEntry(Base):
    __tablename__ = "cash_ledger_entries"
    __table_args__ = (
        Index("ix_cash_ledger_part_id", "game_participant_id", "id"),
        Index("ix_cash_ledger_game_ts", "game_id", "created_at"),
        Index("ix_cash_ledger_ref", "reference_type", "reference_id"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    game_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("games.id", ondelete="CASCADE"), nullable=False)
    game_participant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("game_participants.id", ondelete="CASCADE"),
        nullable=False,
    )
    entry_type: Mapped[str] = mapped_column(String(48), nullable=False)

    delta_available: Mapped[Decimal] = mapped_column(Numeric(18, 4), nullable=False, default=Decimal("0.0000"))
    delta_order_reserved: Mapped[Decimal] = mapped_column(Numeric(18, 4), nullable=False, default=Decimal("0.0000"))
    delta_short_margin: Mapped[Decimal] = mapped_column(Numeric(18, 4), nullable=False, default=Decimal("0.0000"))
    delta_short_proceeds: Mapped[Decimal] = mapped_column(Numeric(18, 4), nullable=False, default=Decimal("0.0000"))
    delta_unfunded_debt: Mapped[Decimal] = mapped_column(Numeric(18, 4), nullable=False, default=Decimal("0.0000"))

    balance_available_after: Mapped[Decimal] = mapped_column(Numeric(18, 4), nullable=False)
    balance_total_cash_after: Mapped[Decimal] = mapped_column(Numeric(18, 4), nullable=False)

    reference_type: Mapped[str] = mapped_column(String(32), nullable=False)
    reference_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    idempotency_key: Mapped[str] = mapped_column(String(160), unique=True, nullable=False)
    notes: Mapped[str | None] = mapped_column(String(255), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utcnow)


class ShareLedgerEntry(Base):
    __tablename__ = "share_ledger_entries"
    __table_args__ = (
        Index("ix_share_ledger_part_stock_id", "game_participant_id", "stock_id", "id"),
        Index("ix_share_ledger_game_stock_ts", "game_id", "stock_id", "created_at"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    game_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("games.id", ondelete="CASCADE"), nullable=False)
    game_participant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("game_participants.id", ondelete="CASCADE"),
        nullable=False,
    )
    stock_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("stocks.id", ondelete="CASCADE"), nullable=False)
    entry_type: Mapped[str] = mapped_column(String(48), nullable=False)

    delta_long_available: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    delta_long_reserved: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    delta_short_borrowed: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)

    long_available_after: Mapped[int] = mapped_column(BigInteger, nullable=False)
    long_reserved_after: Mapped[int] = mapped_column(BigInteger, nullable=False)
    short_borrowed_after: Mapped[int] = mapped_column(BigInteger, nullable=False)

    reference_type: Mapped[str] = mapped_column(String(32), nullable=False)
    reference_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    idempotency_key: Mapped[str] = mapped_column(String(160), unique=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utcnow)
