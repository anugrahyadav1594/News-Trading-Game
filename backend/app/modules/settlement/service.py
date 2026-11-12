import uuid
from datetime import datetime, timezone
from decimal import Decimal
from sqlalchemy import asc, delete, desc, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.decimal_utils import ZERO, to_dec
from app.core.exceptions import InvalidGamePhaseError, ResourceNotFoundError
from app.db.locks import acquire_game_lifecycle_lock, acquire_stock_matching_lock
from app.models.enums import (
    CashLedgerType,
    ExecutionKind,
    GameStatus,
    LeaderboardSnapshotType,
    MarginStatus,
    NewsApprovalStatus,
    OrderIntent,
    OrderSide,
    OrderStatus,
    ShareLedgerType,
)
from app.models.game import Game, GameParticipant, GamePhase
from app.models.leaderboard import LeaderboardSnapshot
from app.models.market import MarketReferencePrice
from app.models.news import NewsEvent
from app.models.order import Order, OrderExecution
from app.models.portfolio import PlayerPortfolio, PlayerStockHolding
from app.models.shorting import BorrowingPoolInventory, ShortPosition
from app.models.stock import Stock
from app.models.user import Participant, User
from app.modules.accounting.service import (
    apply_cash_mutation,
    apply_share_mutation,
    compute_participant_valuation,
)
from app.modules.audit.service import record_audit_event
from app.modules.matching.service import cancel_order
from app.modules.news.schemas import ReleaseNewsRequest
from app.modules.news.service import release_or_schedule_news_event
from app.modules.pricing.service import recompute_stock_market_metrics
from app.modules.tournament.service import compute_clock_state


async def _close_current_phase_row(session: AsyncSession, game_id: uuid.UUID, now: datetime) -> None:
    open_phase = (
        await session.execute(
            select(GamePhase)
            .where(GamePhase.game_id == game_id, GamePhase.exited_at.is_(None))
            .order_by(desc(GamePhase.entered_at))
            .limit(1)
            .with_for_update()
        )
    ).scalar_one_or_none()
    if open_phase is not None:
        open_phase.exited_at = now


async def start_main_trading(
    session: AsyncSession,
    game_id: uuid.UUID,
    *,
    admin_user: User | None = None,
    triggered_by: str = "ADMIN_MANUAL",
) -> Game:
    await acquire_game_lifecycle_lock(session, game_id)
    game = (await session.execute(select(Game).where(Game.id == game_id).with_for_update())).scalar_one_or_none()
    if game is None:
        raise ResourceNotFoundError("Game not found.")
    if game.status not in (GameStatus.DRAFT.value, GameStatus.LOBBY.value):
        raise InvalidGamePhaseError(f"Cannot start trading from phase '{game.status}'.")

    now = datetime.now(timezone.utc)
    await _close_current_phase_row(session, game_id, now)

    old_status = game.status
    game.status = GameStatus.MAIN_TRADING.value
    game.trading_started_at = now
    game.updated_at = now

    session.add(
        GamePhase(
            game_id=game.id,
            phase=GameStatus.MAIN_TRADING.value,
            entered_at=now,
            triggered_by=triggered_by,
            actor_user_id=admin_user.id if admin_user else None,
            notes="45-minute Main Trading Round started.",
        )
    )
    await record_audit_event(
        session,
        actor_user_id=admin_user.id if admin_user else None,
        actor_role=admin_user.role if admin_user else "SYSTEM_CLOCK",
        action_type="GAME_STARTED",
        target_type="GAME",
        target_id=str(game.id),
        game_id=game.id,
        before_state={"status": old_status},
        after_state={"status": game.status, "trading_started_at": now.isoformat()},
    )
    await session.flush()
    return game


