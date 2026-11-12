import uuid
from decimal import Decimal
from typing import Any
from fastapi import APIRouter, Depends, Query
from sqlalchemy import asc, desc, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_active_participant_seat, get_current_user
from app.core.decimal_utils import HUNDRED, ZERO, to_dec
from app.core.exceptions import ResourceNotFoundError
from app.core.redis_bus import redis_bus
from app.db.session import atomic_tx, get_db_session
from app.models.enums import (
    GameStatus,
    LeaderboardSnapshotType,
    NewsApprovalStatus,
    OrderStatus,
    UserRole,
)
from app.models.game import Game, GameParticipant, InitialAllocation
from app.models.leaderboard import LeaderboardSnapshot
from app.models.market import MarketPriceHistory, MarketReferencePrice
from app.models.news import EventImpactMapping, NewsEvent, NewsRelease
from app.models.order import Order, Trade
from app.models.portfolio import PlayerPortfolio, PlayerStockHolding
from app.models.shorting import BorrowingPoolInventory, ShortPosition
from app.models.stock import CompanyProfile, Stock
from app.models.user import User
from app.modules.accounting.service import compute_participant_valuation
from app.modules.matching.service import get_order_book_depth, serialize_order
from app.modules.settlement.service import build_and_persist_leaderboard
from app.modules.shorting.service import compute_short_position_metrics
from app.modules.tournament.service import (
    compute_clock_state,
    join_and_initialize_participant,
)

router = APIRouter(prefix="/games", tags=["games & market"])


def _serialize_game_summary(game: Game, participant_count: int, joined: bool = False) -> dict[str, Any]:
    clock = compute_clock_state(game)
    return {
        "id": str(game.id),
        "code": game.code,
        "name": game.name,
        "status": game.status,
        "trading_duration_sec": game.trading_duration_sec,
        "settlement_duration_sec": game.settlement_duration_sec,
        "scheduled_start_at": game.scheduled_start_at.isoformat() if game.scheduled_start_at else None,
        "trading_started_at": game.trading_started_at.isoformat() if game.trading_started_at else None,
        "settlement_started_at": game.settlement_started_at.isoformat() if game.settlement_started_at else None,
        "completed_at": game.completed_at.isoformat() if game.completed_at else None,
        "initial_cash": str(game.initial_cash),
        "default_opening_price": str(game.default_opening_price),
        "default_shares_per_stock": game.default_shares_per_stock,
        "initial_net_worth": str(game.initial_net_worth),
        "initial_margin_ratio": str(game.initial_margin_ratio),
        "maintenance_margin_ratio": str(game.maintenance_margin_ratio),
        "short_position_limit_per_stock": game.short_position_limit_per_stock,
        "default_short_pool_shares": game.default_short_pool_shares,
        "allow_simultaneous_long_short": game.allow_simultaneous_long_short,
        "market_order_collar_pct": str(game.market_order_collar_pct),
        "participant_count": participant_count,
        "joined": joined,
        "clock": clock.model_dump(mode="json"),
        "simulation_disclaimer": "MTT TOURNAMENT SIMULATION — ALL PRICES, NEWS & TRADES ARE 100% FICTIONAL.",
    }


