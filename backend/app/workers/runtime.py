import asyncio
import logging
import uuid
from datetime import datetime, timezone
from sqlalchemy import select

from app.api.v1.games import build_stocks_watchlist
from app.core.config import get_settings
from app.core.decimal_utils import to_dec
from app.db.session import get_session_factory
from app.models.enums import GameStatus
from app.models.game import Game
from app.models.market import MarketReferencePrice
from app.models.stock import Stock
from app.modules.matching.service import get_order_book_depth
from app.modules.pricing.service import recompute_stock_market_metrics
from app.modules.realtime.hub import ws_hub
from app.modules.settlement.service import (
    build_and_persist_leaderboard,
    tick_authoritative_game_clock,
)
from app.modules.shorting.service import evaluate_and_enforce_margins
from app.modules.tournament.service import compute_clock_state

logger = logging.getLogger(__name__)


class BackgroundEngineLoops:
    def __init__(self) -> None:
        self._tasks: list[asyncio.Task] = []
        self._running = False

    def start(self) -> None:
        if self._running:
            return
        self._running = True
        self._tasks = [
            asyncio.create_task(self._clock_and_risk_loop(), name="mtt-clock-loop"),
            asyncio.create_task(self._market_conflation_loop(), name="mtt-market-conflator"),
            asyncio.create_task(self._leaderboard_conflation_loop(), name="mtt-leaderboard-conflator"),
        ]

    async def stop(self) -> None:
        self._running = False
        for t in self._tasks:
            t.cancel()
        if self._tasks:
            await asyncio.gather(*self._tasks, return_exceptions=True)
        self._tasks.clear()

    async def _clock_and_risk_loop(self) -> None:
        factory = get_session_factory()
        while self._running:
            try:
                async with factory() as session:
                    active_games = (
                        await session.execute(
                            select(Game.id).where(
                                Game.status.in_(
                                    [
                                        GameStatus.LOBBY.value,
                                        GameStatus.MAIN_TRADING.value,
                                        GameStatus.PAUSED.value,
                                        GameStatus.SHORT_SETTLEMENT.value,
                                    ]
                                )
                            )
                        )
                    ).scalars().all()

                for gid in active_games:
                    async with factory() as session:
                        async with session.begin():
                            triggered = await tick_authoritative_game_clock(session, gid)
                            game = (await session.execute(select(Game).where(Game.id == gid))).scalar_one()
                            now = datetime.now(timezone.utc)

                            # Refresh decaying reference prices & candles during active phases
                            if game.status in (GameStatus.MAIN_TRADING.value, GameStatus.SHORT_SETTLEMENT.value):
                                stocks = (
                                    await session.execute(select(Stock).where(Stock.game_id == gid))
                                ).scalars().all()
                                for st in stocks:
                                    ref = (
                                        await session.execute(
                                            select(MarketReferencePrice)
                                            .where(
                                                MarketReferencePrice.game_id == gid,
                                                MarketReferencePrice.stock_id == st.id,
                                            )
                                            .with_for_update()
                                        )
                                    ).scalar_one()
                                    await recompute_stock_market_metrics(
                                        session, game=game, stock=st, ref_row=ref, now=now
                                    )
                                margin_events = await evaluate_and_enforce_margins(session, gid, now=now)
                            else:
                                margin_events = []

                            clock = compute_clock_state(game, now)

                    for ev in triggered:
                        if ev["event"] == "PHASE_CHANGED":
                            await ws_hub.broadcast_public(
                                game_id=gid,
                                channel="public:clock",
                                event="PHASE_CHANGED",
                                phase=ev["new_phase"],
                                game_elapsed_ms=clock.trading_elapsed_ms,
                                payload=ev,
                            )
                            ws_hub._dirty_leaderboard_games.add(gid)
                        elif ev["event"] == "NEWS_RELEASED":
                            for sym in ("RELIANCE", "ICICIBANK", "TATAMOTORS", "SUNPHARMA", "INFY"):
                                ws_hub.mark_stock_dirty(gid, sym)
                            await ws_hub.broadcast_public(
                                game_id=gid,
                                channel="public:news",
                                event="NEWS_RELEASED",
                                phase=game.status,
                                game_elapsed_ms=clock.trading_elapsed_ms,
                                payload=ev,
                            )

                    for mev in margin_events:
                        await ws_hub.send_private_to_participant(
                            game_id=gid,
                            game_participant_id=mev["game_participant_id"],
                            event="MARGIN_ALERT",
                            phase=game.status,
                            game_elapsed_ms=clock.trading_elapsed_ms,
                            payload=mev,
                        )

                    if gid in ws_hub.active_games_with_clients():
                        await ws_hub.broadcast_public(
                            game_id=gid,
                            channel="public:clock",
                            event="CLOCK_SYNC",
                            phase=game.status,
                            game_elapsed_ms=clock.trading_elapsed_ms,
                            payload=clock.model_dump(mode="json"),
                        )
            except asyncio.CancelledError:
                break
            except Exception:
                logger.exception("Error in authoritative clock/risk worker loop")

            await asyncio.sleep(1.0)

    async def _market_conflation_loop(self) -> None:
        settings = get_settings()
        interval = max(0.05, settings.WS_MARKET_TICK_MS / 1000.0)
        factory = get_session_factory()

        while self._running:
            try:
                for gid in list(ws_hub._dirty_stocks_by_game.keys()):
                    dirty_syms = ws_hub.pop_dirty_stocks(gid)
                    if not dirty_syms:
                        continue
                    async with factory() as session:
                        game = (await session.execute(select(Game).where(Game.id == gid))).scalar_one_or_none()
                        if game is None:
                            continue
                        clock = compute_clock_state(game)
                        watchlist = await build_stocks_watchlist(session, gid)
                        changed = [q for q in watchlist if q["symbol"] in dirty_syms]

                        await ws_hub.broadcast_public(
                            game_id=gid,
                            channel="public:tickers",
                            event="MARKET_TICK",
                            phase=game.status,
                            game_elapsed_ms=clock.trading_elapsed_ms,
                            payload={"stocks": changed},
                        )

                        for q in changed:
                            book = await get_order_book_depth(
                                session,
                                game_id=gid,
                                stock_id=uuid.UUID(q["stock_id"]),
                                levels=15,
                            )
                            await ws_hub.broadcast_public(
                                game_id=gid,
                                channel=f"public:book:{q['symbol']}",
                                event="ORDERBOOK_SNAPSHOT",
                                phase=game.status,
                                game_elapsed_ms=clock.trading_elapsed_ms,
                                payload={"symbol": q["symbol"], **book},
                            )
            except asyncio.CancelledError:
                break
            except Exception:
                logger.exception("Error in conflated market data loop")

            await asyncio.sleep(interval)

    async def _leaderboard_conflation_loop(self) -> None:
        settings = get_settings()
        interval = max(0.5, settings.WS_LEADERBOARD_TICK_MS / 1000.0)
        factory = get_session_factory()

        while self._running:
            try:
                dirty_games = ws_hub.pop_dirty_leaderboard_games()
                for gid in dirty_games:
                    if gid not in ws_hub.active_games_with_clients():
                        continue
                    async with factory() as session:
                        async with session.begin():
                            game = (await session.execute(select(Game).where(Game.id == gid))).scalar_one_or_none()
                            if game is None:
                                continue
                            clock = compute_clock_state(game)
                            snaps = await build_and_persist_leaderboard(session, game=game)
                            top_entries = [
                                {
                                    "rank": s.rank,
                                    "tournament_code": s.tournament_code,
                                    "display_name": s.display_name,
                                    "final_net_worth": str(to_dec(s.final_net_worth)),
                                    "net_pnl": str(to_dec(s.net_pnl)),
                                    "return_pct": str(to_dec(s.return_pct)),
                                }
                                for s in snaps[:20]
                            ]
                    await ws_hub.broadcast_public(
                        game_id=gid,
                        channel="public:leaderboard",
                        event="LEADERBOARD_UPDATE",
                        phase=game.status,
                        game_elapsed_ms=clock.trading_elapsed_ms,
                        payload={"top": top_entries},
                    )
            except asyncio.CancelledError:
                break
            except Exception:
                logger.exception("Error in conflated leaderboard loop")

            await asyncio.sleep(interval)


background_loops = BackgroundEngineLoops()
