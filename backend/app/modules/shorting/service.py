import uuid
from datetime import datetime, timezone
from decimal import Decimal
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.decimal_utils import HUNDRED, ZERO, to_dec
from app.models.enums import MarginStatus, OrderIntent, OrderPriceType, OrderStatus
from app.models.game import Game
from app.models.market import MarketReferencePrice
from app.models.order import Order
from app.models.shorting import MarginRecord, ShortPosition
from app.models.stock import Stock
from app.modules.matching.schemas import PlaceOrderRequest
from app.modules.matching.service import cancel_order, place_order


def compute_short_position_metrics(
    short_pos: ShortPosition,
    mark_price: Decimal,
    maintenance_ratio: Decimal,
) -> dict:
    """
    Compute exact short-position accounting metrics (Section 6):
      - borrowed_shares
      - opening_price
      - current_market_price
      - sale_proceeds
      - margin_collateral
      - current_liability = borrowed_shares * mark_price
      - unrealized_pnl = sale_proceeds - current_liability
      - position_equity = sale_proceeds + margin_collateral - current_liability
      - margin_ratio = position_equity / current_liability
      - required_maintenance_collateral = current_liability * maintenance_ratio
    """
    qty = short_pos.borrowed_shares
    px = to_dec(mark_price)
    if qty <= 0:
        return {
            "borrowed_shares": 0,
            "pending_cover_shares": 0,
            "opening_price": str(ZERO),
            "current_market_price": str(px),
            "sale_proceeds": str(ZERO),
            "margin_collateral": str(ZERO),
            "current_liability": str(ZERO),
            "unrealized_pnl": str(ZERO),
            "realized_pnl": str(to_dec(short_pos.realized_pnl)),
            "position_equity": str(ZERO),
            "required_maintenance_collateral": str(ZERO),
            "margin_ratio": None,
            "margin_ratio_pct": None,
            "margin_status": MarginStatus.HEALTHY.value,
        }

    proceeds = to_dec(short_pos.sale_proceeds_locked)
    collat = to_dec(short_pos.margin_collateral_locked)
    liability = to_dec(px * Decimal(qty))
    unrealized = to_dec(proceeds - liability)
    equity = to_dec(proceeds + collat - liability)
    req_maint = to_dec(liability * to_dec(maintenance_ratio))
    ratio = to_dec(equity / liability) if liability > ZERO else ZERO
    ratio_pct = to_dec(ratio * HUNDRED)

    return {
        "borrowed_shares": qty,
        "pending_cover_shares": short_pos.pending_cover_shares,
        "opening_price": str(to_dec(short_pos.weighted_avg_open_price)),
        "current_market_price": str(px),
        "sale_proceeds": str(proceeds),
        "margin_collateral": str(collat),
        "current_liability": str(liability),
        "unrealized_pnl": str(unrealized),
        "realized_pnl": str(to_dec(short_pos.realized_pnl)),
        "position_equity": str(equity),
        "required_maintenance_collateral": str(req_maint),
        "margin_ratio": str(ratio),
        "margin_ratio_pct": str(ratio_pct),
        "margin_status": short_pos.margin_status,
    }


