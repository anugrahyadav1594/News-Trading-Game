import uuid
from datetime import datetime
from decimal import Decimal
from pydantic import BaseModel, Field


class PlaceOrderRequest(BaseModel):
    symbol: str = Field(min_length=1, max_length=20)
    intent: str = Field(description="BUY_LONG | SELL_LONG | SHORT_SELL | BUY_TO_COVER")
    price_type: str = Field(description="MARKET | LIMIT")
    quantity: int = Field(gt=0, le=1000000)
    limit_price: Decimal | None = Field(default=None, gt=Decimal("0"))
    time_in_force: str = Field(default="GTC", description="GTC | IOC | GTD")
    expires_in_sec: int | None = Field(default=None, ge=5, le=2700)
    client_order_id: str | None = Field(default=None, max_length=128)


class ModifyOrderRequest(BaseModel):
    quantity: int = Field(gt=0, le=1000000)
    limit_price: Decimal = Field(gt=Decimal("0"))
    client_order_id: str | None = Field(default=None, max_length=128)


class OrderResponse(BaseModel):
    id: uuid.UUID
    game_id: uuid.UUID
    stock_id: uuid.UUID
    symbol: str
    client_order_id: str
    sequence_num: int
    intent: str
    side: str
    price_type: str
    time_in_force: str
    limit_price: Decimal | None
    collar_price: Decimal | None
    quantity: int
    filled_quantity: int
    remaining_quantity: int
    avg_fill_price: Decimal | None
    status: str
    cancel_reason: str | None
    is_forced_liquidation: bool
    expires_at: datetime | None
    created_at: datetime
    updated_at: datetime