async def build_stocks_watchlist(session: AsyncSession, game_id: uuid.UUID) -> list[dict[str, Any]]:
    rows = (
        await session.execute(
            select(Stock, MarketReferencePrice, BorrowingPoolInventory, CompanyProfile)
            .join(
                MarketReferencePrice,
                (MarketReferencePrice.stock_id == Stock.id) & (MarketReferencePrice.game_id == game_id),
            )
            .join(
                BorrowingPoolInventory,
                (BorrowingPoolInventory.stock_id == Stock.id) & (BorrowingPoolInventory.game_id == game_id),
            )
            .join(CompanyProfile, CompanyProfile.stock_id == Stock.id)
            .where(Stock.game_id == game_id)
            .order_by(Stock.symbol)
        )
    ).all()

    out: list[dict[str, Any]] = []
    for st, ref, pool, prof in rows:
        open_px = to_dec(st.opening_price)
        ltp = to_dec(ref.last_traded_price)
        mtm = to_dec(ref.official_mtm_price)
        chg = to_dec(mtm - open_px)
        chg_pct = to_dec((chg / open_px) * HUNDRED) if open_px > ZERO else ZERO
        spread = (
            to_dec(ref.best_ask - ref.best_bid)
            if (ref.best_bid is not None and ref.best_ask is not None)
            else None
        )
        out.append(
            {
                "stock_id": str(st.id),
                "symbol": st.symbol,
                "company_name": st.company_name,
                "sector": st.sector,
                "sub_sectors": prof.sub_sectors,
                "opening_price": str(open_px),
                "fundamental_ref_price": str(to_dec(ref.fundamental_ref_price)),
                "last_traded_price": str(ltp),
                "has_trades": ref.has_trades,
                "best_bid": str(to_dec(ref.best_bid)) if ref.best_bid is not None else None,
                "best_ask": str(to_dec(ref.best_ask)) if ref.best_ask is not None else None,
                "spread": str(spread) if spread is not None else None,
                "official_mtm_price": str(mtm),
                "final_settlement_price": (
                    str(to_dec(ref.final_settlement_price)) if ref.final_settlement_price is not None else None
                ),
                "change": str(chg),
                "change_pct": str(chg_pct),
                "day_high": str(to_dec(ref.day_high)),
                "day_low": str(to_dec(ref.day_low)),
                "total_volume": ref.total_volume,
                "rolling_vwap": str(to_dec(ref.rolling_vwap)) if ref.rolling_vwap is not None else None,
                "realized_volatility_pct": str(to_dec(ref.realized_volatility_pct)),
                "trading_enabled": st.trading_enabled,
                "halt_reason": st.halt_reason,
                "tick_size": str(to_dec(st.tick_size)),
                "short_limit_per_player": st.short_limit_per_player,
                "borrowing_pool": {
                    "total_pool_shares": pool.total_pool_shares,
                    "available_pool_shares": pool.available_pool_shares,
                    "reserved_pool_shares": pool.reserved_pool_shares,
                    "borrowed_shares": pool.borrowed_shares,
                },
            }
        )
    return out


@router.get("")
async def api_list_games(
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_db_session),
) -> list[dict[str, Any]]:
    games = (await session.execute(select(Game).order_by(desc(Game.created_at)))).scalars().all()
    counts = dict(
        (
            await session.execute(
                select(GameParticipant.game_id, func.count(GameParticipant.id))
                .where(GameParticipant.allocation_initialized.is_(True))
                .group_by(GameParticipant.game_id)
            )
        ).all()
    )
    joined_ids = set(
        (
            await session.execute(
                select(GameParticipant.game_id).where(
                    GameParticipant.user_id == user.id,
                    GameParticipant.allocation_initialized.is_(True),
                )
            )
        ).scalars().all()
    )
    return [_serialize_game_summary(g, int(counts.get(g.id, 0)), g.id in joined_ids) for g in games]


@router.post("/{game_id}/join")
async def api_join_game(
    game_id: uuid.UUID,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_db_session),
) -> dict[str, Any]:
    async with atomic_tx(session):
        gp = await join_and_initialize_participant(session, game_id=game_id, user=user)
        game = (await session.execute(select(Game).where(Game.id == game_id))).scalar_one()
        val = await compute_participant_valuation(
            session,
            game_id=game_id,
            game_participant_id=gp.id,
            initial_net_worth=game.initial_net_worth,
        )
        return {
            "game_participant_id": str(gp.id),
            "game_id": str(game_id),
            "allocation_initialized": gp.allocation_initialized,
            "initial_net_worth": str(val.net_worth),
            "available_cash": str(val.available_cash),
            "long_market_value": str(val.long_market_value),
        }


