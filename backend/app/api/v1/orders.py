import uuid
from decimal import Decimal
from typing import Any
from fastapi import APIRouter, Depends, Query
from sqlalchemy import desc, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import (
    enforce_order_rate_limit,
    get_active_participant_seat,
    get_idempotency_key,
)
from app.core.decimal_utils import to_dec
from app.db.session import atomic_tx, get_db_session
from app.models.enums import GameStatus
from app.models.game import Game, GameParticipant
from app.models.ledger import CashLedgerEntry, ShareLedgerEntry
from app.models.market import MarketReferencePrice
from app.models.order import Order, OrderExecution
from app.models.portfolio import PlayerStockHolding
from app.models.shorting import ShortPosition
from app.models.stock import Stock
from app.modules.accounting.service import compute_participant_valuation
from app.modules.matching.schemas import (
    ModifyOrderRequest,
    OrderResponse,
    PlaceOrderRequest,
)
from app.modules.matching.service import (
    cancel_order,
    modify_order_cancel_replace,
    place_order,
    serialize_order,
)
from app.modules.realtime.hub import ws_hub
from app.modules.shorting.service import compute_short_position_metrics
from app.modules.tournament.service import compute_clock_state

router = APIRouter(prefix="/games/{game_id}", tags=["orders & portfolio"])


async def _notify_after_order_change(
    session: AsyncSession,
    *,
    game_id: uuid.UUID,
    submitter_pid: uuid.UUID,
    symbol: str,
    order_resp: OrderResponse,
    trades: list,
    affected_pids: set[uuid.UUID],
) -> None:
    game = (await session.execute(select(Game).where(Game.id == game_id))).scalar_one()
    clock = compute_clock_state(game)
    ws_hub.mark_stock_dirty(game_id, symbol)

    await ws_hub.send_private_to_participant(
        game_id=game_id,
        game_participant_id=submitter_pid,
        event="ORDER_UPDATED",
        phase=game.status,
        game_elapsed_ms=clock.trading_elapsed_ms,
        payload={"order": order_resp.model_dump(mode="json")},
    )

    for tr in trades:
        await ws_hub.broadcast_public(
            game_id=game_id,
            channel=f"public:trades:{symbol}",
            event="TRADE_PRINT",
            phase=game.status,
            game_elapsed_ms=clock.trading_elapsed_ms,
            payload={
                "id": str(tr.id),
                "trade_seq": tr.trade_seq,
                "symbol": symbol,
                "price": str(to_dec(tr.price)),
                "quantity": tr.quantity,
                "notional_value": str(to_dec(tr.notional_value)),
                "aggressor_side": tr.aggressor_side,
                "executed_at": tr.executed_at.isoformat(),
            },
        )

    for pid in affected_pids:
        val = await compute_participant_valuation(
            session,
            game_id=game_id,
            game_participant_id=pid,
            initial_net_worth=game.initial_net_worth,
        )
        await ws_hub.send_private_to_participant(
            game_id=game_id,
            game_participant_id=pid,
            event="PORTFOLIO_SYNC",
            phase=game.status,
            game_elapsed_ms=clock.trading_elapsed_ms,
            payload={
                "available_cash": str(val.available_cash),
                "reserved_cash_total": str(val.reserved_cash_total),
                "long_market_value": str(val.long_market_value),
                "short_liability": str(val.short_liability),
                "net_worth": str(val.net_worth),
                "net_pnl": str(val.net_pnl),
                "return_pct": str(val.return_pct),
            },
        )


@router.post("/orders", response_model=OrderResponse)
async def api_place_order(
    game_id: uuid.UUID,
    req: PlaceOrderRequest,
    seat: GameParticipant = Depends(get_active_participant_seat),
    _rl: None = Depends(enforce_order_rate_limit),
    idem_key: str | None = Depends(get_idempotency_key),
    session: AsyncSession = Depends(get_db_session),
) -> OrderResponse:
    async with atomic_tx(session):
        order_resp, trades, affected = await place_order(
            session,
            game_id=game_id,
            game_participant_id=seat.id,
            req=req,
            idempotency_key=idem_key,
        )
    async with atomic_tx(session):
        affected_set = set(affected) | {seat.id}
        await _notify_after_order_change(
            session,
            game_id=game_id,
            submitter_pid=seat.id,
            symbol=order_resp.symbol,
            order_resp=order_resp,
            trades=trades,
            affected_pids=affected_set,
        )
    return order_resp