async def pause_game(
    session: AsyncSession,
    game_id: uuid.UUID,
    *,
    admin_user: User,
    reason: str = "Administrative trading pause",
) -> Game:
    await acquire_game_lifecycle_lock(session, game_id)
    game = (await session.execute(select(Game).where(Game.id == game_id).with_for_update())).scalar_one_or_none()
    if game is None:
        raise ResourceNotFoundError("Game not found.")
    if game.status not in (GameStatus.MAIN_TRADING.value, GameStatus.SHORT_SETTLEMENT.value):
        raise InvalidGamePhaseError(f"Cannot pause game while in '{game.status}'.")

    now = datetime.now(timezone.utc)
    await _close_current_phase_row(session, game_id, now)

    game.previous_active_phase = game.status
    game.status = GameStatus.PAUSED.value
    game.paused_at = now
    game.updated_at = now

    session.add(
        GamePhase(
            game_id=game.id,
            phase=GameStatus.PAUSED.value,
            entered_at=now,
            triggered_by="ADMIN_MANUAL",
            actor_user_id=admin_user.id,
            notes=reason,
        )
    )
    await record_audit_event(
        session,
        actor_user_id=admin_user.id,
        actor_role=admin_user.role,
        action_type="GAME_PAUSED",
        target_type="GAME",
        target_id=str(game.id),
        game_id=game.id,
        before_state={"status": game.previous_active_phase},
        after_state={"status": GameStatus.PAUSED.value},
        reason=reason,
    )
    await session.flush()
    return game


async def resume_game(
    session: AsyncSession,
    game_id: uuid.UUID,
    *,
    admin_user: User,
    reason: str = "Administrative trading resume",
) -> Game:
    await acquire_game_lifecycle_lock(session, game_id)
    game = (await session.execute(select(Game).where(Game.id == game_id).with_for_update())).scalar_one_or_none()
    if game is None:
        raise ResourceNotFoundError("Game not found.")
    if game.status != GameStatus.PAUSED.value or game.previous_active_phase is None:
        raise InvalidGamePhaseError("Game is not currently paused.")

    now = datetime.now(timezone.utc)
    pause_delta_ms = int((now - game.paused_at).total_seconds() * 1000) if game.paused_at else 0
    if game.previous_active_phase == GameStatus.MAIN_TRADING.value:
        game.accumulated_pause_ms += max(0, pause_delta_ms)
    elif game.previous_active_phase == GameStatus.SHORT_SETTLEMENT.value:
        game.settlement_pause_ms += max(0, pause_delta_ms)

    await _close_current_phase_row(session, game_id, now)
    restored = game.previous_active_phase
    game.status = restored
    game.previous_active_phase = None
    game.paused_at = None
    game.updated_at = now

    session.add(
        GamePhase(
            game_id=game.id,
            phase=restored,
            entered_at=now,
            triggered_by="ADMIN_MANUAL",
            actor_user_id=admin_user.id,
            notes=reason,
        )
    )
    await record_audit_event(
        session,
        actor_user_id=admin_user.id,
        actor_role=admin_user.role,
        action_type="GAME_RESUMED",
        target_type="GAME",
        target_id=str(game.id),
        game_id=game.id,
        before_state={"status": GameStatus.PAUSED.value},
        after_state={"status": restored, "pause_added_ms": pause_delta_ms},
        reason=reason,
    )
    await session.flush()
    return game


