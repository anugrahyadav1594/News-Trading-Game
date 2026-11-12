import math
import uuid
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from sqlalchemy import desc, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.decimal_utils import HUNDRED, ONE, ZERO, round_to_tick, to_dec
from app.models.enums import OrderSide, OrderStatus
from app.models.game import Game
from app.models.market import MarketPriceHistory, MarketReferencePrice
from app.models.news import EventImpactMapping, NewsEvent
from app.models.order import Order, Trade
from app.models.stock import CompanyProfile, Stock

MAX_CUMULATIVE_LOG_SHIFT = Decimal("0.850000")  # Caps extreme single-game price range (~[₹427, ₹2,340])


def _floor_bucket(ts: datetime, interval_sec: int) -> datetime:
    epoch = int(ts.timestamp())
    floored = (epoch // interval_sec) * interval_sec
    return datetime.fromtimestamp(floored, tz=timezone.utc)


def compute_current_ref_price(
    *,
    opening_price: Decimal,
    tick_size: Decimal,
    permanent_log_shift: Decimal,
    transient_impulses: list[dict],
    now: datetime,
) -> tuple[Decimal, list[dict], Decimal]:
    """
    Evaluate P_ref(t) = round_tick(P_0 * exp(X(t))) from permanent log shift
    plus decaying transient impulses, pruning negligible decayed terms.
    Returns (ref_price, active_transients, active_abs_impulse_300s).
    """
    total_log = float(permanent_log_shift)
    active_list: list[dict] = []
    rolling_abs_recent = 0.0

    for item in transient_impulses:
        released_ts = datetime.fromisoformat(item["released_at"])
        dt_sec = max(0.0, (now - released_ts).total_seconds())
        half_life = max(10.0, float(item.get("duration_sec", 300)))
        amp = float(item["transient_log"])
        full_applied = float(item.get("applied_log", amp))
        decayed = amp * math.exp(-math.log(2.0) * dt_sec / half_life)
        if abs(decayed) > 1e-5 or dt_sec <= 300.0:
            total_log += decayed
            active_list.append(item)
        if dt_sec <= 300.0:
            rolling_abs_recent += abs(full_applied)

    max_bound = float(MAX_CUMULATIVE_LOG_SHIFT)
    clamped_log = max(-max_bound, min(max_bound, total_log))
    raw_px = Decimal(str(float(opening_price) * math.exp(clamped_log)))
    ref_px = round_to_tick(raw_px, tick_size)
    return ref_px, active_list, Decimal(str(round(rolling_abs_recent, 6)))


def calculate_event_stock_impacts(
    *,
    game: Game,
    stocks_with_profiles: list[tuple[Stock, CompanyProfile]],
    event: NewsEvent,
) -> list[dict]:
    """
    Deterministically compute direct, indirect, and sector/macro factor exposure
    and raw log-return impulses for all 5 stocks (Section 6.2 & Section 8).
    """
    gamma_max = float(game.max_single_event_log_move)
    severity = float(event.severity)
    credibility = float(event.credibility)
    surprise = float(event.surprise_factor)

    direct_map = {k: float(v) for k, v in (event.direct_weights or {}).items()}
    indirect_map = {k: float(v) for k, v in (event.indirect_weights or {}).items()}
    factor_shocks = {k: float(v) for k, v in (event.factor_shocks or {}).items()}

    results: list[dict] = []
    for stock, profile in stocks_with_profiles:
        d_w = direct_map.get(stock.symbol, 0.0)
        u_w = indirect_map.get(stock.symbol, 0.0)
        exposures = profile.factor_exposures or {}

        macro_dot = 0.0
        for factor_key, shock_val in factor_shocks.items():
            beta = float(exposures.get(factor_key, 0.0))
            macro_dot += beta * shock_val
        macro_dot = max(-1.25, min(1.25, macro_dot))

        combined = (1.0 * d_w) + (0.55 * u_w) + (0.65 * macro_dot)
        combined = max(-1.5, min(1.5, combined))

        raw_log = gamma_max * combined * severity * credibility * surprise
        est_pct = (math.exp(raw_log) - 1.0) * 100.0

        results.append(
            {
                "stock_id": stock.id,
                "symbol": stock.symbol,
                "direct_exposure": Decimal(str(round(d_w, 4))),
                "indirect_exposure": Decimal(str(round(u_w, 4))),
                "macro_sensitivity": Decimal(str(round(macro_dot, 4))),
                "combined_exposure": Decimal(str(round(combined, 4))),
                "raw_log_impulse": Decimal(str(round(raw_log, 6))),
                "estimated_pct_delta": Decimal(str(round(est_pct, 4))),
            }
        )
    return results


async def apply_released_news_to_market(
    session: AsyncSession,
    *,
    game: Game,
    event: NewsEvent,
    now: datetime,
) -> tuple[dict[str, str], dict[str, str]]:
    """
    Apply a newly released NewsEvent to all 5 stocks' MarketReferencePrice rows:
      - Accounts for multi-stage event chains (incremental surprise only)
      - Accounts for event reversals / denials
      - Applies overlapping-event saturation dampening
      - Updates Official MTM & candle records
    Returns (pre_release_ref_prices, post_release_ref_prices).
    """
    stocks = (
        await session.execute(select(Stock).where(Stock.game_id == game.id).order_by(Stock.symbol))
    ).scalars().all()
    mappings = {
        m.stock_id: m
        for m in (
            await session.execute(
                select(EventImpactMapping).where(EventImpactMapping.news_event_id == event.id)
            )
        ).scalars().all()
    }

    pre_prices: dict[str, str] = {}
    post_prices: dict[str, str] = {}
    eta = float(game.overlap_dampening_eta)
    perm_frac = float(event.permanent_fraction)

    for st in stocks:
        ref_row = (
            await session.execute(
                select(MarketReferencePrice)
                .where(MarketReferencePrice.game_id == game.id, MarketReferencePrice.stock_id == st.id)
                .with_for_update()
            )
        ).scalar_one()

        cur_ref, active_trans, recent_abs = compute_current_ref_price(
            opening_price=st.opening_price,
            tick_size=st.tick_size,
            permanent_log_shift=ref_row.permanent_log_shift,
            transient_impulses=list(ref_row.transient_impulses or []),
            now=now,
        )
        pre_prices[st.symbol] = str(cur_ref)

        mapping = mappings.get(st.id)
        raw_r = float(mapping.raw_log_impulse) if mapping else 0.0

        chain_priced = dict(ref_row.chain_priced_impulses or {})
        event_applied = dict(ref_row.event_applied_impulses or {})

        # 1. Event Reversal / Denial handling
        if event.reverses_event_id is not None:
            target_key = str(event.reverses_event_id)
            prev_applied = float(event_applied.get(target_key, 0.0))
            rev_ratio = float(event.reversal_ratio) if float(event.reversal_ratio) > 0 else 1.0
            delta_r = -rev_ratio * prev_applied
        # 2. Multi-stage chain incremental pricing
        elif event.chain_id is not None:
            chain_key = str(event.chain_id)
            already_priced = float(chain_priced.get(chain_key, 0.0))
            # If same sign and larger conviction, apply only unpriced delta; if conflicting/opposite, apply shift
            if already_priced * raw_r > 0 and abs(raw_r) >= abs(already_priced):
                delta_r = raw_r - already_priced
                chain_priced[chain_key] = round(raw_r, 6)
            else:
                delta_r = raw_r
                chain_priced[chain_key] = round(already_priced + raw_r, 6)
        else:
            delta_r = raw_r

        # 3. Overlapping-event saturation dampener (skipped for explicit reversals so reversals restore cleanly)
        if event.reverses_event_id is not None:
            damped_x = delta_r
        else:
            damped_x = delta_r / (1.0 + eta * float(recent_abs))

        perm_delta = damped_x * perm_frac
        trans_delta = damped_x * (1.0 - perm_frac)

        new_perm = float(ref_row.permanent_log_shift) + perm_delta
        max_bound = float(MAX_CUMULATIVE_LOG_SHIFT)
        new_perm = max(-max_bound, min(max_bound, new_perm))

        if abs(damped_x) > 1e-6:
            active_trans.append(
                {
                    "event_id": str(event.id),
                    "released_at": now.isoformat(),
                    "duration_sec": int(event.expected_duration_sec),
                    "transient_log": round(trans_delta, 6),
                    "applied_log": round(damped_x, 6),
                }
            )
            event_applied[str(event.id)] = round(damped_x, 6)

        ref_row.permanent_log_shift = Decimal(str(round(new_perm, 6)))
        ref_row.transient_impulses = active_trans
        ref_row.chain_priced_impulses = chain_priced
        ref_row.event_applied_impulses = event_applied

        if mapping is not None:
            mapping.applied_log_impulse = Decimal(str(round(damped_x, 6)))
            mapping.estimated_pct_delta = Decimal(str(round((math.exp(damped_x) - 1.0) * 100.0, 4)))

        await recompute_stock_market_metrics(session, game=game, stock=st, ref_row=ref_row, now=now)
        post_prices[st.symbol] = str(ref_row.fundamental_ref_price)

    await session.flush()
    return pre_prices, post_prices


async def recompute_stock_market_metrics(
    session: AsyncSession,
    *,
    game: Game,
    stock: Stock,
    ref_row: MarketReferencePrice,
    now: datetime | None = None,
    latest_trade_price: Decimal | None = None,
    latest_trade_qty: int = 0,
) -> MarketReferencePrice:
    """
    Update Fundamental Reference Price, Best Bid/Ask, Trailing Window VWAP,
    Realized Volatility, Official MTM Price, and 5s/60s Candles for a stock.
    """
    ts = now or datetime.now(timezone.utc)

    cur_ref, active_trans, _ = compute_current_ref_price(
        opening_price=stock.opening_price,
        tick_size=stock.tick_size,
        permanent_log_shift=ref_row.permanent_log_shift,
        transient_impulses=list(ref_row.transient_impulses or []),
        now=ts,
    )
    ref_row.fundamental_ref_price = cur_ref
    ref_row.transient_impulses = active_trans

    if latest_trade_price is not None and latest_trade_qty > 0:
        px = to_dec(latest_trade_price)
        ref_row.last_traded_price = px
        ref_row.has_trades = True
        ref_row.total_volume += latest_trade_qty
        ref_row.total_notional = to_dec(ref_row.total_notional + (px * Decimal(latest_trade_qty)))
        if px > ref_row.day_high:
            ref_row.day_high = px
        if px < ref_row.day_low:
            ref_row.day_low = px

    # Query top-of-book Best Bid & Best Ask
    best_bid = (
        await session.execute(
            select(func.max(Order.limit_price)).where(
                Order.game_id == game.id,
                Order.stock_id == stock.id,
                Order.side == OrderSide.BUY.value,
                Order.status.in_([OrderStatus.OPEN.value, OrderStatus.PARTIALLY_FILLED.value]),
            )
        )
    ).scalar_one_or_none()
    best_ask = (
        await session.execute(
            select(func.min(Order.limit_price)).where(
                Order.game_id == game.id,
                Order.stock_id == stock.id,
                Order.side == OrderSide.SELL.value,
                Order.status.in_([OrderStatus.OPEN.value, OrderStatus.PARTIALLY_FILLED.value]),
            )
        )
    ).scalar_one_or_none()
    ref_row.best_bid = to_dec(best_bid) if best_bid is not None else None
    ref_row.best_ask = to_dec(best_ask) if best_ask is not None else None

    # Trailing window VWAP & Official MTM Price (Section 6.3)
    win_start = ts - timedelta(seconds=int(game.settlement_vwap_window_sec))
    vwap_row = (
        await session.execute(
            select(
                func.coalesce(func.sum(Trade.notional_value), ZERO),
                func.coalesce(func.sum(Trade.quantity), 0),
            ).where(
                Trade.game_id == game.id,
                Trade.stock_id == stock.id,
                Trade.executed_at >= win_start,
            )
        )
    ).one()
    win_notional = to_dec(vwap_row[0])
    win_vol = int(vwap_row[1])

    if win_vol > 0:
        vwap_px = to_dec(win_notional / Decimal(win_vol))
        ref_row.rolling_vwap = vwap_px
        collar = to_dec(game.settlement_collar_pct)
        lower_bound = to_dec(cur_ref * (ONE - collar))
        upper_bound = to_dec(cur_ref * (ONE + collar))
        clamped_mkt = max(lower_bound, min(upper_bound, vwap_px))
        pivot = max(1, int(game.settlement_liquidity_pivot_shares))
        lam = Decimal(win_vol) / Decimal(win_vol + pivot)
        raw_mtm = (lam * clamped_mkt) + ((ONE - lam) * cur_ref)
        ref_row.official_mtm_price = round_to_tick(raw_mtm, stock.tick_size)
    else:
        ref_row.rolling_vwap = None
        ref_row.official_mtm_price = cur_ref

    # Rolling Realized Volatility across last 25 trades
    recent_prices = (
        await session.execute(
            select(Trade.price)
            .where(Trade.game_id == game.id, Trade.stock_id == stock.id)
            .order_by(desc(Trade.trade_seq))
            .limit(25)
        )
    ).scalars().all()
    if len(recent_prices) >= 3:
        ordered = [float(p) for p in reversed(recent_prices)]
        log_rets = [math.log(ordered[i] / ordered[i - 1]) for i in range(1, len(ordered)) if ordered[i - 1] > 0]
        if len(log_rets) >= 2:
            mean_r = sum(log_rets) / len(log_rets)
            var_r = sum((r - mean_r) ** 2 for r in log_rets) / (len(log_rets) - 1)
            vol_pct = math.sqrt(var_r) * 100.0
            ref_row.realized_volatility_pct = Decimal(str(round(vol_pct, 4)))

    ref_row.updated_at = ts

    # Upsert 5s and 60s OHLCV + Reference + MTM candles
    candle_px = to_dec(latest_trade_price) if latest_trade_price is not None else ref_row.last_traded_price
    for interval_sec in (5, 60):
        b_start = _floor_bucket(ts, interval_sec)
        candle = (
            await session.execute(
                select(MarketPriceHistory)
                .where(
                    MarketPriceHistory.game_id == game.id,
                    MarketPriceHistory.stock_id == stock.id,
                    MarketPriceHistory.interval_sec == interval_sec,
                    MarketPriceHistory.bucket_start == b_start,
                )
                .with_for_update()
            )
        ).scalar_one_or_none()
        if candle is None:
            session.add(
                MarketPriceHistory(
                    game_id=game.id,
                    stock_id=stock.id,
                    interval_sec=interval_sec,
                    bucket_start=b_start,
                    open_price=candle_px,
                    high_price=candle_px,
                    low_price=candle_px,
                    close_price=candle_px,
                    ref_price_close=ref_row.fundamental_ref_price,
                    mtm_price_close=ref_row.official_mtm_price,
                    volume=latest_trade_qty,
                    trade_count=1 if latest_trade_qty > 0 else 0,
                )
            )
        else:
            if latest_trade_qty > 0:
                if candle.trade_count == 0:
                    candle.open_price = candle_px
                    candle.high_price = candle_px
                    candle.low_price = candle_px
                else:
                    if candle_px > candle.high_price:
                        candle.high_price = candle_px
                    if candle_px < candle.low_price:
                        candle.low_price = candle_px
                candle.close_price = candle_px
                candle.volume += latest_trade_qty
                candle.trade_count += 1
            candle.ref_price_close = ref_row.fundamental_ref_price
            candle.mtm_price_close = ref_row.official_mtm_price

    await session.flush()
    return ref_row