@router.put("/orders/{order_id}", response_model=OrderResponse)
async def api_modify_order(
    game_id: uuid.UUID,
    order_id: uuid.UUID,
    req: ModifyOrderRequest,
    seat: GameParticipant = Depends(get_active_participant_seat),
    _rl: None = Depends(enforce_order_rate_limit),
    idem_key: str | None = Depends(get_idempotency_key),
    session: AsyncSession = Depends(get_db_session),
) -> OrderResponse:
    async with atomic_tx(session):
        order_resp, trades, affected = await modify_order_cancel_replace(
            session,
            game_id=game_id,
            order_id=order_id,
            game_participant_id=seat.id,
            req=req,
            idempotency_key=idem_key,
        )
    async with atomic_tx(session):
        await _notify_after_order_change(
            session,
            game_id=game_id,
            submitter_pid=seat.id,
            symbol=order_resp.symbol,
            order_resp=order_resp,
            trades=trades,
            affected_pids=set(affected) | {seat.id},
        )
    return order_resp


@router.delete("/orders/{order_id}", response_model=OrderResponse)
async def api_cancel_order(
    game_id: uuid.UUID,
    order_id: uuid.UUID,
    seat: GameParticipant = Depends(get_active_participant_seat),
    session: AsyncSession = Depends(get_db_session),
) -> OrderResponse:
    async with atomic_tx(session):
        order_resp = await cancel_order(
            session,
            game_id=game_id,
            order_id=order_id,
            actor_participant_id=seat.id,
            reason="USER_CANCELLED",
        )
    async with atomic_tx(session):
        await _notify_after_order_change(
            session,
            game_id=game_id,
            submitter_pid=seat.id,
            symbol=order_resp.symbol,
            order_resp=order_resp,
            trades=[],
            affected_pids={seat.id},
        )
    return order_resp


@router.get("/orders", response_model=list[OrderResponse])
async def api_list_my_orders(
    game_id: uuid.UUID,
    status: str | None = Query(default=None),
    limit: int = Query(default=100, ge=1, le=500),
    seat: GameParticipant = Depends(get_active_participant_seat),
    session: AsyncSession = Depends(get_db_session),
) -> list[OrderResponse]:
    stocks = {
        s.id: s.symbol
        for s in (await session.execute(select(Stock).where(Stock.game_id == game_id))).scalars().all()
    }
    stmt = select(Order).where(Order.game_participant_id == seat.id)
    if status == "ACTIVE":
        stmt = stmt.where(Order.status.in_(["OPEN", "PARTIALLY_FILLED"]))
    elif status:
        stmt = stmt.where(Order.status == status.upper())
    stmt = stmt.order_by(desc(Order.created_at)).limit(limit)
    orders = (await session.execute(stmt)).scalars().all()
    return [serialize_order(o, stocks.get(o.stock_id, "UNKNOWN")) for o in orders]


@router.get("/portfolio")
async def api_my_portfolio(
    game_id: uuid.UUID,
    seat: GameParticipant = Depends(get_active_participant_seat),
    session: AsyncSession = Depends(get_db_session),
) -> dict[str, Any]:
    game = (await session.execute(select(Game).where(Game.id == game_id))).scalar_one()
    use_final = game.status == GameStatus.COMPLETED.value
    val = await compute_participant_valuation(
        session,
        game_id=game_id,
        game_participant_id=seat.id,
        initial_net_worth=game.initial_net_worth,
        use_final_settlement_price=use_final,
    )

    rows = (
        await session.execute(
            select(Stock, MarketReferencePrice, PlayerStockHolding, ShortPosition)
            .join(MarketReferencePrice, MarketReferencePrice.stock_id == Stock.id)
            .join(
                PlayerStockHolding,
                (PlayerStockHolding.stock_id == Stock.id)
                & (PlayerStockHolding.game_participant_id == seat.id),
            )
            .join(
                ShortPosition,
                (ShortPosition.stock_id == Stock.id)
                & (ShortPosition.game_participant_id == seat.id),
            )
            .where(Stock.game_id == game_id)
            .order_by(Stock.symbol)
        )
    ).all()

    long_holdings = []
    short_positions = []
    for st, ref, h, sp in rows:
        mark_px = (
            to_dec(ref.final_settlement_price)
            if (use_final and ref.final_settlement_price is not None)
            else to_dec(ref.official_mtm_price)
        )
        total_l = h.available_shares + h.reserved_shares
        mkt_val = to_dec(mark_px * Decimal(total_l))
        unrl = to_dec((mark_px - h.avg_entry_price) * Decimal(total_l))
        long_holdings.append(
            {
                "symbol": st.symbol,
                "company_name": st.company_name,
                "available_shares": h.available_shares,
                "reserved_shares": h.reserved_shares,
                "total_shares": total_l,
                "avg_entry_price": str(to_dec(h.avg_entry_price)),
                "mark_price": str(mark_px),
                "market_value": str(mkt_val),
                "unrealized_pnl": str(unrl),
                "realized_pnl": str(to_dec(h.realized_pnl)),
            }
        )
        short_info = compute_short_position_metrics(sp, mark_px, game.maintenance_margin_ratio)
        short_info["symbol"] = st.symbol
        short_info["company_name"] = st.company_name
        short_positions.append(short_info)

    return {
        "game_participant_id": str(seat.id),
        "available_cash": str(val.available_cash),
        "order_reserved_cash": str(val.order_reserved_cash),
        "short_margin_locked": str(val.short_margin_locked),
        "short_proceeds_locked": str(val.short_proceeds_locked),
        "reserved_cash_total": str(val.reserved_cash_total),
        "unfunded_settlement_debt": str(val.unfunded_settlement_debt),
        "long_market_value": str(val.long_market_value),
        "short_liability": str(val.short_liability),
        "realized_pnl": str(val.realized_pnl),
        "unrealized_long_pnl": str(val.unrealized_long_pnl),
        "unrealized_short_pnl": str(val.unrealized_short_pnl),
        "unrealized_pnl_total": str(val.unrealized_pnl_total),
        "net_worth": str(val.net_worth),
        "initial_net_worth": str(to_dec(game.initial_net_worth)),
        "net_pnl": str(val.net_pnl),
        "return_pct": str(val.return_pct),
        "long_holdings": long_holdings,
        "short_positions": short_positions,
    }


