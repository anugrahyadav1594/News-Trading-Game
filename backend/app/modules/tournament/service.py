import secrets
import uuid
from datetime import datetime, timezone
from decimal import Decimal
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.decimal_utils import ZERO, to_dec
from app.core.exceptions import (
    DuplicateAccountError,
    ForbiddenActionError,
    InvalidGamePhaseError,
    ResourceNotFoundError,
)
from app.db.locks import acquire_game_lifecycle_lock
from app.models.enums import (
    AssetType,
    CashLedgerType,
    GameStatus,
    MarginStatus,
    ShareLedgerType,
    UserRole,
)
from app.models.game import Game, GameParticipant, GamePhase, InitialAllocation
from app.models.market import MarketPriceHistory, MarketReferencePrice
from app.models.portfolio import PlayerPortfolio, PlayerStockHolding
from app.models.shorting import BorrowingPoolInventory, ShortPosition
from app.models.stock import CompanyProfile, Stock
from app.models.user import Participant, User
from app.modules.accounting.service import apply_cash_mutation, apply_share_mutation
from app.modules.audit.service import record_audit_event
from app.modules.tournament.schemas import (
    ClockStateSnapshot,
    CreateGameRequest,
    UpdateGameConfigRequest,
)
from app.modules.tournament.universe import INITIAL_INDIAN_STOCKS


