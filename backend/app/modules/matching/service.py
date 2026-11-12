import uuid
from datetime import datetime, timedelta, timezone
from decimal import Decimal, ROUND_DOWN
from sqlalchemy import asc, desc, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.decimal_utils import FOUR_DP, ONE, ZERO, is_valid_tick, round_to_tick, to_dec
from app.core.exceptions import (
    BorrowPoolExhaustedError,
    ForbiddenActionError,
    InsufficientFundsError,
    InsufficientSharesError,
    InvalidGamePhaseError,
    OrderValidationError,
    ResourceNotFoundError,
    ShortPositionLimitError,
    StockHaltedError,
)
from app.db.locks import acquire_stock_matching_lock
from app.models.enums import (
    CashLedgerType,
    ExecutionKind,
    GameStatus,
    MarginStatus,
    OrderIntent,
    OrderPriceType,
    OrderSide,
    OrderStatus,
    ShareLedgerType,
    TimeInForce,
)
from app.models.game import Game, GameParticipant
from app.models.market import MarketReferencePrice
from app.models.order import Order, OrderExecution, Trade
from app.models.portfolio import PlayerPortfolio, PlayerStockHolding
from app.models.shorting import BorrowingPoolInventory, ShortPosition
from app.models.stock import Stock
from app.models.user import Participant
from app.modules.accounting.service import (
    apply_cash_mutation,
    apply_share_mutation,
    compute_participant_valuation,
    lock_portfolios_canonical,
)
from app.modules.matching.schemas import ModifyOrderRequest, OrderResponse, PlaceOrderRequest
from app.modules.pricing.service import recompute_stock_market_metrics


def _floor_4dp(val: Decimal) -> Decimal:
    return val.quantize(FOUR_DP, rounding=ROUND_DOWN)


def _intent_to_side(intent: str) -> str:
    if intent in (OrderIntent.BUY_LONG.value, OrderIntent.BUY_TO_COVER.value):
        return OrderSide.BUY.value
    if intent in (OrderIntent.SELL_LONG.value, OrderIntent.SHORT_SELL.value):
        return OrderSide.SELL.value
    raise OrderValidationError(f"Unsupported order intent '{intent}'.")


def _validate_phase_allows_intent(game: Game, intent: str, *, is_forced_liquidation: bool = False) -> None:
    if game.status == GameStatus.MAIN_TRADING.value:
        return
    if game.status == GameStatus.SHORT_SETTLEMENT.value:
        # Phase B (5-minute settlement): Only closing existing long or short positions is permitted!
        if intent in (OrderIntent.SELL_LONG.value, OrderIntent.BUY_TO_COVER.value):
            return
        raise InvalidGamePhaseError(
            "Settlement Phase active: opening new long or short positions is prohibited; only SELL_LONG and BUY_TO_COVER are allowed."
        )
    if is_forced_liquidation and game.status in (GameStatus.MAIN_TRADING.value, GameStatus.SHORT_SETTLEMENT.value):
        return
    raise InvalidGamePhaseError(f"Trading is not permitted while game is in '{game.status}' phase.")


def serialize_order(order: Order, symbol: str) -> OrderResponse:
    return OrderResponse(
        id=order.id,
        game_id=order.game_id,
        stock_id=order.stock_id,
        symbol=symbol,
        client_order_id=order.client_order_id,
        sequence_num=order.sequence_num,
        intent=order.intent,
        side=order.side,
        price_type=order.price_type,
        time_in_force=order.time_in_force,
        limit_price=order.limit_price,
        collar_price=order.collar_price,
        quantity=order.quantity,
        filled_quantity=order.filled_quantity,
        remaining_quantity=order.remaining_quantity,
        avg_fill_price=order.avg_fill_price,
        status=order.status,
        cancel_reason=order.cancel_reason,
        is_forced_liquidation=order.is_forced_liquidation,
        expires_at=order.expires_at,
        created_at=order.created_at,
        updated_at=order.updated_at,
    )


async def _release_order_reservations(
    session: AsyncSession,
    *,
    order: Order,
    portfolio: PlayerPortfolio,
    holding: PlayerStockHolding,
    short_pos: ShortPosition,
    pool: BorrowingPoolInventory,
    reason_tag: str,
) -> None:
    """Release any remaining cash, long share, borrow pool, or pending-cover reservations on an order."""
    if order.reserved_cash > ZERO:
        amt = to_dec(order.reserved_cash)
        order.reserved_cash = ZERO
        await apply_cash_mutation(
            session,
            portfolio,
            entry_type=CashLedgerType.ORDER_CASH_RELEASE.value,
            reference_type="ORDER",
            reference_id=order.id,
            idempotency_key=f"ord:rel:cash:{order.id}:{reason_tag}",
            delta_available=amt,
            delta_order_reserved=-amt,
            notes=f"Release order cash reservation ({reason_tag})",
        )

    if order.reserved_short_margin > ZERO:
        m_amt = to_dec(order.reserved_short_margin)
        order.reserved_short_margin = ZERO
        await apply_cash_mutation(
            session,
            portfolio,
            entry_type=CashLedgerType.SHORT_MARGIN_RELEASE.value,
            reference_type="ORDER",
            reference_id=order.id,
            idempotency_key=f"ord:rel:smargin:{order.id}:{reason_tag}",
            delta_available=m_amt,
            delta_short_margin=-m_amt,
            notes=f"Release unfilled short margin reservation ({reason_tag})",
        )

    if order.reserved_long_shares > 0:
        qty = order.reserved_long_shares
        order.reserved_long_shares = 0
        await apply_share_mutation(
            session,
            game_id=order.game_id,
            game_participant_id=order.game_participant_id,
            stock_id=order.stock_id,
            holding=holding,
            short_pos=short_pos,
            entry_type=ShareLedgerType.SELL_ORDER_RELEASE.value,
            reference_type="ORDER",
            reference_id=order.id,
            idempotency_key=f"ord:rel:lshare:{order.id}:{reason_tag}",
            delta_long_available=qty,
            delta_long_reserved=-qty,
        )

    if order.reserved_borrow_shares > 0:
        b_qty = order.reserved_borrow_shares
        order.reserved_borrow_shares = 0
        pool.reserved_pool_shares -= b_qty
        pool.available_pool_shares += b_qty

    if order.reserved_cover_shares > 0:
        c_qty = order.reserved_cover_shares
        order.reserved_cover_shares = 0
        short_pos.pending_cover_shares -= c_qty