@router.get("/{game_id}/lobby")
async def api_game_lobby(
    game_id: uuid.UUID,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_db_session),
) -> dict[str, Any]:
    game = (await session.execute(select(Game).where(Game.id == game_id))).scalar_one_or_none()
    if game is None:
        raise ResourceNotFoundError("Game not found.")
    cnt = int(
        (
            await session.execute(
                select(func.count(GameParticipant.id)).where(
                    GameParticipant.game_id == game_id,
                    GameParticipant.allocation_initialized.is_(True),
                )
            )
        ).scalar_one()
    )
    gp = (
        await session.execute(
            select(GameParticipant).where(GameParticipant.game_id == game_id, GameParticipant.user_id == user.id)
        )
    ).scalar_one_or_none()

    allocs = []
    if gp is not None:
        rows = (
            await session.execute(
                select(InitialAllocation)
                .where(InitialAllocation.game_participant_id == gp.id)
                .order_by(InitialAllocation.allocation_key)
            )
        ).scalars().all()
        allocs = [
            {
                "asset_key": r.allocation_key,
                "asset_type": r.asset_type,
                "quantity": r.quantity,
                "cash_amount": str(r.cash_amount) if r.cash_amount is not None else None,
                "valuation_at_open": str(r.valuation_at_open),
            }
            for r in rows
        ]

    stocks = await build_stocks_watchlist(session, game_id)
    return {
        "game": _serialize_game_summary(game, cnt, gp is not None and gp.allocation_initialized),
        "seat": {
            "joined": gp is not None and gp.allocation_initialized,
            "game_participant_id": str(gp.id) if gp else None,
            "tournament_code": user.participant.tournament_code if user.participant else None,
            "display_name": user.participant.display_name if user.participant else user.username,
        },
        "initial_allocations": allocs,
        "stocks": stocks,
        "rules": {
            "phase_a_main_trading_min": game.trading_duration_sec // 60,
            "phase_b_short_settlement_min": game.settlement_duration_sec // 60,
            "initial_cash_inr": str(game.initial_cash),
            "shares_per_stock": game.default_shares_per_stock,
            "opening_price_inr": str(game.default_opening_price),
            "initial_net_worth_inr": str(game.initial_net_worth),
            "initial_margin_pct": str(to_dec(game.initial_margin_ratio * HUNDRED)),
            "maintenance_margin_pct": str(to_dec(game.maintenance_margin_ratio * HUNDRED)),
            "short_limit_shares": game.short_position_limit_per_stock,
        },
    }


@router.get("/{game_id}/stocks")
async def api_list_stocks(
    game_id: uuid.UUID,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_db_session),
) -> list[dict[str, Any]]:
    return await build_stocks_watchlist(session, game_id)


@router.get("/{game_id}/stocks/{symbol}")
async def api_stock_detail(
    game_id: uuid.UUID,
    symbol: str,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_db_session),
) -> dict[str, Any]:
    sym = symbol.strip().upper()
    row = (
        await session.execute(
            select(Stock, CompanyProfile, MarketReferencePrice, BorrowingPoolInventory)
            .join(CompanyProfile, CompanyProfile.stock_id == Stock.id)
            .join(MarketReferencePrice, MarketReferencePrice.stock_id == Stock.id)
            .join(BorrowingPoolInventory, BorrowingPoolInventory.stock_id == Stock.id)
            .where(Stock.game_id == game_id, Stock.symbol == sym)
        )
    ).one_or_none()
    if row is None:
        raise ResourceNotFoundError(f"Stock '{sym}' not found.")

    st, prof, ref, pool = row
    game = (await session.execute(select(Game).where(Game.id == game_id))).scalar_one()
    book = await get_order_book_depth(session, game_id=game_id, stock_id=st.id, levels=20)

    recent_trades_rows = (
        await session.execute(
            select(Trade)
            .where(Trade.game_id == game_id, Trade.stock_id == st.id)
            .order_by(desc(Trade.trade_seq))
            .limit(40)
        )
    ).scalars().all()
    recent_trades = [
        {
            "id": str(t.id),
            "trade_seq": t.trade_seq,
            "price": str(to_dec(t.price)),
            "quantity": t.quantity,
            "notional_value": str(to_dec(t.notional_value)),
            "aggressor_side": t.aggressor_side,
            "executed_at": t.executed_at.isoformat(),
        }
        for t in recent_trades_rows
    ]

    # Released news affecting this company
    news_rows = (
        await session.execute(
            select(NewsEvent, EventImpactMapping)
            .join(EventImpactMapping, EventImpactMapping.news_event_id == NewsEvent.id)
            .where(
                NewsEvent.game_id == game_id,
                NewsEvent.approval_status == NewsApprovalStatus.RELEASED.value,
                EventImpactMapping.stock_id == st.id,
            )
            .order_by(desc(NewsEvent.released_at))
            .limit(30)
        )
    ).all()
    company_news = [
        {
            "id": str(ev.id),
            "event_code": ev.event_code,
            "category": ev.category,
            "news_type": ev.news_type,
            "headline": ev.headline,
            "body": ev.body,
            "direction": ev.direction,
            "released_at": ev.released_at.isoformat() if ev.released_at else None,
            "simulation_label": ev.simulation_label,
            "stock_estimated_pct_delta": str(to_dec(mp.estimated_pct_delta)),
        }
        for ev, mp in news_rows
        if abs(mp.raw_log_impulse) > Decimal("0.0001") or ev.primary_symbol == sym
    ]

    player_position = None
    if user.role == UserRole.PLAYER.value:
        gp = (
            await session.execute(
                select(GameParticipant).where(
                    GameParticipant.game_id == game_id,
                    GameParticipant.user_id == user.id,
                )
            )
        ).scalar_one_or_none()
        if gp and gp.allocation_initialized:
            holding = (
                await session.execute(
                    select(PlayerStockHolding).where(
                        PlayerStockHolding.game_participant_id == gp.id,
                        PlayerStockHolding.stock_id == st.id,
                    )
                )
            ).scalar_one()
            sp = (
                await session.execute(
                    select(ShortPosition).where(
                        ShortPosition.game_participant_id == gp.id,
                        ShortPosition.stock_id == st.id,
                    )
                )
            ).scalar_one()
            total_l = holding.available_shares + holding.reserved_shares
            mtm = to_dec(ref.official_mtm_price)
            player_position = {
                "long_available_shares": holding.available_shares,
                "long_reserved_shares": holding.reserved_shares,
                "long_total_shares": total_l,
                "long_avg_entry_price": str(to_dec(holding.avg_entry_price)),
                "long_market_value": str(to_dec(mtm * Decimal(total_l))),
                "long_unrealized_pnl": str(to_dec((mtm - holding.avg_entry_price) * Decimal(total_l))),
                "long_realized_pnl": str(to_dec(holding.realized_pnl)),
                "short": compute_short_position_metrics(sp, mtm, game.maintenance_margin_ratio),
            }

    watchlist = await build_stocks_watchlist(session, game_id)
    quote = next(x for x in watchlist if x["symbol"] == sym)

    return {
        "quote": quote,
        "profile": {
            "description": prof.description,
            "sub_sectors": prof.sub_sectors,
            "factor_exposures": prof.factor_exposures,
            "supply_chain_links": prof.supply_chain_links,
            "base_volatility": str(prof.base_volatility),
            "simulated_market_cap_cr": str(prof.simulated_market_cap_cr),
            "simulated_pe_ratio": str(prof.simulated_pe_ratio),
        },
        "order_book": book,
        "recent_trades": recent_trades,
        "company_news": company_news,
        "player_position": player_position,
    }


