import uuid
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any
from sqlalchemy import (
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
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.models.enums import NewsApprovalStatus


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class NewsCategoryRecord(Base):
    __tablename__ = "news_categories"

    code: Mapped[str] = mapped_column(String(64), primary_key=True)
    display_name: Mapped[str] = mapped_column(String(120), nullable=False)
    domain_group: Mapped[str] = mapped_column(String(64), nullable=False)
    default_factors: Mapped[list[str]] = mapped_column(JSONB, nullable=False, default=list)
    is_builtin: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utcnow)


class NewsEvent(Base):
    __tablename__ = "news_events"
    __table_args__ = (
        UniqueConstraint("game_id", "event_code", name="uq_news_events_game_code"),
        Index("ix_news_events_game_status", "game_id", "approval_status"),
        Index("ix_news_events_chain", "game_id", "chain_id", "chain_stage"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    game_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("games.id", ondelete="CASCADE"), nullable=False)
    event_code: Mapped[str] = mapped_column(String(48), nullable=False)
    chain_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    chain_name: Mapped[str | None] = mapped_column(String(140), nullable=True)
    chain_stage: Mapped[int | None] = mapped_column(Integer, nullable=True)
    chain_total_stages: Mapped[int | None] = mapped_column(Integer, nullable=True)
    parent_event_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("news_events.id"), nullable=True)
    reverses_event_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("news_events.id"), nullable=True)

    category: Mapped[str] = mapped_column(String(64), ForeignKey("news_categories.code"), nullable=False)
    news_type: Mapped[str] = mapped_column(String(32), nullable=False)
    headline: Mapped[str] = mapped_column(String(320), nullable=False)
    body: Mapped[str] = mapped_column(Text, nullable=False)

    primary_stock_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("stocks.id"), nullable=True)
    primary_symbol: Mapped[str | None] = mapped_column(String(20), nullable=True)
    secondary_symbols: Mapped[list[str]] = mapped_column(JSONB, nullable=False, default=list)
    affected_sectors: Mapped[list[str]] = mapped_column(JSONB, nullable=False, default=list)
    factor_shocks: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    direct_weights: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    indirect_weights: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)

    direction: Mapped[str] = mapped_column(String(16), nullable=False)
    severity: Mapped[Decimal] = mapped_column(Numeric(6, 4), nullable=False)
    credibility: Mapped[Decimal] = mapped_column(Numeric(6, 4), nullable=False)
    surprise_factor: Mapped[Decimal] = mapped_column(Numeric(6, 4), nullable=False)
    impact_magnitude: Mapped[Decimal] = mapped_column(Numeric(8, 4), nullable=False)
    permanent_fraction: Mapped[Decimal] = mapped_column(Numeric(6, 4), nullable=False, default=Decimal("0.8000"))
    reversal_ratio: Mapped[Decimal] = mapped_column(Numeric(6, 4), nullable=False, default=Decimal("0.0000"))
    expected_duration_sec: Mapped[int] = mapped_column(Integer, nullable=False, default=600)

    approval_status: Mapped[str] = mapped_column(String(24), nullable=False, default=NewsApprovalStatus.GENERATED.value)
    scheduled_game_sec: Mapped[int | None] = mapped_column(Integer, nullable=True)
    released_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    simulation_label: Mapped[str] = mapped_column(
        String(140),
        nullable=False,
        default="MTT TOURNAMENT SIMULATION — FICTIONAL FINANCIAL NEWS",
    )

    created_by_admin_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=True)
    approved_by_admin_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utcnow, onupdate=utcnow)


class EventImpactMapping(Base):
    __tablename__ = "event_impact_mappings"
    __table_args__ = (UniqueConstraint("news_event_id", "stock_id", name="uq_event_impact_event_stock"),)

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    news_event_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("news_events.id", ondelete="CASCADE"), nullable=False)
    stock_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("stocks.id", ondelete="CASCADE"), nullable=False)
    symbol: Mapped[str] = mapped_column(String(20), nullable=False)

    direct_exposure: Mapped[Decimal] = mapped_column(Numeric(8, 4), nullable=False, default=Decimal("0.0000"))
    indirect_exposure: Mapped[Decimal] = mapped_column(Numeric(8, 4), nullable=False, default=Decimal("0.0000"))
    macro_sensitivity: Mapped[Decimal] = mapped_column(Numeric(8, 4), nullable=False, default=Decimal("0.0000"))
    combined_exposure: Mapped[Decimal] = mapped_column(Numeric(8, 4), nullable=False, default=Decimal("0.0000"))
    raw_log_impulse: Mapped[Decimal] = mapped_column(Numeric(10, 6), nullable=False, default=Decimal("0.000000"))
    applied_log_impulse: Mapped[Decimal] = mapped_column(Numeric(10, 6), nullable=False, default=Decimal("0.000000"))
    estimated_pct_delta: Mapped[Decimal] = mapped_column(Numeric(8, 4), nullable=False, default=Decimal("0.0000"))


class NewsRelease(Base):
    __tablename__ = "news_releases"
    __table_args__ = (Index("ix_news_releases_game_ts", "game_id", "released_at"),)

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    game_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("games.id", ondelete="CASCADE"), nullable=False)
    news_event_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("news_events.id", ondelete="CASCADE"), unique=True, nullable=False)
    release_mode: Mapped[str] = mapped_column(String(24), nullable=False, default="IMMEDIATE")
    game_elapsed_sec: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    released_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utcnow)
    released_by_admin_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=True)
    pre_release_ref_prices: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    post_release_ref_prices: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    idempotency_key: Mapped[str] = mapped_column(String(128), unique=True, nullable=False)