@router.get("/trades")
async def api_my_trade_history(
    game_id: uuid.UUID,
    limit: int = Query(default=200, ge=1, le=1000),
    seat: GameParticipant = Depends(get_active_participant_seat),
    session: AsyncSession = Depends(get_db_session),
) -> list[dict[str, Any]]:
    rows = (
        await session.execute(
            select(OrderExecution, Stock.symbol)
            .join(Stock, Stock.id == OrderExecution.stock_id)
            .where(OrderExecution.game_participant_id == seat.id)
            .order_by(desc(OrderExecution.executed_at))
            .limit(limit)
        )
    ).all()
    return [
        {
            "id": str(ex.id),
            "order_id": str(ex.order_id) if ex.order_id else None,
            "trade_id": str(ex.trade_id) if ex.trade_id else None,
            "symbol": sym,
            "execution_kind": ex.execution_kind,
            "intent": ex.intent,
            "side": ex.side,
            "quantity": ex.quantity,
            "price": str(to_dec(ex.price)),
            "gross_amount": str(to_dec(ex.gross_amount)),
            "fee_amount": str(to_dec(ex.fee_amount)),
            "realized_pnl_delta": str(to_dec(ex.realized_pnl_delta)),
            "counterparty_code": ex.counterparty_code,
            "status": "SETTLED",
            "executed_at": ex.executed_at.isoformat(),
        }
        for ex, sym in rows
    ]


@router.get("/ledgers")
async def api_my_ledgers(
    game_id: uuid.UUID,
    ledger_type: str = Query(default="cash", description="cash | share"),
    limit: int = Query(default=150, ge=1, le=500),
    seat: GameParticipant = Depends(get_active_participant_seat),
    session: AsyncSession = Depends(get_db_session),
) -> list[dict[str, Any]]:
    if ledger_type.lower() == "share":
        rows = (
            await session.execute(
                select(ShareLedgerEntry, Stock.symbol)
                .join(Stock, Stock.id == ShareLedgerEntry.stock_id)
                .where(ShareLedgerEntry.game_participant_id == seat.id)
                .order_by(desc(ShareLedgerEntry.id))
                .limit(limit)
            )
        ).all()
        return [
            {
                "id": r.id,
                "symbol": sym,
                "entry_type": r.entry_type,
                "delta_long_available": r.delta_long_available,
                "delta_long_reserved": r.delta_long_reserved,
                "delta_short_borrowed": r.delta_short_borrowed,
                "long_available_after": r.long_available_after,
                "long_reserved_after": r.long_reserved_after,
                "short_borrowed_after": r.short_borrowed_after,
                "reference_type": r.reference_type,
                "created_at": r.created_at.isoformat(),
            }
            for r, sym in rows
        ]

    c_rows = (
        await session.execute(
            select(CashLedgerEntry)
            .where(CashLedgerEntry.game_participant_id == seat.id)
            .order_by(desc(CashLedgerEntry.id))
            .limit(limit)
        )
    ).scalars().all()
    return [
        {
            "id": r.id,
            "entry_type": r.entry_type,
            "delta_available": str(to_dec(r.delta_available)),
            "delta_order_reserved": str(to_dec(r.delta_order_reserved)),
            "delta_short_margin": str(to_dec(r.delta_short_margin)),
            "delta_short_proceeds": str(to_dec(r.delta_short_proceeds)),
            "delta_unfunded_debt": str(to_dec(r.delta_unfunded_debt)),
            "balance_available_after": str(to_dec(r.balance_available_after)),
            "balance_total_cash_after": str(to_dec(r.balance_total_cash_after)),
            "notes": r.notes,
            "created_at": r.created_at.isoformat(),
        }
        for r in c_rows
    ]