async def enter_short_settlement_phase(
    session: AsyncSession,
    game_id: uuid.UUID,
    *,
    triggered_by: str = "SYSTEM_CLOCK",
    admin_user: User | None = None,
) -> tuple[Game, int]:
    """
    Transition from Phase A (45m MAIN_TRADING) into Phase B (5m SHORT_SETTLEMENT):
      - Automatically cancels all resting position-opening orders (BUY_LONG & SHORT_SELL),
        releasing reserved cash, short margin, and borrowing pool shares.
      - Keeps resting close-only orders (SELL_LONG & BUY_TO_COVER) active.
    Returns (game, cancelled_opening_order_count).
    """
    await acquire_game_lifecycle_lock(session, game_id)
    game = (await session.execute(select(Game).where(Game.id == game_id).with_for_update())).scalar_one_or_none()
    if game is None:
        raise ResourceNotFoundError("Game not found.")
    if game.status == GameStatus.SHORT_SETTLEMENT.value:
        return game, 0
    if game.status not in (GameStatus.MAIN_TRADING.value, GameStatus.PAUSED.value):
        raise InvalidGamePhaseError(f"Cannot enter settlement phase from '{game.status}'.")

    now = datetime.now(timezone.utc)
    await _close_current_phase_row(session, game_id, now)

    old_status = game.status
    game.status = GameStatus.SHORT_SETTLEMENT.value
    game.previous_active_phase = None
    game.paused_at = None
    game.settlement_started_at = now
    game.updated_at = now

    # Cancel all resting BUY_LONG and SHORT_SELL orders so only close-only orders remain
    opening_order_ids = (
        await session.execute(
            select(Order.id).where(
                Order.game_id == game_id,
                Order.status.in_([OrderStatus.OPEN.value, OrderStatus.PARTIALLY_FILLED.value]),
                Order.intent.in_([OrderIntent.BUY_LONG.value, OrderIntent.SHORT_SELL.value]),
            )
        )
    ).scalars().all()

    for oid in opening_order_ids:
        await cancel_order(
            session,
            game_id=game_id,
            order_id=oid,
            is_admin_or_system=True,
            reason="PHASE_B_SETTLEMENT_OPEN_ORDERS_CANCELLED",
        )

    session.add(
        GamePhase(
            game_id=game.id,
            phase=GameStatus.SHORT_SETTLEMENT.value,
            entered_at=now,
            triggered_by=triggered_by,
            actor_user_id=admin_user.id if admin_user else None,
            notes=f"5-minute Short Position Settlement started; cancelled {len(opening_order_ids)} opening orders.",
        )
    )
    await record_audit_event(
        session,
        actor_user_id=admin_user.id if admin_user else None,
        actor_role=admin_user.role if admin_user else "SYSTEM_CLOCK",
        action_type="ENTERED_SHORT_SETTLEMENT",
        target_type="GAME",
        target_id=str(game.id),
        game_id=game.id,
        before_state={"status": old_status},
        after_state={
            "status": GameStatus.SHORT_SETTLEMENT.value,
            "cancelled_opening_orders": len(opening_order_ids),
        },
    )
    await session.flush()
    return game, len(opening_order_ids)