async def place_order(
    session: AsyncSession,
    *,
    game_id: uuid.UUID,
    game_participant_id: uuid.UUID,
    req: PlaceOrderRequest,
    idempotency_key: str | None = None,
    is_forced_liquidation: bool = False,
) -> tuple[OrderResponse, list[Trade], set[uuid.UUID]]:
    """
    Submit an order into the Central Continuous Double Auction (CDA) order book,
    reserve balances, execute any immediate price-time priority matches at resting prices,
    and update market metrics.
    Returns (order_response, executed_trades, affected_participant_ids).
    """
    client_oid = (idempotency_key or req.client_order_id or str(uuid.uuid4())).strip()

    # 1. Fast Idempotency Check before taking heavy locks
    existing_order = (
        await session.execute(
            select(Order).where(
                Order.game_participant_id == game_participant_id,
                Order.client_order_id == client_oid,
            )
        )
    ).scalar_one_or_none()
    if existing_order is not None:
        st_row = (await session.execute(select(Stock).where(Stock.id == existing_order.stock_id))).scalar_one()
        return serialize_order(existing_order, st_row.symbol), [], set()

    if not isinstance(req.quantity, int) or req.quantity <= 0:
        raise OrderValidationError("Order quantity must be a strictly positive integer.")

    intent = req.intent.upper()
    side = _intent_to_side(intent)
    price_type = req.price_type.upper()
    if price_type not in (OrderPriceType.MARKET.value, OrderPriceType.LIMIT.value):
        raise OrderValidationError(f"Unsupported price_type '{req.price_type}'.")

    tif = req.time_in_force.upper()
    if price_type == OrderPriceType.MARKET.value:
        tif = TimeInForce.IOC.value
    elif tif not in (TimeInForce.GTC.value, TimeInForce.IOC.value, TimeInForce.GTD.value):
        raise OrderValidationError(f"Unsupported time_in_force '{req.time_in_force}'.")

    game = (await session.execute(select(Game).where(Game.id == game_id))).scalar_one_or_none()
    if game is None:
        raise ResourceNotFoundError("Game not found.")
    _validate_phase_allows_intent(game, intent, is_forced_liquidation=is_forced_liquidation)

    gp = (
        await session.execute(
            select(GameParticipant).where(
                GameParticipant.id == game_participant_id,
                GameParticipant.game_id == game_id,
            )
        )
    ).scalar_one_or_none()
    if gp is None or not gp.allocation_initialized or gp.is_disqualified:
        raise ForbiddenActionError("Participant is not active/initialized in this game.")

    symbol_norm = req.symbol.strip().upper()
    stock = (
        await session.execute(
            select(Stock).where(Stock.game_id == game_id, Stock.symbol == symbol_norm)
        )
    ).scalar_one_or_none()
    if stock is None:
        raise ResourceNotFoundError(f"Stock '{symbol_norm}' does not exist in this game.")

    # 2. Acquire per-stock transaction-scoped advisory serialization lock
    await acquire_stock_matching_lock(session, game_id, stock.id)

    # Re-check idempotency inside lock
    existing_inside = (
        await session.execute(
            select(Order).where(
                Order.game_participant_id == game_participant_id,
                Order.client_order_id == client_oid,
            )
        )
    ).scalar_one_or_none()
    if existing_inside is not None:
        return serialize_order(existing_inside, stock.symbol), [], set()

    # Reload stock, ref_row, pool with FOR UPDATE inside per-stock lock
    stock = (await session.execute(select(Stock).where(Stock.id == stock.id).with_for_update())).scalar_one()
    if not stock.trading_enabled:
        raise StockHaltedError(f"Trading in {stock.symbol} is currently halted: {stock.halt_reason or 'Circuit breaker'}")

    ref_row = (
        await session.execute(
            select(MarketReferencePrice)
            .where(MarketReferencePrice.game_id == game_id, MarketReferencePrice.stock_id == stock.id)
            .with_for_update()
        )
    ).scalar_one()
    pool = (
        await session.execute(
            select(BorrowingPoolInventory)
            .where(BorrowingPoolInventory.game_id == game_id, BorrowingPoolInventory.stock_id == stock.id)
            .with_for_update()
        )
    ).scalar_one()

    now = datetime.now(timezone.utc)
    # Expire any stale GTD orders on this stock before matching
    await expire_stale_orders_for_stock(session, game=game, stock=stock, pool=pool, now=now)
    await recompute_stock_market_metrics(session, game=game, stock=stock, ref_row=ref_row, now=now)

    limit_px: Decimal | None = None
    collar_px: Decimal | None = None
    if price_type == OrderPriceType.LIMIT.value:
        if req.limit_price is None:
            raise OrderValidationError("limit_price is required for LIMIT orders.")
        limit_px = to_dec(req.limit_price)
        if not is_valid_tick(limit_px, stock.tick_size):
            raise OrderValidationError(
                f"limit_price {limit_px} must be a positive multiple of tick size {stock.tick_size}."
            )
    else:
        collar = to_dec(game.market_order_collar_pct)
        if side == OrderSide.BUY.value:
            anchor = ref_row.best_ask if ref_row.best_ask is not None else ref_row.fundamental_ref_price
            if is_forced_liquidation:
                collar = max(collar, Decimal("0.2500"))
            collar_px = round_to_tick(anchor * (ONE + collar), stock.tick_size)
        else:
            anchor = ref_row.best_bid if ref_row.best_bid is not None else ref_row.fundamental_ref_price
            collar_px = round_to_tick(anchor * (ONE - collar), stock.tick_size)

    # 3. Lock submitter's portfolio, holding, and short position
    submitter_pf = (
        await session.execute(
            select(PlayerPortfolio)
            .where(PlayerPortfolio.game_participant_id == game_participant_id)
            .with_for_update()
        )
    ).scalar_one()
    submitter_holding = (
        await session.execute(
            select(PlayerStockHolding)
            .where(
                PlayerStockHolding.game_participant_id == game_participant_id,
                PlayerStockHolding.stock_id == stock.id,
            )
            .with_for_update()
        )
    ).scalar_one()
    submitter_short = (
        await session.execute(
            select(ShortPosition)
            .where(
                ShortPosition.game_participant_id == game_participant_id,
                ShortPosition.stock_id == stock.id,
            )
            .with_for_update()
        )
    ).scalar_one()

    fee_rate = to_dec(game.transaction_fee_bps) / Decimal("10000")
    seq_num = stock.next_order_seq
    stock.next_order_seq += 1

    expires_at = now + timedelta(seconds=req.expires_in_sec) if req.expires_in_sec else None
    order = Order(
        game_id=game_id,
        game_participant_id=game_participant_id,
        stock_id=stock.id,
        client_order_id=client_oid,
        sequence_num=seq_num,
        intent=intent,
        side=side,
        price_type=price_type,
        time_in_force=tif,
        limit_price=limit_px,
        collar_price=collar_px,
        quantity=req.quantity,
        filled_quantity=0,
        remaining_quantity=req.quantity,
        status=OrderStatus.OPEN.value,
        is_forced_liquidation=is_forced_liquidation,
        expires_at=expires_at,
    )
    session.add(order)
    await session.flush()

    # 4. Pre-Trade Validation & Balance/Inventory Reservation
    qty = req.quantity
    if intent == OrderIntent.BUY_LONG.value:
        unit_px = limit_px if limit_px is not None else collar_px
        assert unit_px is not None
        req_cash = to_dec(Decimal(qty) * unit_px * (ONE + fee_rate))
        order.reserved_cash = req_cash
        await apply_cash_mutation(
            session,
            submitter_pf,
            entry_type=CashLedgerType.ORDER_CASH_RESERVE.value,
            reference_type="ORDER",
            reference_id=order.id,
            idempotency_key=f"ord:res:cash:{order.id}",
            delta_available=-req_cash,
            delta_order_reserved=req_cash,
            notes=f"Reserve cash for BUY_LONG {qty} {stock.symbol}",
        )

    elif intent == OrderIntent.SELL_LONG.value:
        if submitter_holding.available_shares < qty:
            raise InsufficientSharesError(
                f"Insufficient available {stock.symbol} shares: have {submitter_holding.available_shares}, tried to sell {qty}."
            )
        order.reserved_long_shares = qty
        await apply_share_mutation(
            session,
            game_id=game_id,
            game_participant_id=game_participant_id,
            stock_id=stock.id,
            holding=submitter_holding,
            short_pos=submitter_short,
            entry_type=ShareLedgerType.SELL_ORDER_RESERVE.value,
            reference_type="ORDER",
            reference_id=order.id,
            idempotency_key=f"ord:res:lshare:{order.id}",
            delta_long_available=-qty,
            delta_long_reserved=qty,
        )

    elif intent == OrderIntent.SHORT_SELL.value:
        if not game.allow_simultaneous_long_short:
            if submitter_holding.available_shares + submitter_holding.reserved_shares > 0:
                raise OrderValidationError(
                    f"Simultaneous long and short positions are disabled; sell your existing {stock.symbol} long holdings before shorting."
                )

        pending_short_orders = (
            await session.execute(
                select(Order.reserved_borrow_shares).where(
                    Order.game_participant_id == game_participant_id,
                    Order.stock_id == stock.id,
                    Order.status.in_([OrderStatus.OPEN.value, OrderStatus.PARTIALLY_FILLED.value]),
                    Order.id != order.id,
                )
            )
        ).scalars().all()
        total_player_short = submitter_short.borrowed_shares + sum(pending_short_orders) + qty
        if total_player_short > stock.short_limit_per_player:
            raise ShortPositionLimitError(
                f"Short position limit exceeded for {stock.symbol}: limit is {stock.short_limit_per_player} shares."
            )

        if pool.available_pool_shares < qty:
            raise BorrowPoolExhaustedError(
                f"Central borrowing pool exhausted for {stock.symbol}: {pool.available_pool_shares} shares available, requested {qty}."
            )

        pool.available_pool_shares -= qty
        pool.reserved_pool_shares += qty
        order.reserved_borrow_shares = qty

        best_bid_val = ref_row.best_bid or ZERO
        base_px = limit_px if limit_px is not None else ref_row.fundamental_ref_price
        margin_anchor_px = max(base_px, best_bid_val)
        req_margin = to_dec(Decimal(qty) * margin_anchor_px * to_dec(game.initial_margin_ratio))
        order.reserved_short_margin = req_margin
        await apply_cash_mutation(
            session,
            submitter_pf,
            entry_type=CashLedgerType.SHORT_MARGIN_RESERVE.value,
            reference_type="ORDER",
            reference_id=order.id,
            idempotency_key=f"ord:res:smargin:{order.id}",
            delta_available=-req_margin,
            delta_short_margin=req_margin,
            notes=f"Reserve initial margin for SHORT_SELL {qty} {stock.symbol}",
        )

    elif intent == OrderIntent.BUY_TO_COVER.value:
        coverable = submitter_short.borrowed_shares - submitter_short.pending_cover_shares
        if coverable <= 0 or qty > coverable:
            raise OrderValidationError(
                f"BUY_TO_COVER quantity ({qty}) exceeds open uncovered short shares ({coverable}) in {stock.symbol}."
            )
        submitter_short.pending_cover_shares += qty
        order.reserved_cover_shares = qty

        unit_px = limit_px if limit_px is not None else collar_px
        assert unit_px is not None
        worst_cost = to_dec(Decimal(qty) * unit_px * (ONE + fee_rate))
        b_cur = submitter_short.borrowed_shares
        collat_total = to_dec(submitter_short.sale_proceeds_locked + submitter_short.margin_collateral_locked)
        collat_slice = collat_total if qty == b_cur else _floor_4dp(collat_total * Decimal(qty) / Decimal(b_cur))
        extra_cash = max(ZERO, to_dec(worst_cost - collat_slice))
        if extra_cash > ZERO:
            if is_forced_liquidation and submitter_pf.available_cash < extra_cash:
                # Cap P2P forced cover quantity to maximum cash-solvent shares so P2P cash stays strictly zero-sum;
                # any insolvent residual shares are handled by audited administrative settlement debt accounting.
                per_share_collat = collat_total / Decimal(b_cur)
                per_share_cost = unit_px * (ONE + fee_rate)
                shortfall_per_share = max(Decimal("0.0001"), per_share_cost - per_share_collat)
                affordable_qty = min(qty, int(submitter_pf.available_cash // shortfall_per_share))
                if affordable_qty <= 0:
                    submitter_short.pending_cover_shares -= qty
                    order.reserved_cover_shares = 0
                    order.status = OrderStatus.CANCELLED.value
                    order.cancel_reason = "INSUFFICIENT_SOLVENCY_FOR_P2P_COVER_AWAITING_ADMIN_SETTLEMENT"
                    await session.flush()
                    return serialize_order(order, stock.symbol), [], {game_participant_id}
                diff_qty = qty - affordable_qty
                submitter_short.pending_cover_shares -= diff_qty
                qty = affordable_qty
                order.quantity = qty
                order.remaining_quantity = qty
                order.reserved_cover_shares = qty
                worst_cost = to_dec(Decimal(qty) * unit_px * (ONE + fee_rate))
                collat_slice = collat_total if qty == b_cur else _floor_4dp(collat_total * Decimal(qty) / Decimal(b_cur))
                extra_cash = max(ZERO, to_dec(worst_cost - collat_slice))

            order.reserved_cash = extra_cash
            if extra_cash > ZERO:
                await apply_cash_mutation(
                    session,
                    submitter_pf,
                    entry_type=CashLedgerType.ORDER_CASH_RESERVE.value,
                    reference_type="ORDER",
                    reference_id=order.id,
                    idempotency_key=f"ord:res:covercash:{order.id}",
                    delta_available=-extra_cash,
                    delta_order_reserved=extra_cash,
                    notes=f"Reserve supplemental cash for BUY_TO_COVER {qty} {stock.symbol}",
                )

    # 5. Query opposite-side order book in strict Price-Time Priority
    if side == OrderSide.BUY.value:
        bound_px = limit_px if price_type == OrderPriceType.LIMIT.value else collar_px
        assert bound_px is not None
        book_stmt = (
            select(Order)
            .where(
                Order.game_id == game_id,
                Order.stock_id == stock.id,
                Order.side == OrderSide.SELL.value,
                Order.status.in_([OrderStatus.OPEN.value, OrderStatus.PARTIALLY_FILLED.value]),
                Order.limit_price <= bound_px,
            )
            .order_by(asc(Order.limit_price), asc(Order.sequence_num))
            .with_for_update()
        )
    else:
        bound_px = limit_px if price_type == OrderPriceType.LIMIT.value else collar_px
        assert bound_px is not None
        book_stmt = (
            select(Order)
            .where(
                Order.game_id == game_id,
                Order.stock_id == stock.id,
                Order.side == OrderSide.BUY.value,
                Order.status.in_([OrderStatus.OPEN.value, OrderStatus.PARTIALLY_FILLED.value]),
                Order.limit_price >= bound_px,
            )
            .order_by(desc(Order.limit_price), asc(Order.sequence_num))
            .with_for_update()
        )

    resting_orders = (await session.execute(book_stmt)).scalars().all()

    trades_executed: list[Trade] = []
    affected_participants: set[uuid.UUID] = {game_participant_id}
    fill_notional_accum = ZERO

    # Pre-fetch tournament codes for counterparty execution records
    part_ids_needed = {o.game_participant_id for o in resting_orders} | {game_participant_id}
    tcode_rows = (
        await session.execute(
            select(GameParticipant.id, Participant.tournament_code)
            .join(Participant, Participant.id == GameParticipant.participant_id)
            .where(GameParticipant.id.in_(part_ids_needed))
        )
    ).all()
    tcode_map = {r[0]: r[1] for r in tcode_rows}

    for resting in resting_orders:
        if order.remaining_quantity <= 0:
            break

        # Self-Trade Prevention (STP): cancel own resting order & release its reservations
        if resting.game_participant_id == game_participant_id:
            await _release_order_reservations(
                session,
                order=resting,
                portfolio=submitter_pf,
                holding=submitter_holding,
                short_pos=submitter_short,
                pool=pool,
                reason_tag="stp_cancel",
            )
            resting.status = OrderStatus.CANCELLED.value
            resting.cancel_reason = "SELF_TRADE_PREVENTION"
            resting.updated_at = now
            continue

        fill_qty = min(order.remaining_quantity, resting.remaining_quantity)
        exec_price = to_dec(resting.limit_price)  # Always execute at resting order's price!
        gross_val = to_dec(exec_price * Decimal(fill_qty))

        buy_order = order if side == OrderSide.BUY.value else resting
        sell_order = resting if side == OrderSide.BUY.value else order
        buyer_pid = buy_order.game_participant_id
        seller_pid = sell_order.game_participant_id

        # Canonical lock ordering across buyer and seller portfolios
        locked_pfs = await lock_portfolios_canonical(session, [buyer_pid, seller_pid])
        buyer_pf = locked_pfs[buyer_pid]
        seller_pf = locked_pfs[seller_pid]

        other_pid = resting.game_participant_id
        other_holding = (
            await session.execute(
                select(PlayerStockHolding)
                .where(
                    PlayerStockHolding.game_participant_id == other_pid,
                    PlayerStockHolding.stock_id == stock.id,
                )
                .with_for_update()
            )
        ).scalar_one()
        other_short = (
            await session.execute(
                select(ShortPosition)
                .where(
                    ShortPosition.game_participant_id == other_pid,
                    ShortPosition.stock_id == stock.id,
                )
                .with_for_update()
            )
        ).scalar_one()

        buyer_holding = submitter_holding if side == OrderSide.BUY.value else other_holding
        buyer_short = submitter_short if side == OrderSide.BUY.value else other_short
        seller_holding = other_holding if side == OrderSide.BUY.value else submitter_holding
        seller_short = other_short if side == OrderSide.BUY.value else submitter_short

        #For forced liquidation cover where extra cash might be constrained, ensure solvency check
        buyer_fee = to_dec(gross_val * fee_rate)
        seller_fee = to_dec(gross_val * fee_rate)

        trade_seq = stock.next_trade_seq
        stock.next_trade_seq += 1
        trade = Trade(
            game_id=game_id,
            stock_id=stock.id,
            trade_seq=trade_seq,
            buy_order_id=buy_order.id,
            sell_order_id=sell_order.id,
            buyer_participant_id=buyer_pid,
            seller_participant_id=seller_pid,
            aggressor_side=side,
            price=exec_price,
            quantity=fill_qty,
            notional_value=gross_val,
            executed_at=now,
        )
        session.add(trade)
        await session.flush()

        # --- Settle BUYER leg ---
        buyer_rpnl = ZERO
        if buy_order.intent == OrderIntent.BUY_LONG.value:
            is_last_buy = fill_qty == buy_order.remaining_quantity
            rel_ord_cash = (
                to_dec(buy_order.reserved_cash)
                if is_last_buy
                else _floor_4dp(buy_order.reserved_cash * Decimal(fill_qty) / Decimal(buy_order.remaining_quantity))
            )
            total_buyer_cost = to_dec(gross_val + buyer_fee)
            refund_avail = to_dec(rel_ord_cash - total_buyer_cost)
            buy_order.reserved_cash = to_dec(buy_order.reserved_cash - rel_ord_cash)

            await apply_cash_mutation(
                session,
                buyer_pf,
                entry_type=CashLedgerType.BUY_SETTLEMENT.value,
                reference_type="TRADE",
                reference_id=trade.id,
                idempotency_key=f"trd:buy:cash:{trade.id}",
                delta_available=refund_avail,
                delta_order_reserved=-rel_ord_cash,
                notes=f"BUY_LONG fill {fill_qty} {stock.symbol} @ {exec_price}",
            )

            old_total_qty = buyer_holding.available_shares + buyer_holding.reserved_shares
            new_total_qty = old_total_qty + fill_qty
            buyer_holding.avg_entry_price = to_dec(
                ((buyer_holding.avg_entry_price * Decimal(old_total_qty)) + gross_val) / Decimal(new_total_qty)
            )
            await apply_share_mutation(
                session,
                game_id=game_id,
                game_participant_id=buyer_pid,
                stock_id=stock.id,
                holding=buyer_holding,
                short_pos=buyer_short,
                entry_type=ShareLedgerType.BUY_FILL_CREDIT.value,
                reference_type="TRADE",
                reference_id=trade.id,
                idempotency_key=f"trd:buy:share:{trade.id}",
                delta_long_available=fill_qty,
            )

        elif buy_order.intent == OrderIntent.BUY_TO_COVER.value:
            b_cur = buyer_short.borrowed_shares
            is_full_pos_cover = fill_qty == b_cur
            proc_slice = (
                to_dec(buyer_short.sale_proceeds_locked)
                if is_full_pos_cover
                else _floor_4dp(buyer_short.sale_proceeds_locked * Decimal(fill_qty) / Decimal(b_cur))
            )
            margin_slice = (
                to_dec(buyer_short.margin_collateral_locked)
                if is_full_pos_cover
                else _floor_4dp(buyer_short.margin_collateral_locked * Decimal(fill_qty) / Decimal(b_cur))
            )
            is_last_buy = fill_qty == buy_order.remaining_quantity
            rel_ord_cash = (
                to_dec(buy_order.reserved_cash)
                if is_last_buy
                else _floor_4dp(buy_order.reserved_cash * Decimal(fill_qty) / Decimal(buy_order.remaining_quantity))
            )
            buy_order.reserved_cash = to_dec(buy_order.reserved_cash - rel_ord_cash)
            buy_order.reserved_cover_shares -= fill_qty
            buyer_short.pending_cover_shares -= fill_qty

            total_buyer_cost = to_dec(gross_val + buyer_fee)
            unlocked = to_dec(proc_slice + margin_slice + rel_ord_cash)
            net_to_avail = to_dec(unlocked - total_buyer_cost)
            buyer_rpnl = to_dec(proc_slice - total_buyer_cost)

            buyer_short.sale_proceeds_locked = to_dec(buyer_short.sale_proceeds_locked - proc_slice)
            buyer_short.margin_collateral_locked = to_dec(buyer_short.margin_collateral_locked - margin_slice)
            buyer_short.realized_pnl = to_dec(buyer_short.realized_pnl + buyer_rpnl)

            await apply_cash_mutation(
                session,
                buyer_pf,
                entry_type=CashLedgerType.SHORT_COVER_SETTLEMENT.value,
                reference_type="TRADE",
                reference_id=trade.id,
                idempotency_key=f"trd:cover:cash:{trade.id}",
                delta_available=net_to_avail,
                delta_order_reserved=-rel_ord_cash,
                delta_short_margin=-margin_slice,
                delta_short_proceeds=-proc_slice,
                realized_pnl_delta=buyer_rpnl,
                notes=f"BUY_TO_COVER fill {fill_qty} {stock.symbol} @ {exec_price}",
            )

            await apply_share_mutation(
                session,
                game_id=game_id,
                game_participant_id=buyer_pid,
                stock_id=stock.id,
                holding=buyer_holding,
                short_pos=buyer_short,
                entry_type=ShareLedgerType.SHORT_COVER_RETURN.value,
                reference_type="TRADE",
                reference_id=trade.id,
                idempotency_key=f"trd:cover:share:{trade.id}",
                delta_short_borrowed=-fill_qty,
            )
            if buyer_short.borrowed_shares == 0:
                buyer_short.weighted_avg_open_price = ZERO
                buyer_short.margin_status = MarginStatus.HEALTHY.value
                buyer_short.margin_call_triggered_at = None

            pool.borrowed_shares -= fill_qty
            pool.available_pool_shares += fill_qty

        # --- Settle SELLER leg ---
        seller_rpnl = ZERO
        if sell_order.intent == OrderIntent.SELL_LONG.value:
            net_proceeds = to_dec(gross_val - seller_fee)
            seller_rpnl = to_dec(((exec_price - seller_holding.avg_entry_price) * Decimal(fill_qty)) - seller_fee)
            sell_order.reserved_long_shares -= fill_qty
            seller_holding.realized_pnl = to_dec(seller_holding.realized_pnl + seller_rpnl)

            await apply_cash_mutation(
                session,
                seller_pf,
                entry_type=CashLedgerType.SELL_SETTLEMENT.value,
                reference_type="TRADE",
                reference_id=trade.id,
                idempotency_key=f"trd:sell:cash:{trade.id}",
                delta_available=net_proceeds,
                realized_pnl_delta=seller_rpnl,
                notes=f"SELL_LONG fill {fill_qty} {stock.symbol} @ {exec_price}",
            )
            await apply_share_mutation(
                session,
                game_id=game_id,
                game_participant_id=seller_pid,
                stock_id=stock.id,
                holding=seller_holding,
                short_pos=seller_short,
                entry_type=ShareLedgerType.SELL_FILL_DEBIT.value,
                reference_type="TRADE",
                reference_id=trade.id,
                idempotency_key=f"trd:sell:share:{trade.id}",
                delta_long_reserved=-fill_qty,
            )

        elif sell_order.intent == OrderIntent.SHORT_SELL.value:
            is_last_sell = fill_qty == sell_order.remaining_quantity
            rel_ord_margin = (
                to_dec(sell_order.reserved_short_margin)
                if is_last_sell
                else _floor_4dp(
                    sell_order.reserved_short_margin * Decimal(fill_qty) / Decimal(sell_order.remaining_quantity)
                )
            )
            sell_order.reserved_short_margin = to_dec(sell_order.reserved_short_margin - rel_ord_margin)
            sell_order.reserved_borrow_shares -= fill_qty

            req_fill_margin = to_dec(gross_val * to_dec(game.initial_margin_ratio))
            # If rel_ord_margin > req_fill_margin, refund excess margin to available_cash
            margin_excess_refund = to_dec(rel_ord_margin - req_fill_margin)
            net_short_proceeds = to_dec(gross_val - seller_fee)
            seller_rpnl = -seller_fee

            old_short_qty = seller_short.borrowed_shares
            new_short_qty = old_short_qty + fill_qty
            seller_short.weighted_avg_open_price = to_dec(
                ((seller_short.weighted_avg_open_price * Decimal(old_short_qty)) + gross_val)
                / Decimal(new_short_qty)
            )
            seller_short.sale_proceeds_locked = to_dec(seller_short.sale_proceeds_locked + net_short_proceeds)
            seller_short.margin_collateral_locked = to_dec(seller_short.margin_collateral_locked + req_fill_margin)

            await apply_cash_mutation(
                session,
                seller_pf,
                entry_type=CashLedgerType.SHORT_PROCEEDS_LOCK.value,
                reference_type="TRADE",
                reference_id=trade.id,
                idempotency_key=f"trd:short:cash:{trade.id}",
                delta_available=margin_excess_refund,
                delta_short_margin=-margin_excess_refund,
                delta_short_proceeds=net_short_proceeds,
                realized_pnl_delta=seller_rpnl,
                notes=f"SHORT_SELL fill {fill_qty} {stock.symbol} @ {exec_price}",
            )
            await apply_share_mutation(
                session,
                game_id=game_id,
                game_participant_id=seller_pid,
                stock_id=stock.id,
                holding=seller_holding,
                short_pos=seller_short,
                entry_type=ShareLedgerType.SHORT_BORROW_OPEN.value,
                reference_type="TRADE",
                reference_id=trade.id,
                idempotency_key=f"trd:short:share:{trade.id}",
                delta_short_borrowed=fill_qty,
            )
            pool.reserved_pool_shares -= fill_qty
            pool.borrowed_shares += fill_qty

        # Update both orders' fill counters & average fill prices
        for ord_obj in (buy_order, sell_order):
            prev_filled = ord_obj.filled_quantity
            prev_avg = ord_obj.avg_fill_price or ZERO
            new_filled = prev_filled + fill_qty
            ord_obj.avg_fill_price = to_dec(
                ((prev_avg * Decimal(prev_filled)) + gross_val) / Decimal(new_filled)
            )
            ord_obj.filled_quantity = new_filled
            ord_obj.remaining_quantity -= fill_qty
            ord_obj.status = (
                OrderStatus.FILLED.value if ord_obj.remaining_quantity == 0 else OrderStatus.PARTIALLY_FILLED.value
            )
            ord_obj.updated_at = now

        # Record per-participant OrderExecution legs
        session.add(
            OrderExecution(
                game_id=game_id,
                stock_id=stock.id,
                game_participant_id=buyer_pid,
                order_id=buy_order.id,
                trade_id=trade.id,
                execution_kind=ExecutionKind.P2P_TRADE.value,
                intent=buy_order.intent,
                side=OrderSide.BUY.value,
                price=exec_price,
                quantity=fill_qty,
                gross_amount=gross_val,
                fee_amount=buyer_fee,
                realized_pnl_delta=buyer_rpnl,
                counterparty_code=tcode_map.get(seller_pid, "MTT-ANON"),
                executed_at=now,
            )
        )
        session.add(
            OrderExecution(
                game_id=game_id,
                stock_id=stock.id,
                game_participant_id=seller_pid,
                order_id=sell_order.id,
                trade_id=trade.id,
                execution_kind=ExecutionKind.P2P_TRADE.value,
                intent=sell_order.intent,
                side=OrderSide.SELL.value,
                price=exec_price,
                quantity=fill_qty,
                gross_amount=gross_val,
                fee_amount=seller_fee,
                realized_pnl_delta=seller_rpnl,
                counterparty_code=tcode_map.get(buyer_pid, "MTT-ANON"),
                executed_at=now,
            )
        )

        fill_notional_accum = to_dec(fill_notional_accum + gross_val)
        trades_executed.append(trade)
        affected_participants.add(buyer_pid)
        affected_participants.add(seller_pid)

    # 6. Post-Walk Remainder Handling (IOC / Market unfilled cancellation)
    if order.remaining_quantity > 0 and order.time_in_force == TimeInForce.IOC.value:
        await _release_order_reservations(
            session,
            order=order,
            portfolio=submitter_pf,
            holding=submitter_holding,
            short_pos=submitter_short,
            pool=pool,
            reason_tag="ioc_remainder",
        )
        order.status = OrderStatus.CANCELLED.value if order.filled_quantity == 0 else OrderStatus.FILLED.value
        if order.filled_quantity > 0:
            # Normalize partially filled IOC order quantities cleanly so filled + remaining = quantity constraint holds:
            # keep status CANCELLED with cancel_reason = PARTIAL_IOC_REMAINDER_CANCELLED so filled_quantity is preserved!
            order.status = OrderStatus.CANCELLED.value
            order.cancel_reason = "IOC_UNFILLED_REMAINDER_CANCELLED"
        else:
            order.cancel_reason = "NO_OPPOSITE_LIQUIDITY_WITHIN_COLLAR"
        order.updated_at = now

    # 7. Update stock quotes, VWAP, Official MTM, and candles
    if trades_executed:
        for tr in trades_executed:
            await recompute_stock_market_metrics(
                session,
                game=game,
                stock=stock,
                ref_row=ref_row,
                now=now,
                latest_trade_price=tr.price,
                latest_trade_qty=tr.quantity,
            )
    else:
        await recompute_stock_market_metrics(session, game=game, stock=stock, ref_row=ref_row, now=now)

    # Refresh net_worth_achieved_at tie-breaker timestamps for affected players
    for pid in affected_participants:
        pf = (
            await session.execute(
                select(PlayerPortfolio).where(PlayerPortfolio.game_participant_id == pid).with_for_update()
            )
        ).scalar_one()
        val = await compute_participant_valuation(
            session,
            game_id=game_id,
            game_participant_id=pid,
            initial_net_worth=game.initial_net_worth,
        )
        if val.net_worth != pf.last_net_worth:
            pf.last_net_worth = val.net_worth
            pf.net_worth_achieved_at = now

    await session.flush()
    return serialize_order(order, stock.symbol), trades_executed, affected_participants


async def cancel_order(
    session: AsyncSession,
    *,
    game_id: uuid.UUID,
    order_id: uuid.UUID,
    actor_participant_id: uuid.UUID | None = None,
    is_admin_or_system: bool = False,
    reason: str = "USER_CANCELLED",
) -> OrderResponse:
    """Atomically cancel an open or partially-filled order and release all reservations."""
    ord_peek = (
        await session.execute(select(Order).where(Order.id == order_id, Order.game_id == game_id))
    ).scalar_one_or_none()
    if ord_peek is None:
        raise ResourceNotFoundError("Order not found.")
    if not is_admin_or_system and ord_peek.game_participant_id != actor_participant_id:
        raise ForbiddenActionError("Cannot cancel another participant's order.")

    await acquire_stock_matching_lock(session, game_id, ord_peek.stock_id)

    order = (await session.execute(select(Order).where(Order.id == order_id).with_for_update())).scalar_one()
    stock = (await session.execute(select(Stock).where(Stock.id == order.stock_id).with_for_update())).scalar_one()
    if order.status not in (OrderStatus.OPEN.value, OrderStatus.PARTIALLY_FILLED.value):
        raise OrderValidationError(f"Order cannot be cancelled in status '{order.status}'.")

    pf = (
        await session.execute(
            select(PlayerPortfolio)
            .where(PlayerPortfolio.game_participant_id == order.game_participant_id)
            .with_for_update()
        )
    ).scalar_one()
    holding = (
        await session.execute(
            select(PlayerStockHolding)
            .where(
                PlayerStockHolding.game_participant_id == order.game_participant_id,
                PlayerStockHolding.stock_id == stock.id,
            )
            .with_for_update()
        )
    ).scalar_one()
    short_pos = (
        await session.execute(
            select(ShortPosition)
            .where(
                ShortPosition.game_participant_id == order.game_participant_id,
                ShortPosition.stock_id == stock.id,
            )
            .with_for_update()
        )
    ).scalar_one()
    pool = (
        await session.execute(
            select(BorrowingPoolInventory)
            .where(BorrowingPoolInventory.game_id == game_id, BorrowingPoolInventory.stock_id == stock.id)
            .with_for_update()
        )
    ).scalar_one()
    ref_row = (
        await session.execute(
            select(MarketReferencePrice)
            .where(MarketReferencePrice.game_id == game_id, MarketReferencePrice.stock_id == stock.id)
            .with_for_update()
        )
    ).scalar_one()
    game = (await session.execute(select(Game).where(Game.id == game_id))).scalar_one()

    await _release_order_reservations(
        session,
        order=order,
        portfolio=pf,
        holding=holding,
        short_pos=short_pos,
        pool=pool,
        reason_tag="cancel",
    )
    order.status = OrderStatus.CANCELLED.value
    order.cancel_reason = reason
    order.updated_at = datetime.now(timezone.utc)

    await recompute_stock_market_metrics(session, game=game, stock=stock, ref_row=ref_row)
    await session.flush()
    return serialize_order(order, stock.symbol)


async def modify_order_cancel_replace(
    session: AsyncSession,
    *,
    game_id: uuid.UUID,
    order_id: uuid.UUID,
    game_participant_id: uuid.UUID,
    req: ModifyOrderRequest,
    idempotency_key: str | None = None,
) -> tuple[OrderResponse, list[Trade], set[uuid.UUID]]:
    """
    Atomic cancel-and-replace inside one transaction:
      1. Cancels the resting order (releasing unused reservations).
      2. Places the replacement LIMIT order for the requested remaining/new quantity & price.
      3. Links replaces_order_id <-> replaced_by_order_id.
    """
    old_resp = await cancel_order(
        session,
        game_id=game_id,
        order_id=order_id,
        actor_participant_id=game_participant_id,
        reason="REPLACED_BY_MODIFY",
    )
    old_order = (await session.execute(select(Order).where(Order.id == order_id))).scalar_one()
    new_req = PlaceOrderRequest(
        symbol=old_resp.symbol,
        intent=old_order.intent,
        price_type=OrderPriceType.LIMIT.value,
        quantity=req.quantity,
        limit_price=req.limit_price,
        time_in_force=old_order.time_in_force,
        client_order_id=req.client_order_id or idempotency_key or f"replace:{order_id}:{uuid.uuid4().hex[:8]}",
    )
    new_resp, trades, affected = await place_order(
        session,
        game_id=game_id,
        game_participant_id=game_participant_id,
        req=new_req,
    )
    new_order = (await session.execute(select(Order).where(Order.id == new_resp.id))).scalar_one()
    new_order.replaces_order_id = old_order.id
    old_order.replaced_by_order_id = new_order.id
    await session.flush()
    return new_resp, trades, affected


async def expire_stale_orders_for_stock(
    session: AsyncSession,
    *,
    game: Game,
    stock: Stock,
    pool: BorrowingPoolInventory,
    now: datetime,
) -> list[Order]:
    """Expire any resting orders on a stock whose expires_at <= now, releasing reservations."""
    stale_orders = (
        await session.execute(
            select(Order)
            .where(
                Order.game_id == game.id,
                Order.stock_id == stock.id,
                Order.status.in_([OrderStatus.OPEN.value, OrderStatus.PARTIALLY_FILLED.value]),
                Order.expires_at.is_not(None),
                Order.expires_at <= now,
            )
            .with_for_update()
        )
    ).scalars().all()

    for ord_obj in stale_orders:
        pf = (
            await session.execute(
                select(PlayerPortfolio)
                .where(PlayerPortfolio.game_participant_id == ord_obj.game_participant_id)
                .with_for_update()
            )
        ).scalar_one()
        holding = (
            await session.execute(
                select(PlayerStockHolding)
                .where(
                    PlayerStockHolding.game_participant_id == ord_obj.game_participant_id,
                    PlayerStockHolding.stock_id == stock.id,
                )
                .with_for_update()
            )
        ).scalar_one()
        short_pos = (
            await session.execute(
                select(ShortPosition)
                .where(
                    ShortPosition.game_participant_id == ord_obj.game_participant_id,
                    ShortPosition.stock_id == stock.id,
                )
                .with_for_update()
            )
        ).scalar_one()
        await _release_order_reservations(
            session,
            order=ord_obj,
            portfolio=pf,
            holding=holding,
            short_pos=short_pos,
            pool=pool,
            reason_tag="expired",
        )
        ord_obj.status = OrderStatus.EXPIRED.value
        ord_obj.cancel_reason = "ORDER_EXPIRED"
        ord_obj.updated_at = now

    return list(stale_orders)


async def get_order_book_depth(
    session: AsyncSession,
    *,
    game_id: uuid.UUID,
    stock_id: uuid.UUID,
    levels: int = 15,
) -> dict:
    """Aggregate resting bids & asks into top N price levels."""
    active_orders = (
        await session.execute(
            select(Order).where(
                Order.game_id == game_id,
                Order.stock_id == stock_id,
                Order.status.in_([OrderStatus.OPEN.value, OrderStatus.PARTIALLY_FILLED.value]),
                Order.limit_price.is_not(None),
            )
        )
    ).scalars().all()

    bid_buckets: dict[Decimal, list[int]] = {}
    ask_buckets: dict[Decimal, list[int]] = {}

    for o in active_orders:
        px = to_dec(o.limit_price)
        target = bid_buckets if o.side == OrderSide.BUY.value else ask_buckets
        if px not in target:
            target[px] = [0, 0]
        target[px][0] += o.remaining_quantity
        target[px][1] += 1

    sorted_bids = sorted(bid_buckets.items(), key=lambda kv: kv[0], reverse=True)[:levels]
    sorted_asks = sorted(ask_buckets.items(), key=lambda kv: kv[0])[:levels]

    bids = [
        {"price": str(px), "quantity": vals[0], "order_count": vals[1]}
        for px, vals in sorted_bids
    ]
    asks = [
        {"price": str(px), "quantity": vals[0], "order_count": vals[1]}
        for px, vals in sorted_asks
    ]
    best_bid = sorted_bids[0][0] if sorted_bids else None
    best_ask = sorted_asks[0][0] if sorted_asks else None
    spread = to_dec(best_ask - best_bid) if (best_bid is not None and best_ask is not None) else None

    return {
        "bids": bids,
        "asks": asks,
        "best_bid": str(best_bid) if best_bid is not None else None,
        "best_ask": str(best_ask) if best_ask is not None else None,
        "spread": str(spread) if spread is not None else None,
    }