def _floor_bucket(ts: datetime, interval_sec: int) -> datetime:
    epoch = int(ts.timestamp())
    floored = (epoch // interval_sec) * interval_sec
    return datetime.fromtimestamp(floored, tz=timezone.utc)


def compute_clock_state(game: Game, now: datetime | None = None) -> ClockStateSnapshot:
    now_ts = now or datetime.now(timezone.utc)
    trading_total_ms = game.trading_duration_sec * 1000
    settlement_total_ms = game.settlement_duration_sec * 1000

    is_paused = game.status == GameStatus.PAUSED.value
    effective_now = game.paused_at if (is_paused and game.paused_at is not None) else now_ts

    if game.trading_started_at is None:
        trading_elapsed_ms = 0
    else:
        raw_ms = int((effective_now - game.trading_started_at).total_seconds() * 1000) - game.accumulated_pause_ms
        trading_elapsed_ms = max(0, min(trading_total_ms, raw_ms))

    trading_remaining_ms = max(0, trading_total_ms - trading_elapsed_ms)

    if game.settlement_started_at is None:
        settlement_elapsed_ms = 0
    else:
        raw_s_ms = int((effective_now - game.settlement_started_at).total_seconds() * 1000) - game.settlement_pause_ms
        settlement_elapsed_ms = max(0, min(settlement_total_ms, raw_s_ms))

    settlement_remaining_ms = max(0, settlement_total_ms - settlement_elapsed_ms)

    active_phase = game.previous_active_phase if is_paused else game.status
    if active_phase == GameStatus.MAIN_TRADING.value:
        phase_remaining_ms = trading_remaining_ms
    elif active_phase == GameStatus.SHORT_SETTLEMENT.value:
        phase_remaining_ms = settlement_remaining_ms
    else:
        phase_remaining_ms = 0

    return ClockStateSnapshot(
        game_id=game.id,
        status=game.status,
        server_ts=now_ts,
        trading_elapsed_ms=trading_elapsed_ms,
        trading_remaining_ms=trading_remaining_ms,
        settlement_elapsed_ms=settlement_elapsed_ms,
        settlement_remaining_ms=settlement_remaining_ms,
        phase_remaining_ms=phase_remaining_ms,
        is_paused=is_paused,
        news_halted=game.news_halted,
    )


async def create_game(
    session: AsyncSession,
    req: CreateGameRequest,
    *,
    admin_user: User | None = None,
) -> Game:
    if req.maintenance_margin_ratio >= req.initial_margin_ratio:
        raise InvalidGamePhaseError("maintenance_margin_ratio must be strictly less than initial_margin_ratio.")

    code = (req.code or f"MTT-{secrets.token_hex(3).upper()}").strip().upper()
    exists = (await session.execute(select(Game.id).where(Game.code == code))).scalar_one_or_none()
    if exists is not None:
        raise DuplicateAccountError(f"Game code '{code}' already exists.")

    open_px = to_dec(req.default_opening_price)
    init_cash = to_dec(req.initial_cash)
    stock_total_val = to_dec(open_px * Decimal(req.default_shares_per_stock * len(INITIAL_INDIAN_STOCKS)))
    init_net_worth = to_dec(init_cash + stock_total_val)

    game = Game(
        code=code,
        name=req.name.strip(),
        status=GameStatus.LOBBY.value,
        trading_duration_sec=req.trading_duration_sec,
        settlement_duration_sec=req.settlement_duration_sec,
        scheduled_start_at=req.scheduled_start_at,
        initial_cash=init_cash,
        default_opening_price=open_px,
        default_shares_per_stock=req.default_shares_per_stock,
        initial_net_worth=init_net_worth,
        initial_margin_ratio=to_dec(req.initial_margin_ratio),
        maintenance_margin_ratio=to_dec(req.maintenance_margin_ratio),
        critical_margin_ratio=to_dec(req.critical_margin_ratio),
        margin_call_grace_sec=req.margin_call_grace_sec,
        default_short_pool_shares=req.default_short_pool_shares,
        short_position_limit_per_stock=req.short_position_limit_per_stock,
        allow_simultaneous_long_short=req.allow_simultaneous_long_short,
        market_order_collar_pct=to_dec(req.market_order_collar_pct),
        settlement_vwap_window_sec=req.settlement_vwap_window_sec,
        settlement_liquidity_pivot_shares=req.settlement_liquidity_pivot_shares,
        settlement_collar_pct=to_dec(req.settlement_collar_pct),
        transaction_fee_bps=to_dec(req.transaction_fee_bps),
        created_by_admin_id=admin_user.id if admin_user else None,
    )
    session.add(game)
    await session.flush()

    now = datetime.now(timezone.utc)
    session.add(
        GamePhase(
            game_id=game.id,
            phase=GameStatus.LOBBY.value,
            entered_at=now,
            triggered_by="ADMIN_MANUAL" if admin_user else "SYSTEM_INIT",
            actor_user_id=admin_user.id if admin_user else None,
            notes="Game created and lobby opened with 5-stock Indian tournament universe.",
        )
    )

    for item in INITIAL_INDIAN_STOCKS:
        stock = Stock(
            game_id=game.id,
            symbol=item["symbol"],
            company_name=item["company_name"],
            sector=item["sector"],
            opening_price=open_px,
            initial_allocation_shares=req.default_shares_per_stock,
            tick_size=Decimal("0.0500"),
            lot_size=1,
            short_limit_per_player=req.short_position_limit_per_stock,
            trading_enabled=True,
        )
        session.add(stock)
        await session.flush()

        profile = CompanyProfile(
            stock_id=stock.id,
            sub_sectors=item["sub_sectors"],
            description=item["description"],
            factor_exposures=item["factor_exposures"],
            competitor_symbols=[],
            supply_chain_links=item["supply_chain_links"],
            base_volatility=item["base_volatility"],
            simulated_market_cap_cr=item["simulated_market_cap_cr"],
            simulated_pe_ratio=item["simulated_pe_ratio"],
        )
        session.add(profile)

        pool = BorrowingPoolInventory(
            game_id=game.id,
            stock_id=stock.id,
            total_pool_shares=req.default_short_pool_shares,
            available_pool_shares=req.default_short_pool_shares,
            reserved_pool_shares=0,
            borrowed_shares=0,
        )
        session.add(pool)

        ref_price = MarketReferencePrice(
            game_id=game.id,
            stock_id=stock.id,
            fundamental_ref_price=open_px,
            last_traded_price=open_px,
            has_trades=False,
            official_mtm_price=open_px,
            day_high=open_px,
            day_low=open_px,
        )
        session.add(ref_price)

        for interval_sec in (5, 60):
            session.add(
                MarketPriceHistory(
                    game_id=game.id,
                    stock_id=stock.id,
                    interval_sec=interval_sec,
                    bucket_start=_floor_bucket(now, interval_sec),
                    open_price=open_px,
                    high_price=open_px,
                    low_price=open_px,
                    close_price=open_px,
                    ref_price_close=open_px,
                    mtm_price_close=open_px,
                    volume=0,
                    trade_count=0,
                )
            )

    await record_audit_event(
        session,
        actor_user_id=admin_user.id if admin_user else None,
        actor_role=admin_user.role if admin_user else "SYSTEM",
        action_type="GAME_CREATED",
        target_type="GAME",
        target_id=str(game.id),
        game_id=game.id,
        after_state={"code": game.code, "name": game.name, "initial_net_worth": str(init_net_worth)},
        reason="Initial tournament game configuration",
    )
    await session.flush()
    return game


async def update_pregame_config(
    session: AsyncSession,
    game_id: uuid.UUID,
    req: UpdateGameConfigRequest,
    *,
    admin_user: User,
) -> Game:
    await acquire_game_lifecycle_lock(session, game_id)
    game = (await session.execute(select(Game).where(Game.id == game_id).with_for_update())).scalar_one_or_none()
    if game is None:
        raise ResourceNotFoundError("Game not found.")
    if game.status not in (GameStatus.DRAFT.value, GameStatus.LOBBY.value):
        raise InvalidGamePhaseError("Financial & allocation parameters can only be edited before trading starts.")

    has_initialized = (
        await session.execute(
            select(GameParticipant.id)
            .where(GameParticipant.game_id == game_id, GameParticipant.allocation_initialized.is_(True))
            .limit(1)
        )
    ).scalar_one_or_none()
    if has_initialized is not None and any(
        v is not None for v in (req.initial_cash, req.default_opening_price, req.default_shares_per_stock)
    ):
        raise InvalidGamePhaseError(
            "Participants have already received initial allocations; opening price/allocation cannot be altered."
        )

    before = {
        "initial_margin_ratio": str(game.initial_margin_ratio),
        "maintenance_margin_ratio": str(game.maintenance_margin_ratio),
        "default_short_pool_shares": game.default_short_pool_shares,
        "short_position_limit_per_stock": game.short_position_limit_per_stock,
    }

    for field, val in req.model_dump(exclude_none=True).items():
        setattr(game, field, to_dec(val) if isinstance(val, Decimal) else val)

    if game.maintenance_margin_ratio >= game.initial_margin_ratio:
        raise InvalidGamePhaseError("maintenance_margin_ratio must be strictly less than initial_margin_ratio.")

    stocks = (await session.execute(select(Stock).where(Stock.game_id == game_id))).scalars().all()
    if req.default_opening_price is not None or req.default_shares_per_stock is not None:
        for st in stocks:
            st.opening_price = to_dec(game.default_opening_price)
            st.initial_allocation_shares = game.default_shares_per_stock
            ref = (
                await session.execute(
                    select(MarketReferencePrice).where(
                        MarketReferencePrice.game_id == game_id,
                        MarketReferencePrice.stock_id == st.id,
                    )
                )
            ).scalar_one()
            ref.fundamental_ref_price = st.opening_price
            ref.last_traded_price = st.opening_price
            ref.official_mtm_price = st.opening_price
        game.initial_net_worth = to_dec(
            game.initial_cash + (game.default_opening_price * Decimal(game.default_shares_per_stock * len(stocks)))
        )

    if req.short_position_limit_per_stock is not None:
        for st in stocks:
            st.short_limit_per_player = req.short_position_limit_per_stock

    if req.default_short_pool_shares is not None:
        pools = (
            await session.execute(
                select(BorrowingPoolInventory).where(BorrowingPoolInventory.game_id == game_id).with_for_update()
            )
        ).scalars().all()
        for bp in pools:
            delta = req.default_short_pool_shares - bp.total_pool_shares
            if bp.available_pool_shares + delta < 0:
                raise InvalidGamePhaseError("Cannot shrink borrowing pool below already reserved/borrowed shares.")
            bp.total_pool_shares = req.default_short_pool_shares
            bp.available_pool_shares += delta

    await record_audit_event(
        session,
        actor_user_id=admin_user.id,
        actor_role=admin_user.role,
        action_type="GAME_CONFIG_UPDATED",
        target_type="GAME",
        target_id=str(game.id),
        game_id=game.id,
        before_state=before,
        after_state=req.model_dump(exclude_none=True),
        reason="Pre-game configuration update",
    )
    await session.flush()
    return game


async def join_and_initialize_participant(
    session: AsyncSession,
    *,
    game_id: uuid.UUID,
    user: User,
) -> GameParticipant:
    """
    Atomically and idempotently seat a player in a game and grant identical initial allocations:
      - 100 shares of each of the 5 stocks (@ ₹1,000 = ₹5,00,000)
      - ₹5,00,000 available cash
      - Total initial net worth = ₹10,00,000
    Calling this function multiple times for the same (game_id, user_id) is 100% idempotent
    and never duplicates cash or share grants.
    """
    if user.role != UserRole.PLAYER.value or user.participant is None:
        raise ForbiddenActionError("Only registered player accounts can join a tournament seat.")

    await acquire_game_lifecycle_lock(session, game_id)
    game = (await session.execute(select(Game).where(Game.id == game_id).with_for_update())).scalar_one_or_none()
    if game is None:
        raise ResourceNotFoundError("Game not found.")

    participant: Participant = user.participant
    existing_gp = (
        await session.execute(
            select(GameParticipant)
            .where(GameParticipant.game_id == game_id, GameParticipant.user_id == user.id)
            .with_for_update()
        )
    ).scalar_one_or_none()

    if existing_gp is not None and existing_gp.allocation_initialized:
        return existing_gp

    if game.status not in (GameStatus.DRAFT.value, GameStatus.LOBBY.value, GameStatus.MAIN_TRADING.value):
        raise InvalidGamePhaseError(f"Cannot join game in phase '{game.status}'.")

    if existing_gp is None:
        existing_gp = GameParticipant(
            game_id=game_id,
            participant_id=participant.id,
            user_id=user.id,
            allocation_initialized=False,
            allocation_idempotency_key=f"init:{game_id}:{participant.id}",
        )
        session.add(existing_gp)
        await session.flush()

    now = datetime.now(timezone.utc)
    portfolio = PlayerPortfolio(
        game_id=game_id,
        game_participant_id=existing_gp.id,
        available_cash=ZERO,
        order_reserved_cash=ZERO,
        short_margin_locked=ZERO,
        short_proceeds_locked=ZERO,
        unfunded_settlement_debt=ZERO,
        realized_pnl=ZERO,
        last_net_worth=game.initial_net_worth,
        net_worth_achieved_at=now,
    )
    session.add(portfolio)
    await session.flush()

    cash_alloc = InitialAllocation(
        game_id=game_id,
        game_participant_id=existing_gp.id,
        stock_id=None,
        allocation_key="CASH",
        asset_type=AssetType.CASH.value,
        quantity=None,
        cash_amount=game.initial_cash,
        valuation_at_open=game.initial_cash,
    )
    session.add(cash_alloc)
    await session.flush()

    await apply_cash_mutation(
        session,
        portfolio,
        entry_type=CashLedgerType.INITIAL_GRANT.value,
        reference_type="INIT",
        reference_id=cash_alloc.id,
        idempotency_key=f"init:cash:{existing_gp.id}",
        delta_available=game.initial_cash,
        notes="Initial tournament cash allocation",
    )

    stocks = (
        await session.execute(select(Stock).where(Stock.game_id == game_id).order_by(Stock.symbol))
    ).scalars().all()

    for st in stocks:
        holding = PlayerStockHolding(
            game_id=game_id,
            game_participant_id=existing_gp.id,
            stock_id=st.id,
            available_shares=0,
            reserved_shares=0,
            avg_entry_price=st.opening_price,
            realized_pnl=ZERO,
        )
        session.add(holding)

        short_pos = ShortPosition(
            game_id=game_id,
            game_participant_id=existing_gp.id,
            stock_id=st.id,
            borrowed_shares=0,
            pending_cover_shares=0,
            weighted_avg_open_price=ZERO,
            sale_proceeds_locked=ZERO,
            margin_collateral_locked=ZERO,
            realized_pnl=ZERO,
            margin_status=MarginStatus.HEALTHY.value,
        )
        session.add(short_pos)
        await session.flush()

        stock_val = to_dec(st.opening_price * Decimal(st.initial_allocation_shares))
        stock_alloc = InitialAllocation(
            game_id=game_id,
            game_participant_id=existing_gp.id,
            stock_id=st.id,
            allocation_key=st.symbol,
            asset_type=AssetType.STOCK.value,
            quantity=st.initial_allocation_shares,
            cash_amount=None,
            valuation_at_open=stock_val,
        )
        session.add(stock_alloc)
        await session.flush()

        await apply_share_mutation(
            session,
            game_id=game_id,
            game_participant_id=existing_gp.id,
            stock_id=st.id,
            holding=holding,
            short_pos=short_pos,
            entry_type=ShareLedgerType.INITIAL_GRANT.value,
            reference_type="INIT",
            reference_id=stock_alloc.id,
            idempotency_key=f"init:stock:{existing_gp.id}:{st.symbol}",
            delta_long_available=st.initial_allocation_shares,
        )

    # Dynamically scale borrowing pool if needed (50 * participant_count >= default_short_pool_shares)
    init_count_rows = (
        await session.execute(
            select(GameParticipant.id).where(
                GameParticipant.game_id == game_id,
                GameParticipant.allocation_initialized.is_(True),
            )
        )
    ).scalars().all()
    next_player_count = len(init_count_rows) + 1
    scaled_target = max(int(game.default_short_pool_shares), next_player_count * 50)
    if scaled_target > game.default_short_pool_shares:
        pools = (
            await session.execute(
                select(BorrowingPoolInventory).where(BorrowingPoolInventory.game_id == game_id).with_for_update()
            )
        ).scalars().all()
        for bp in pools:
            if bp.total_pool_shares < scaled_target:
                inc = scaled_target - bp.total_pool_shares
                bp.total_pool_shares = scaled_target
                bp.available_pool_shares += inc

    existing_gp.allocation_initialized = True
    await session.flush()
    return existing_gp