@router.get("/{game_id}/stocks/{symbol}/candles")
async def api_stock_candles(
    game_id: uuid.UUID,
    symbol: str,
    interval_sec: int = Query(default=5, description="5 or 60 seconds"),
    limit: int = Query(default=300, ge=10, le=1000),
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_db_session),
) -> list[dict[str, Any]]:
    iv = 60 if interval_sec >= 60 else 5
    stock = (
        await session.execute(
            select(Stock).where(Stock.game_id == game_id, Stock.symbol == symbol.strip().upper())
        )
    ).scalar_one_or_none()
    if stock is None:
        raise ResourceNotFoundError("Stock not found.")

    candles = (
        await session.execute(
            select(MarketPriceHistory)
            .where(
                MarketPriceHistory.game_id == game_id,
                MarketPriceHistory.stock_id == stock.id,
                MarketPriceHistory.interval_sec == iv,
            )
            .order_by(desc(MarketPriceHistory.bucket_start))
            .limit(limit)
        )
    ).scalars().all()

    return [
        {
            "time": int(c.bucket_start.timestamp()),
            "bucket_start": c.bucket_start.isoformat(),
            "open": float(c.open_price),
            "high": float(c.high_price),
            "low": float(c.low_price),
            "close": float(c.close_price),
            "ref_price": float(c.ref_price_close),
            "mtm_price": float(c.mtm_price_close),
            "volume": c.volume,
            "trade_count": c.trade_count,
        }
        for c in reversed(candles)
    ]


@router.get("/{game_id}/news")
async def api_released_news(
    game_id: uuid.UUID,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_db_session),
) -> list[dict[str, Any]]:
    rows = (
        await session.execute(
            select(NewsEvent, NewsRelease)
            .join(NewsRelease, NewsRelease.news_event_id == NewsEvent.id)
            .where(
                NewsEvent.game_id == game_id,
                NewsEvent.approval_status == NewsApprovalStatus.RELEASED.value,
            )
            .order_by(desc(NewsRelease.released_at))
            .limit(100)
        )
    ).all()

    out = []
    for ev, rel in rows:
        out.append(
            {
                "id": str(ev.id),
                "event_code": ev.event_code,
                "chain_id": str(ev.chain_id) if ev.chain_id else None,
                "chain_name": ev.chain_name,
                "chain_stage": ev.chain_stage,
                "chain_total_stages": ev.chain_total_stages,
                "category": ev.category,
                "news_type": ev.news_type,
                "headline": ev.headline,
                "body": ev.body,
                "primary_symbol": ev.primary_symbol,
                "secondary_symbols": ev.secondary_symbols,
                "affected_sectors": ev.affected_sectors,
                "direction": ev.direction,
                "severity": str(ev.severity),
                "credibility": str(ev.credibility),
                "game_elapsed_sec": rel.game_elapsed_sec,
                "released_at": rel.released_at.isoformat(),
                "simulation_label": ev.simulation_label,
            }
        )
    return out