async def evaluate_and_enforce_margins(
    session: AsyncSession,
    game_id: uuid.UUID,
    *,
    now: datetime | None = None,
) -> list[dict]:
    """
    Evaluate all open short positions in a game against current Official MTM prices:
      1. Issues MARGIN_CALL when actual margin ratio < maintenance_margin_ratio.
      2. Resolves MARGIN_CALL back to HEALTHY if price recovers or participant covers.
      3. Triggers FORCED_LIQUIDATION (cancels open margin-consuming orders & submits
         priority P2P BUY_TO_COVER market order) when:
         - margin_ratio <= critical_margin_ratio, OR
         - MARGIN_CALL has persisted longer than game.margin_call_grace_sec.
    """
    ts = now or datetime.now(timezone.utc)
    game = (await session.execute(select(Game).where(Game.id == game_id))).scalar_one()
    maint_req = to_dec(game.maintenance_margin_ratio)
    crit_req = to_dec(game.critical_margin_ratio)
    warn_band = to_dec(maint_req * Decimal("1.20"))

    stocks = {
        s.id: s
        for s in (await session.execute(select(Stock).where(Stock.game_id == game_id))).scalars().all()
    }
    refs = {
        r.stock_id: r
        for r in (
            await session.execute(select(MarketReferencePrice).where(MarketReferencePrice.game_id == game_id))
        ).scalars().all()
    }

    open_shorts = (
        await session.execute(
            select(ShortPosition).where(
                ShortPosition.game_id == game_id,
                ShortPosition.borrowed_shares > 0,
            )
        )
    ).scalars().all()

    events_emitted: list[dict] = []

    for sp in open_shorts:
        ref = refs.get(sp.stock_id)
        stock = stocks.get(sp.stock_id)
        if ref is None or stock is None:
            continue

        mark_px = to_dec(ref.official_mtm_price)
        liability = to_dec(mark_px * Decimal(sp.borrowed_shares))
        if liability <= ZERO:
            continue
        equity = to_dec(sp.sale_proceeds_locked + sp.margin_collateral_locked - liability)
        ratio = to_dec(equity / liability)

        should_liquidate = False
        if ratio < maint_req:
            if sp.margin_call_triggered_at is None:
                sp.margin_call_triggered_at = ts
                sp.margin_status = MarginStatus.MARGIN_CALL.value
                session.add(
                    MarginRecord(
                        game_id=game_id,
                        game_participant_id=sp.game_participant_id,
                        stock_id=sp.stock_id,
                        short_position_id=sp.id,
                        mark_price=mark_px,
                        current_liability=liability,
                        position_equity=equity,
                        margin_ratio_actual=ratio,
                        maintenance_ratio_req=maint_req,
                        event_type="MARGIN_CALL_ISSUED",
                        notes=f"Margin ratio {ratio} fell below maintenance {maint_req}",
                    )
                )
                events_emitted.append(
                    {
                        "type": "MARGIN_CALL",
                        "game_participant_id": sp.game_participant_id,
                        "symbol": stock.symbol,
                        "margin_ratio": str(ratio),
                        "maintenance_ratio": str(maint_req),
                        "grace_sec": game.margin_call_grace_sec,
                    }
                )

            elapsed_grace = (ts - sp.margin_call_triggered_at).total_seconds()
            if ratio <= crit_req or elapsed_grace >= game.margin_call_grace_sec:
                should_liquidate = True
        elif ratio < warn_band:
            if sp.margin_status == MarginStatus.MARGIN_CALL.value:
                sp.margin_call_triggered_at = None
            sp.margin_status = MarginStatus.WARNING.value
        else:
            if sp.margin_status in (MarginStatus.MARGIN_CALL.value, MarginStatus.LIQUIDATING.value):
                session.add(
                    MarginRecord(
                        game_id=game_id,
                        game_participant_id=sp.game_participant_id,
                        stock_id=sp.stock_id,
                        short_position_id=sp.id,
                        mark_price=mark_px,
                        current_liability=liability,
                        position_equity=equity,
                        margin_ratio_actual=ratio,
                        maintenance_ratio_req=maint_req,
                        event_type="MARGIN_CALL_RESOLVED",
                    )
                )
            sp.margin_status = MarginStatus.HEALTHY.value
            sp.margin_call_triggered_at = None

        if should_liquidate and stock.trading_enabled:
            sp.margin_status = MarginStatus.LIQUIDATING.value
            session.add(
                MarginRecord(
                    game_id=game_id,
                    game_participant_id=sp.game_participant_id,
                    stock_id=sp.stock_id,
                    short_position_id=sp.id,
                    mark_price=mark_px,
                    current_liability=liability,
                    position_equity=equity,
                    margin_ratio_actual=ratio,
                    maintenance_ratio_req=maint_req,
                    event_type="FORCED_LIQUIDATION_TRIGGERED",
                    notes="Breached critical margin or exceeded margin call grace window.",
                )
            )
            await session.flush()

            # Cancel open orders of this participant to free cash & pending cover locks
            open_ords = (
                await session.execute(
                    select(Order.id).where(
                        Order.game_id == game_id,
                        Order.game_participant_id == sp.game_participant_id,
                        Order.status.in_([OrderStatus.OPEN.value, OrderStatus.PARTIALLY_FILLED.value]),
                    )
                )
            ).scalars().all()
            for oid in open_ords:
                await cancel_order(
                    session,
                    game_id=game_id,
                    order_id=oid,
                    is_admin_or_system=True,
                    reason="MARGIN_FORCED_LIQUIDATION_CLEANUP",
                )

            # Refresh sp after cancellations
            await session.refresh(sp)
            uncovered = sp.borrowed_shares - sp.pending_cover_shares
            if uncovered > 0:
                liq_resp, liq_trades, _ = await place_order(
                    session,
                    game_id=game_id,
                    game_participant_id=sp.game_participant_id,
                    req=PlaceOrderRequest(
                        symbol=stock.symbol,
                        intent=OrderIntent.BUY_TO_COVER.value,
                        price_type=OrderPriceType.MARKET.value,
                        quantity=uncovered,
                        client_order_id=f"forced-liq:{sp.id}:{int(ts.timestamp() * 1000)}:{uuid.uuid4().hex[:6]}",
                    ),
                    is_forced_liquidation=True,
                )
                events_emitted.append(
                    {
                        "type": "FORCED_LIQUIDATION",
                        "game_participant_id": sp.game_participant_id,
                        "symbol": stock.symbol,
                        "requested_cover_qty": uncovered,
                        "filled_cover_qty": liq_resp.filled_quantity,
                        "trades_count": len(liq_trades),
                    }
                )

    await session.flush()
    return events_emitted