async def finalize_settlement_and_complete_game(
    session: AsyncSession,
    game_id: uuid.UUID,
    *,
    triggered_by: str = "SYSTEM_CLOCK",
    admin_user: User | None = None,
    reason: str = "Automatic end-of-settlement short liquidation and final ranking",
    now: datetime | None = None,
) -> tuple[Game, list[LeaderboardSnapshot]]:
    """
    Execute end-of-Phase-B administrative short liquidation & lock final tournament rankings:
      1. Cancel all remaining open orders across all stocks.
      2. Freeze Official Final Settlement Prices on all 5 stocks.
      3. Automatically liquidate every remaining open short position at Official Final Settlement Price:
         - Returns borrowed shares to central borrowing pool.
         - Deducts cash obligation from locked short proceeds -> locked short margin -> available cash.
         - Records any unfunded liability in unfunded_settlement_debt without ever waiving debt.
         - Logs explicit ADMIN_FINAL_SHORT_SETTLEMENT execution & audit records (not fake P2P trades).
      4. Compute server-authoritative Final Net Worth, Net P&L, Return %, and deterministic tie-breakers.
      5. Lock immutable FINAL_OFFICIAL leaderboard and mark game COMPLETED (read-only).
    """
    await acquire_game_lifecycle_lock(session, game_id)
    game = (await session.execute(select(Game).where(Game.id == game_id).with_for_update())).scalar_one_or_none()
    if game is None:
        raise ResourceNotFoundError("Game not found.")
    if game.status == GameStatus.COMPLETED.value:
        existing_lb = (
            await session.execute(
                select(LeaderboardSnapshot)
                .where(
                    LeaderboardSnapshot.game_id == game_id,
                    LeaderboardSnapshot.snapshot_type == LeaderboardSnapshotType.FINAL_OFFICIAL.value,
                )
                .order_by(asc(LeaderboardSnapshot.rank))
            )
        ).scalars().all()
        return game, list(existing_lb)

    now = now or datetime.now(timezone.utc)
    old_status = game.status
    game.status = GameStatus.SETTLING.value

    # 1. Cancel all remaining resting orders across all stocks
    remaining_order_ids = (
        await session.execute(
            select(Order.id).where(
                Order.game_id == game_id,
                Order.status.in_([OrderStatus.OPEN.value, OrderStatus.PARTIALLY_FILLED.value]),
            )
        )
    ).scalars().all()
    for oid in remaining_order_ids:
        await cancel_order(
            session,
            game_id=game_id,
            order_id=oid,
            is_admin_or_system=True,
            reason="FINAL_SETTLEMENT_BOOK_CLOSE",
        )

    # 2. Freeze Official Final Settlement Prices on all 5 stocks
    stocks = (
        await session.execute(select(Stock).where(Stock.game_id == game_id).order_by(Stock.symbol))
    ).scalars().all()
    final_prices: dict[uuid.UUID, Decimal] = {}
    final_prices_by_sym: dict[str, str] = {}

    for st in stocks:
        await acquire_stock_matching_lock(session, game_id, st.id)
        ref_row = (
            await session.execute(
                select(MarketReferencePrice)
                .where(MarketReferencePrice.game_id == game_id, MarketReferencePrice.stock_id == st.id)
                .with_for_update()
            )
        ).scalar_one()
        await recompute_stock_market_metrics(session, game=game, stock=st, ref_row=ref_row, now=now)
        ref_row.final_settlement_price = to_dec(ref_row.official_mtm_price)
        final_prices[st.id] = ref_row.final_settlement_price
        final_prices_by_sym[st.symbol] = str(ref_row.final_settlement_price)

    # 3. Administratively liquidate all remaining open short positions
    open_shorts = (
        await session.execute(
            select(ShortPosition)
            .where(ShortPosition.game_id == game_id, ShortPosition.borrowed_shares > 0)
            .with_for_update()
        )
    ).scalars().all()

    auto_settled_summary: list[dict] = []

    for sp in open_shorts:
        qty = sp.borrowed_shares
        settle_px = final_prices[sp.stock_id]
        obligation = to_dec(settle_px * Decimal(qty))

        pf = (
            await session.execute(
                select(PlayerPortfolio)
                .where(PlayerPortfolio.game_participant_id == sp.game_participant_id)
                .with_for_update()
            )
        ).scalar_one()
        holding = (
            await session.execute(
                select(PlayerStockHolding)
                .where(
                    PlayerStockHolding.game_participant_id == sp.game_participant_id,
                    PlayerStockHolding.stock_id == sp.stock_id,
                )
                .with_for_update()
            )
        ).scalar_one()
        pool = (
            await session.execute(
                select(BorrowingPoolInventory)
                .where(
                    BorrowingPoolInventory.game_id == game_id,
                    BorrowingPoolInventory.stock_id == sp.stock_id,
                )
                .with_for_update()
            )
        ).scalar_one()

        used_proc = to_dec(sp.sale_proceeds_locked)
        used_margin = to_dec(sp.margin_collateral_locked)
        collat_unlocked = to_dec(used_proc + used_margin)
        rpnl = to_dec(used_proc - obligation)

        unfunded_shortfall = ZERO
        if collat_unlocked >= obligation:
            avail_delta = to_dec(collat_unlocked - obligation)
        else:
            needed_from_avail = to_dec(obligation - collat_unlocked)
            if pf.available_cash >= needed_from_avail:
                avail_delta = -needed_from_avail
            else:
                paid_from_avail = to_dec(pf.available_cash)
                avail_delta = -paid_from_avail
                unfunded_shortfall = to_dec(needed_from_avail - paid_from_avail)

        exec_rec = OrderExecution(
            game_id=game_id,
            stock_id=sp.stock_id,
            game_participant_id=sp.game_participant_id,
            order_id=None,
            trade_id=None,
            execution_kind=ExecutionKind.ADMIN_FINAL_SHORT_SETTLEMENT.value,
            intent="AUTO_SHORT_SETTLEMENT",
            side=OrderSide.BUY.value,
            price=settle_px,
            quantity=qty,
            gross_amount=obligation,
            fee_amount=ZERO,
            realized_pnl_delta=rpnl,
            counterparty_code="CENTRAL_SETTLEMENT_POOL",
            executed_at=now,
        )
        session.add(exec_rec)
        await session.flush()

        await apply_cash_mutation(
            session,
            pf,
            entry_type=(
                CashLedgerType.UNFUNDED_LIABILITY_RECORDED.value
                if unfunded_shortfall > ZERO
                else CashLedgerType.FORCED_SETTLEMENT_DEBIT.value
            ),
            reference_type="SETTLEMENT",
            reference_id=exec_rec.id,
            idempotency_key=f"settle:short:cash:{sp.id}",
            delta_available=avail_delta,
            delta_short_margin=-used_margin,
            delta_short_proceeds=-used_proc,
            delta_unfunded_debt=unfunded_shortfall,
            realized_pnl_delta=rpnl,
            notes=f"Automatic Phase-B final short settlement: {qty} shares @ {settle_px}",
        )

        await apply_share_mutation(
            session,
            game_id=game_id,
            game_participant_id=sp.game_participant_id,
            stock_id=sp.stock_id,
            holding=holding,
            short_pos=sp,
            entry_type=ShareLedgerType.FORCED_SHORT_SETTLEMENT_RETURN.value,
            reference_type="SETTLEMENT",
            reference_id=exec_rec.id,
            idempotency_key=f"settle:short:share:{sp.id}",
            delta_short_borrowed=-qty,
        )

        pool.borrowed_shares -= qty
        pool.available_pool_shares += qty

        sp.pending_cover_shares = 0
        sp.sale_proceeds_locked = ZERO
        sp.margin_collateral_locked = ZERO
        sp.realized_pnl = to_dec(sp.realized_pnl + rpnl)
        sp.weighted_avg_open_price = ZERO
        sp.margin_status = MarginStatus.SETTLED.value
        sp.updated_at = now

        auto_settled_summary.append(
            {
                "game_participant_id": str(sp.game_participant_id),
                "stock_id": str(sp.stock_id),
                "quantity": qty,
                "settlement_price": str(settle_px),
                "obligation": str(obligation),
                "unfunded_shortfall": str(unfunded_shortfall),
            }
        )

    # 4. Compute Official Final Rankings with Deterministic Tie-Breakers
    snapshots = await build_and_persist_leaderboard(
        session,
        game=game,
        snapshot_type=LeaderboardSnapshotType.FINAL_OFFICIAL.value,
        use_final_settlement_price=True,
        make_immutable=True,
        now=now,
    )

    # 5. Lock game COMPLETED
    await _close_current_phase_row(session, game_id, now)
    game.status = GameStatus.COMPLETED.value
    game.completed_at = now
    game.updated_at = now

    session.add(
        GamePhase(
            game_id=game.id,
            phase=GameStatus.COMPLETED.value,
            entered_at=now,
            triggered_by=triggered_by,
            actor_user_id=admin_user.id if admin_user else None,
            notes=f"Settlement completed; {len(auto_settled_summary)} open short positions auto-liquidated.",
        )
    )
    await record_audit_event(
        session,
        actor_user_id=admin_user.id if admin_user else None,
        actor_role=admin_user.role if admin_user else "SYSTEM_CLOCK",
        action_type="GAME_SETTLED_AND_COMPLETED",
        target_type="GAME",
        target_id=str(game.id),
        game_id=game.id,
        before_state={"status": old_status},
        after_state={
            "status": GameStatus.COMPLETED.value,
            "final_settlement_prices": final_prices_by_sym,
            "auto_liquidated_positions": auto_settled_summary,
            "ranked_participants": len(snapshots),
        },
        reason=reason,
    )
    await session.flush()
    return game, snapshots