@router.get("/{game_id}/leaderboard")
async def api_leaderboard(
    game_id: uuid.UUID,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_db_session),
) -> dict[str, Any]:
    async with atomic_tx(session):
        game = (await session.execute(select(Game).where(Game.id == game_id))).scalar_one_or_none()
        if game is None:
            raise ResourceNotFoundError("Game not found.")

        if game.status == GameStatus.COMPLETED.value:
            snaps = (
                await session.execute(
                    select(LeaderboardSnapshot)
                    .where(
                        LeaderboardSnapshot.game_id == game_id,
                        LeaderboardSnapshot.snapshot_type == LeaderboardSnapshotType.FINAL_OFFICIAL.value,
                    )
                    .order_by(asc(LeaderboardSnapshot.rank))
                )
            ).scalars().all()
            is_final = True
        else:
            snaps = await build_and_persist_leaderboard(
                session,
                game=game,
                snapshot_type=LeaderboardSnapshotType.LIVE.value,
                use_final_settlement_price=False,
                make_immutable=False,
            )
            is_final = False

        my_gp_id = None
        if user.role == UserRole.PLAYER.value:
            my_gp_id = (
                await session.execute(
                    select(GameParticipant.id).where(
                        GameParticipant.game_id == game_id,
                        GameParticipant.user_id == user.id,
                    )
                )
            ).scalar_one_or_none()

        entries = [
            {
                "rank": s.rank,
                "game_participant_id": str(s.game_participant_id),
                "tournament_code": s.tournament_code,
                "display_name": s.display_name,
                "final_net_worth": str(to_dec(s.final_net_worth)),
                "net_pnl": str(to_dec(s.net_pnl)),
                "return_pct": str(to_dec(s.return_pct)),
                "realized_pnl": str(to_dec(s.realized_pnl)),
                "is_me": (my_gp_id is not None and s.game_participant_id == my_gp_id),
            }
            for s in snaps
        ]
        return {
            "game_id": str(game_id),
            "status": game.status,
            "is_final_official": is_final,
            "initial_net_worth": str(to_dec(game.initial_net_worth)),
            "entries": entries,
        }


@router.get("/{game_id}/state")
async def api_full_resync_state(
    game_id: uuid.UUID,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_db_session),
) -> dict[str, Any]:
    """Complete authoritative state snapshot used on page load and WebSocket reconnection."""
    game = (await session.execute(select(Game).where(Game.id == game_id))).scalar_one_or_none()
    if game is None:
        raise ResourceNotFoundError("Game not found.")

    cnt = int(
        (
            await session.execute(
                select(func.count(GameParticipant.id)).where(
                    GameParticipant.game_id == game_id,
                    GameParticipant.allocation_initialized.is_(True),
                )
            )
        ).scalar_one()
    )
    stocks = await build_stocks_watchlist(session, game_id)
    news = await api_released_news(game_id, user, session)
    seq = await redis_bus.current_game_seq(game_id)

    gp = (
        await session.execute(
            select(GameParticipant).where(GameParticipant.game_id == game_id, GameParticipant.user_id == user.id)
        )
    ).scalar_one_or_none()

    open_orders_out = []
    if gp and gp.allocation_initialized:
        sym_map = {uuid.UUID(s["stock_id"]): s["symbol"] for s in stocks}
        ords = (
            await session.execute(
                select(Order)
                .where(
                    Order.game_participant_id == gp.id,
                    Order.status.in_([OrderStatus.OPEN.value, OrderStatus.PARTIALLY_FILLED.value]),
                )
                .order_by(desc(Order.created_at))
            )
        ).scalars().all()
        open_orders_out = [
            serialize_order(o, sym_map.get(o.stock_id, "UNKNOWN")).model_dump(mode="json")
            for o in ords
        ]

    return {
        "last_seq": seq,
        "game": _serialize_game_summary(game, cnt, gp is not None and gp.allocation_initialized),
        "stocks": stocks,
        "news": news[:40],
        "open_orders": open_orders_out,
    }
