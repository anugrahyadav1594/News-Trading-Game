import uuid
from datetime import datetime
from decimal import Decimal
from pydantic import BaseModel, Field


class CreateGameRequest(BaseModel):
    name: str = Field(min_length=3, max_length=160)
    code: str | None = Field(default=None, max_length=32)
    trading_duration_sec: int = Field(default=2700, ge=30, le=14400)
    settlement_duration_sec: int = Field(default=300, ge=15, le=3600)
    scheduled_start_at: datetime | None = None

    initial_cash: Decimal = Field(default=Decimal("500000.0000"), gt=Decimal("0"))
    default_opening_price: Decimal = Field(default=Decimal("1000.0000"), gt=Decimal("0"))
    default_shares_per_stock: int = Field(default=100, ge=0, le=100000)

    initial_margin_ratio: Decimal = Field(default=Decimal("0.5000"), gt=Decimal("0.05"), le=Decimal("2.0"))
    maintenance_margin_ratio: Decimal = Field(default=Decimal("0.2500"), gt=Decimal("0.02"), le=Decimal("1.5"))
    critical_margin_ratio: Decimal = Field(default=Decimal("0.1250"), gt=Decimal("0.01"), le=Decimal("1.0"))
    margin_call_grace_sec: int = Field(default=60, ge=5, le=600)

    default_short_pool_shares: int = Field(default=15000, ge=0, le=10000000)
    short_position_limit_per_stock: int = Field(default=500, ge=0, le=1000000)
    allow_simultaneous_long_short: bool = False

    market_order_collar_pct: Decimal = Field(default=Decimal("0.1000"), gt=Decimal("0.01"), le=Decimal("0.50"))
    settlement_vwap_window_sec: int = Field(default=300, ge=10, le=2700)
    settlement_liquidity_pivot_shares: int = Field(default=500, ge=1, le=1000000)
    settlement_collar_pct: Decimal = Field(default=Decimal("0.1500"), gt=Decimal("0.01"), le=Decimal("0.50"))
    transaction_fee_bps: Decimal = Field(default=Decimal("0.0000"), ge=Decimal("0"), le=Decimal("100"))


class UpdateGameConfigRequest(BaseModel):
    name: str | None = None
    trading_duration_sec: int | None = Field(default=None, ge=30, le=14400)
    settlement_duration_sec: int | None = Field(default=None, ge=15, le=3600)
    initial_cash: Decimal | None = Field(default=None, gt=Decimal("0"))
    default_opening_price: Decimal | None = Field(default=None, gt=Decimal("0"))
    default_shares_per_stock: int | None = Field(default=None, ge=0)
    initial_margin_ratio: Decimal | None = Field(default=None, gt=Decimal("0.05"))
    maintenance_margin_ratio: Decimal | None = Field(default=None, gt=Decimal("0.02"))
    critical_margin_ratio: Decimal | None = Field(default=None, gt=Decimal("0.01"))
    margin_call_grace_sec: int | None = Field(default=None, ge=5)
    default_short_pool_shares: int | None = Field(default=None, ge=0)
    short_position_limit_per_stock: int | None = Field(default=None, ge=0)
    allow_simultaneous_long_short: bool | None = None
    market_order_collar_pct: Decimal | None = None
    settlement_vwap_window_sec: int | None = None
    settlement_liquidity_pivot_shares: int | None = None
    settlement_collar_pct: Decimal | None = None
    transaction_fee_bps: Decimal | None = None


class BulkParticipantImportItem(BaseModel):
    email: str
    username: str
    password: str = "MttPlayer@2026!"
    display_name: str
    institution: str | None = None


class BulkParticipantImportRequest(BaseModel):
    participants: list[BulkParticipantImportItem] = Field(min_length=1, max_length=1200)


class ClockStateSnapshot(BaseModel):
    game_id: uuid.UUID
    status: str
    server_ts: datetime
    trading_elapsed_ms: int
    trading_remaining_ms: int
    settlement_elapsed_ms: int
    settlement_remaining_ms: int
    phase_remaining_ms: int
    is_paused: bool
    news_halted: bool