async def build_and_persist_leaderboard(
    session: AsyncSession,
    *,
    game: Game,
    snapshot_type: str = LeaderboardSnapshotType.LIVE.value,
    use_final_settlement_price: bool = False,
    make_immutable: bool = False,
    now: datetime | None = None,
) -> list[LeaderboardSnapshot]:
    """
    Calculate server-authoritative rankings (Section 11):
      Sort order:
        1. Final Net Worth DESC
        2. Realized Trading P&L DESC
        3. Earlier achievement of Net Worth ASC
        4. Tournament Code ASC
    """
    ts = now or datetime.now(timezone.utc)

    # If immutable FINAL_OFFICIAL already exists, never overwrite it!
    if snapshot_type == LeaderboardSnapshotType.FINAL_OFFICIAL.value:
        existing_final = (
            await session.execute(
                select(LeaderboardSnapshot)
                .where(
                    LeaderboardSnapshot.game_id == game.id,
                    LeaderboardSnapshot.snapshot_type == LeaderboardSnapshotType.FINAL_OFFICIAL.value,
                    LeaderboardSnapshot.is_immutable.is_(True),
                )
                .order_by(asc(LeaderboardSnapshot.rank))
            )
        ).scalars().all()
        if existing_final:
            return list(existing_final)

    # Preload mark prices once for fast O(N) valuation across 1,000+ participants
    refs = (
        await session.execute(select(MarketReferencePrice).where(MarketReferencePrice.game_id == game.id))
    ).scalars().all()
    price_map: dict[uuid.UUID, Decimal] = {}
    for r in refs:
        if use_final_settlement_price and r.final_settlement_price is not None:
            price_map[r.stock_id] = to_dec(r.final_settlement_price)
        else:
            price_map[r.stock_id] = to_dec(r.official_mtm_price)

    gp_rows = (
        await session.execute(
            select(GameParticipant, Participant, PlayerPortfolio)
            .join(Participant, Participant.id == GameParticipant.participant_id)
            .join(PlayerPortfolio, PlayerPortfolio.game_participant_id == GameParticipant.id)
            .where(
                GameParticipant.game_id == game.id,
                GameParticipant.allocation_initialized.is_(True),
                GameParticipant.is_disqualified.is_(False),
            )
        )
    ).all()

    holdings_all = (
        await session.execute(select(PlayerStockHolding).where(PlayerStockHolding.game_id == game.id))
    ).scalars().all()
    shorts_all = (
        await session.execute(select(ShortPosition).where(ShortPosition.game_id == game.id))
    ).scalars().all()

    long_val_by_gp: dict[uuid.UUID, Decimal] = {}
    for h in holdings_all:
        qty = h.available_shares + h.reserved_shares
        if qty > 0:
            v = to_dec(price_map.get(h.stock_id, ZERO) * Decimal(qty))
            long_val_by_gp[h.game_participant_id] = to_dec(long_val_by_gp.get(h.game_participant_id, ZERO) + v)

    short_liab_by_gp: dict[uuid.UUID, Decimal] = {}
    for sp in shorts_all:
        if sp.borrowed_shares > 0:
            liab = to_dec(price_map.get(sp.stock_id, ZERO) * Decimal(sp.borrowed_shares))
            short_liab_by_gp[sp.game_participant_id] = to_dec(short_liab_by_gp.get(sp.game_participant_id, ZERO) + liab)

    scored: list[dict] = []
    init_nw = to_dec(game.initial_net_worth)

    for gp, part, pf in gp_rows:
        avail = to_dec(pf.available_cash)
        res_total = to_dec(pf.order_reserved_cash + pf.short_margin_locked + pf.short_proceeds_locked)
        l_val = long_val_by_gp.get(gp.id, ZERO)
        s_liab = short_liab_by_gp.get(gp.id, ZERO)
        debt = to_dec(pf.unfunded_settlement_debt)
        nw = to_dec(avail + res_total + l_val - s_liab - debt)
        net_pnl = to_dec(nw - init_nw)
        ret_pct = to_dec((net_pnl / init_nw) * Decimal("100")) if init_nw > ZERO else ZERO

        scored.append(
            {
                "gp_id": gp.id,
                "tournament_code": part.tournament_code,
                "display_name": part.display_name,
                "avail": avail,
                "res_total": res_total,
                "l_val": l_val,
                "s_liab": s_liab,
                "debt": debt,
                "nw": nw,
                "net_pnl": net_pnl,
                "ret_pct": ret_pct,
                "realized_pnl": to_dec(pf.realized_pnl),
                "achieved_at": pf.net_worth_achieved_at,
            }
        )

    scored.sort(
        key=lambda item: (
            -item["nw"],
            -item["realized_pnl"],
            item["achieved_at"].timestamp(),
            item["tournament_code"],
        )
    )

    if snapshot_type == LeaderboardSnapshotType.LIVE.value:
        await session.execute(
            delete(LeaderboardSnapshot).where(
                LeaderboardSnapshot.game_id == game.id,
                LeaderboardSnapshot.snapshot_type == LeaderboardSnapshotType.LIVE.value,
                LeaderboardSnapshot.is_immutable.is_(False),
            )
        )

    created_snaps: list[LeaderboardSnapshot] = []
    for idx, item in enumerate(scored, start=1):
        snap = LeaderboardSnapshot(
            game_id=game.id,
            game_participant_id=item["gp_id"],
            snapshot_type=snapshot_type,
            rank=idx,
            tournament_code=item["tournament_code"],
            display_name=item["display_name"],
            available_cash=item["avail"],
            reserved_cash_total=item["res_total"],
            long_market_value=item["l_val"],
            short_liability=item["s_liab"],
            unfunded_debt=item["debt"],
            final_net_worth=item["nw"],
            net_pnl=item["net_pnl"],
            return_pct=item["ret_pct"],
            realized_pnl=item["realized_pnl"],
            achieved_at=item["achieved_at"],
            is_immutable=make_immutable,
            captured_at=ts,
        )
        session.add(snap)
        created_snaps.append(snap)

    await session.flush()
    return created_snaps


