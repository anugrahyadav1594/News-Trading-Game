import uuid
from datetime import datetime
from decimal import Decimal
from typing import Any
from pydantic import BaseModel, Field


class CreateNewsCategoryRequest(BaseModel):
    code: str = Field(min_length=2, max_length=64)
    display_name: str = Field(min_length=2, max_length=120)
    domain_group: str = Field(default="Custom", max_length=64)
    default_factors: list[str] = Field(default_factory=list)


class GenerateNewsBatchRequest(BaseModel):
    count: int = Field(default=30, ge=1, le=120)
    include_chains: bool = True
    seed: int | None = None
    auto_approve: bool = False


class CreateCustomNewsRequest(BaseModel):
    category: str
    news_type: str = Field(default="BREAKING")
    headline: str = Field(min_length=5, max_length=320)
    body: str = Field(min_length=10)
    primary_symbol: str | None = None
    secondary_symbols: list[str] = Field(default_factory=list)
    affected_sectors: list[str] = Field(default_factory=list)
    direction: str = Field(default="POSITIVE")
    severity: Decimal = Field(default=Decimal("0.7000"), ge=Decimal("0"), le=Decimal("1.0"))
    credibility: Decimal = Field(default=Decimal("0.9000"), ge=Decimal("0"), le=Decimal("1.0"))
    surprise_factor: Decimal = Field(default=Decimal("1.0000"), ge=Decimal("0"), le=Decimal("1.5"))
    permanent_fraction: Decimal = Field(default=Decimal("0.8000"), ge=Decimal("0"), le=Decimal("1.0"))
    expected_duration_sec: int = Field(default=600, ge=30, le=3600)
    direct_weights: dict[str, float] = Field(default_factory=dict)
    indirect_weights: dict[str, float] = Field(default_factory=dict)
    factor_shocks: dict[str, float] = Field(default_factory=dict)
    reverses_event_id: uuid.UUID | None = None
    reversal_ratio: Decimal = Field(default=Decimal("0.0000"), ge=Decimal("0"), le=Decimal("1.0"))
    auto_approve: bool = True


class UpdateNewsEventRequest(BaseModel):
    headline: str | None = Field(default=None, max_length=320)
    body: str | None = None
    direction: str | None = None
    severity: Decimal | None = Field(default=None, ge=Decimal("0"), le=Decimal("1.0"))
    credibility: Decimal | None = Field(default=None, ge=Decimal("0"), le=Decimal("1.0"))
    surprise_factor: Decimal | None = Field(default=None, ge=Decimal("0"), le=Decimal("1.5"))
    permanent_fraction: Decimal | None = Field(default=None, ge=Decimal("0"), le=Decimal("1.0"))
    expected_duration_sec: int | None = Field(default=None, ge=30, le=3600)
    direct_weights: dict[str, float] | None = None
    indirect_weights: dict[str, float] | None = None
    factor_shocks: dict[str, float] | None = None


class ApproveNewsRequest(BaseModel):
    approve: bool = True


class ReleaseNewsRequest(BaseModel):
    mode: str = Field(default="IMMEDIATE", description="IMMEDIATE | SCHEDULED")
    scheduled_game_sec: int | None = Field(default=None, ge=0, le=14400)


class CreateReversalEventRequest(BaseModel):
    reversal_ratio: Decimal = Field(default=Decimal("1.0000"), gt=Decimal("0"), le=Decimal("1.0"))
    headline: str | None = None
    body: str | None = None
    release_immediately: bool = False