async def tick_authoritative_game_clock(session: AsyncSession, game_id: uuid.UUID) -> list[dict]:
    """
    Server clock tick:
      - Automatically transitions MAIN_TRADING -> SHORT_SETTLEMENT at 45:00.
      - Automatically transitions SHORT_SETTLEMENT -> COMPLETED (auto-liquidation) at 50:00.
      - Automatically releases any SCHEDULED news events whose scheduled_game_sec <= trading_elapsed_sec.
    """
    events_triggered: list[dict] = []
    game = (await session.execute(select(Game).where(Game.id == game_id))).scalar_one_or_none()
    if game is None or game.status in (
        GameStatus.DRAFT.value,
        GameStatus.LOBBY.value,
        GameStatus.PAUSED.value,
        GameStatus.COMPLETED.value,
        GameStatus.CANCELLED.value,
    ):
        return events_triggered

    now = datetime.now(timezone.utc)
    clock = compute_clock_state(game, now)

    if game.status == GameStatus.MAIN_TRADING.value:
        if clock.trading_remaining_ms <= 0:
            _, cancelled_cnt = await enter_short_settlement_phase(
                session, game_id, triggered_by="SYSTEM_CLOCK"
            )
            events_triggered.append(
                {
                    "event": "PHASE_CHANGED",
                    "new_phase": GameStatus.SHORT_SETTLEMENT.value,
                    "cancelled_opening_orders": cancelled_cnt,
                }
            )
            return events_triggered

        # Release scheduled news events due by current elapsed second
        if not game.news_halted:
            elapsed_sec = clock.trading_elapsed_ms // 1000
            due_events = (
                await session.execute(
                    select(NewsEvent)
                    .where(
                        NewsEvent.game_id == game_id,
                        NewsEvent.approval_status == NewsApprovalStatus.SCHEDULED.value,
                        NewsEvent.scheduled_game_sec.is_not(None),
                        NewsEvent.scheduled_game_sec <= elapsed_sec,
                    )
                    .order_by(asc(NewsEvent.scheduled_game_sec), asc(NewsEvent.created_at))
                )
            ).scalars().all()
            for ev in due_events:
                rel_ev, rel_rec = await release_or_schedule_news_event(
                    session,
                    game_id=game_id,
                    event_id=ev.id,
                    req=ReleaseNewsRequest(mode="IMMEDIATE"),
                    admin_user=None,
                )
                if rel_rec is not None:
                    events_triggered.append(
                        {
                            "event": "NEWS_RELEASED",
                            "event_id": str(rel_ev.id),
                            "headline": rel_ev.headline,
                            "post_ref_prices": rel_rec.post_release_ref_prices,
                        }
                    )

    elif game.status == GameStatus.SHORT_SETTLEMENT.value:
        if clock.settlement_remaining_ms <= 0:
            _, final_lb = await finalize_settlement_and_complete_game(
                session, game_id, triggered_by="SYSTEM_CLOCK"
            )
            events_triggered.append(
                {
                    "event": "PHASE_CHANGED",
                    "new_phase": GameStatus.COMPLETED.value,
                    "final_rankings_count": len(final_lb),
                }
            )

    return events_triggered
