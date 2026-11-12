import math
from datetime import datetime, timedelta, timezone
from decimal import Decimal
import uuid
import pytest
from sqlalchemy import select

from app.core.exceptions import (
    BorrowPoolExhaustedError,
    InvalidGamePhaseError,
    OrderValidationError,
)
from app.models.enums import GameStatus, MarginStatus, OrderStatus
from app.models.market import MarketReferencePrice
from app.models.portfolio import PlayerPortfolio
from app.models.shorting import ShortPosition
from app.models.stock import Stock
from app.modules.accounting.reconcile import verify_game_accounting_invariants
from app.modules.accounting.service import compute_participant_valuation
from app.modules.auth.schemas import RegisterPlayerRequest
from app.modules.auth.service import ensure_admin_user, get_user_by_id, register_player
from app.modules.matching.schemas import PlaceOrderRequest
from app.modules.matching.service import place_order
from app.modules.settlement.service import (
    enter_short_settlement_phase,
    finalize_settlement_and_complete_game,
    start_main_trading,
)
from app.modules.shorting.service import evaluate_and_enforce_margins
from app.modules.tournament.schemas import CreateGameRequest
from app.modules.tournament.service import create_game, join_and_initialize_participant


async def _create_short_test_game(session, *, pool_shares: int = 200, n_players: int = 3):
    tag = uuid.uuid4().hex[:6]
    admin = await ensure_admin_user(
        session,
        email=f"sadmin_{tag}@mtt.in",
        username=f"sadmin_{tag}",
        password="Password123!",
    )
    game = await create_game(
        session,
        CreateGameRequest(
            name=f"Shorting Test {tag}",
            code=f"SH-{tag.upper()}",
            default_short_pool_shares=pool_shares,
            short_position_limit_per_stock=300,
            initial_margin_ratio=Decimal("0.5000"),
            maintenance_margin_ratio=Decimal("0.2500"),
            critical_margin_ratio=Decimal("0.1250"),
            margin_call_grace_sec=30,
        ),
        admin_user=admin,
    )
    seats = []
    for i in range(n_players):
        reg = await register_player(
            session,
            RegisterPlayerRequest(
                email=f"sp{i}_{tag}@mtt.in",
                username=f"sp{i}_{tag}",
                password="Password123!",
                display_name=f"ShortTrader {i}",
            ),
        )
        u = await get_user_by_id(session, reg.user.user_id)
        gp = await join_and_initialize_participant(session, game_id=game.id, user=u)
        seats.append(gp)
    await start_main_trading(session, game.id, admin_user=admin)
    return game, admin, seats


@pytest.mark.asyncio
async def test_short_sale_zero_double_counting_cover_and_pool_exhaustion(db_session):
    async with db_session.begin():
        game, _, seats = await _create_short_test_game(db_session, pool_shares=150)

        # 1. Cannot short while still holding long shares when allow_simultaneous_long_short=False
        with pytest.raises(OrderValidationError):
            async with db_session.begin_nested():
                await place_order(
                    db_session,
                    game_id=game.id,
                    game_participant_id=seats[0].id,
                    req=PlaceOrderRequest(
                        symbol="TATAMOTORS",
                        intent="SHORT_SELL",
                        price_type="LIMIT",
                        quantity=20,
                        limit_price=Decimal("1000.00"),
                    ),
                )

        # 2. Seat 0 sells all 100 initial long shares of TATAMOTORS to Seat 1 @ ₹1,000
        await place_order(
            db_session,
            game_id=game.id,
            game_participant_id=seats[1].id,
            req=PlaceOrderRequest(
                symbol="TATAMOTORS", intent="BUY_LONG", price_type="LIMIT", quantity=100, limit_price=Decimal("1000.00")
            ),
        )
        await place_order(
            db_session,
            game_id=game.id,
            game_participant_id=seats[0].id,
            req=PlaceOrderRequest(
                symbol="TATAMOTORS", intent="SELL_LONG", price_type="LIMIT", quantity=100, limit_price=Decimal("1000.00")
            ),
        )

        # 3. Seat 0 Short Sells 50 shares of TATAMOTORS @ ₹1,000 to Seat 2!
        await place_order(
            db_session,
            game_id=game.id,
            game_participant_id=seats[2].id,
            req=PlaceOrderRequest(
                symbol="TATAMOTORS", intent="BUY_LONG", price_type="LIMIT", quantity=50, limit_price=Decimal("1000.00")
            ),
        )
        short_resp, s_trades, _ = await place_order(
            db_session,
            game_id=game.id,
            game_participant_id=seats[0].id,
            req=PlaceOrderRequest(
                symbol="TATAMOTORS", intent="SHORT_SELL", price_type="LIMIT", quantity=50, limit_price=Decimal("1000.00")
            ),
        )
        assert short_resp.status == OrderStatus.FILLED.value
        assert len(s_trades) == 1

        # Verify ZERO double-counting of short proceeds or collateral!
        val_s0 = await compute_participant_valuation(
            db_session,
            game_id=game.id,
            game_participant_id=seats[0].id,
            initial_net_worth=game.initial_net_worth,
        )
        assert val_s0.short_proceeds_locked == Decimal("50000.0000")
        assert val_s0.short_margin_locked == Decimal("25000.0000")  # 50% of ₹50,000
        assert val_s0.short_liability == Decimal("50000.0000")
        assert val_s0.net_worth == Decimal("1000000.0000")

        # 4. Borrowing pool exhaustion: 150 pool - 50 borrowed = 100 remaining; requesting 120 fails!
        with pytest.raises(BorrowPoolExhaustedError):
            async with db_session.begin_nested():
                await place_order(
                    db_session,
                    game_id=game.id,
                    game_participant_id=seats[0].id,
                    req=PlaceOrderRequest(
                        symbol="TATAMOTORS",
                        intent="SHORT_SELL",
                        price_type="LIMIT",
                        quantity=120,
                        limit_price=Decimal("1000.00"),
                    ),
                )

        # 5. Price drops: Seat 2 sells 50 @ ₹900; Seat 0 Buys to Cover 50 @ ₹900 -> +₹5,000 realized profit!
        await place_order(
            db_session,
            game_id=game.id,
            game_participant_id=seats[2].id,
            req=PlaceOrderRequest(
                symbol="TATAMOTORS", intent="SELL_LONG", price_type="LIMIT", quantity=50, limit_price=Decimal("900.00")
            ),
        )
        cov_resp, _, _ = await place_order(
            db_session,
            game_id=game.id,
            game_participant_id=seats[0].id,
            req=PlaceOrderRequest(
                symbol="TATAMOTORS", intent="BUY_TO_COVER", price_type="LIMIT", quantity=50, limit_price=Decimal("900.00")
            ),
        )
        assert cov_resp.status == OrderStatus.FILLED.value

        val_after = await compute_participant_valuation(
            db_session,
            game_id=game.id,
            game_participant_id=seats[0].id,
            initial_net_worth=game.initial_net_worth,
        )
        assert val_after.short_liability == Decimal("0.0000")
        assert val_after.short_proceeds_locked == Decimal("0.0000")
        assert val_after.short_margin_locked == Decimal("0.0000")
        assert val_after.realized_pnl == Decimal("5000.0000")

        audit = await verify_game_accounting_invariants(db_session, game.id)
        assert audit.passed, audit.violations


@pytest.mark.asyncio
async def test_margin_call_forced_liquidation_phase_b_and_unfunded_negative_net_worth(db_session):
    async with db_session.begin():
        game, admin, seats = await _create_short_test_game(db_session, pool_shares=500, n_players=4)

        # Seat 0 sells all 5 long holdings to Seat 1 so Seat 0 holds 0 long stocks & ₹10,00,000 cash
        for sym in ("RELIANCE", "ICICIBANK", "TATAMOTORS", "SUNPHARMA", "INFY"):
            await place_order(
                db_session,
                game_id=game.id,
                game_participant_id=seats[1].id,
                req=PlaceOrderRequest(symbol=sym, intent="BUY_LONG", price_type="LIMIT", quantity=100, limit_price=Decimal("1000.00")),
            )
            await place_order(
                db_session,
                game_id=game.id,
                game_participant_id=seats[0].id,
                req=PlaceOrderRequest(symbol=sym, intent="SELL_LONG", price_type="LIMIT", quantity=100, limit_price=Decimal("1000.00")),
            )

        # Seat 0 opens Short 40 RELIANCE @ ₹1,000 (matched with Seat 2)
        await place_order(
            db_session,
            game_id=game.id,
            game_participant_id=seats[2].id,
            req=PlaceOrderRequest(symbol="RELIANCE", intent="BUY_LONG", price_type="LIMIT", quantity=40, limit_price=Decimal("1000.00")),
        )
        await place_order(
            db_session,
            game_id=game.id,
            game_participant_id=seats[0].id,
            req=PlaceOrderRequest(symbol="RELIANCE", intent="SHORT_SELL", price_type="LIMIT", quantity=40, limit_price=Decimal("1000.00")),
        )

        # Simulate sharp news-driven reference price jump in RELIANCE (~₹1,280 -> margin ratio < 25% maintenance)
        # Advance clock past settlement_vwap_window_sec (300s) so old ₹1,000 trade drops out of trailing VWAP window
        later_ts = datetime.now(timezone.utc) + timedelta(seconds=400)
        st_rel = (await db_session.execute(select(Stock).where(Stock.game_id == game.id, Stock.symbol == "RELIANCE"))).scalar_one()
        ref_rel = (
            await db_session.execute(
                select(MarketReferencePrice).where(MarketReferencePrice.stock_id == st_rel.id)
            )
        ).scalar_one()
        ref_rel.permanent_log_shift = Decimal(str(round(math.log(1.28), 6)))
        ref_rel.fundamental_ref_price = Decimal("1280.0000")
        ref_rel.official_mtm_price = Decimal("1280.0000")

        m_events_1 = await evaluate_and_enforce_margins(db_session, game.id, now=later_ts)
        assert any(e["type"] == "MARGIN_CALL" for e in m_events_1)

        # Post resting ask liquidity by Seat 2 at ₹1,285 so forced liquidation can execute on P2P book after grace expires!
        await place_order(
            db_session,
            game_id=game.id,
            game_participant_id=seats[2].id,
            req=PlaceOrderRequest(symbol="RELIANCE", intent="SELL_LONG", price_type="LIMIT", quantity=40, limit_price=Decimal("1285.00")),
        )
        # Re-evaluate at later_ts + 40s (grace = 30s exceeded; trailing VWAP window at later_ts+40s has 0 old trades -> MTM = ₹1,280)
        from app.modules.pricing.service import recompute_stock_market_metrics
        await recompute_stock_market_metrics(
            db_session, game=game, stock=st_rel, ref_row=ref_rel, now=later_ts + timedelta(seconds=40)
        )
        m_events_2 = await evaluate_and_enforce_margins(
            db_session, game.id, now=later_ts + timedelta(seconds=40)
        )
        assert any(e["type"] == "FORCED_LIQUIDATION" and e["filled_cover_qty"] == 40 for e in m_events_2)

        # Now test unsettled shorts & unfunded negative net worth at end of Phase B!
        # Seat 0 opens 300-share short positions across SUNPHARMA, TATAMOTORS, and ICICIBANK @ ₹1,000 (900 shares total)
        for sym in ("SUNPHARMA", "TATAMOTORS", "ICICIBANK"):
            # Seat 2 + Seat 3 provide 300 shares of buy demand @ ₹1,000 (each has >₹5,00,000 cash)
            await place_order(
                db_session,
                game_id=game.id,
                game_participant_id=seats[2].id,
                req=PlaceOrderRequest(symbol=sym, intent="BUY_LONG", price_type="LIMIT", quantity=150, limit_price=Decimal("1000.00")),
            )
            await place_order(
                db_session,
                game_id=game.id,
                game_participant_id=seats[3].id,
                req=PlaceOrderRequest(symbol=sym, intent="BUY_LONG", price_type="LIMIT", quantity=150, limit_price=Decimal("1000.00")),
            )
            await place_order(
                db_session,
                game_id=game.id,
                game_participant_id=seats[0].id,
                req=PlaceOrderRequest(symbol=sym, intent="SHORT_SELL", price_type="LIMIT", quantity=300, limit_price=Decimal("1000.00")),
            )

        pf0 = (await db_session.execute(select(PlayerPortfolio).where(PlayerPortfolio.game_participant_id == seats[0].id))).scalar_one()

        # Also place a resting BUY_LONG order to verify Phase B transition cancels resting opening orders!
        rest_buy, _, _ = await place_order(
            db_session,
            game_id=game.id,
            game_participant_id=seats[0].id,
            req=PlaceOrderRequest(symbol="INFY", intent="BUY_LONG", price_type="LIMIT", quantity=10, limit_price=Decimal("950.00")),
        )
        assert rest_buy.status == OrderStatus.OPEN.value

        # Enter Phase B (5-minute Short Position Settlement)
        _, cancelled_cnt = await enter_short_settlement_phase(db_session, game.id, admin_user=admin)
        assert cancelled_cnt == 1

        # New BUY_LONG or SHORT_SELL must be rejected during Phase B!
        with pytest.raises(InvalidGamePhaseError):
            async with db_session.begin_nested():
                await place_order(
                    db_session,
                    game_id=game.id,
                    game_participant_id=seats[0].id,
                    req=PlaceOrderRequest(symbol="INFY", intent="BUY_LONG", price_type="LIMIT", quantity=5, limit_price=Decimal("1000.00")),
                )

        # Positive fundamental shock (+0.85 log shift -> ~₹2,339.65) on all 3 shorted stocks
        # Total short obligation across 900 shares ≈ ₹21,05,685 > Seat 0's total cash (~₹18,88,600) -> Negative Net Worth!
        for sym in ("SUNPHARMA", "TATAMOTORS", "ICICIBANK"):
            st_obj = (await db_session.execute(select(Stock).where(Stock.game_id == game.id, Stock.symbol == sym))).scalar_one()
            ref_obj = (
                await db_session.execute(select(MarketReferencePrice).where(MarketReferencePrice.stock_id == st_obj.id))
            ).scalar_one()
            ref_obj.permanent_log_shift = Decimal("0.850000")

        # Finalize Phase B at T + 1200s (beyond 300s settlement VWAP window) -> Automatic Administrative Short Liquidation!
        completed_game, final_lb = await finalize_settlement_and_complete_game(
            db_session,
            game.id,
            admin_user=admin,
            now=later_ts + timedelta(seconds=1200),
        )
        assert completed_game.status == GameStatus.COMPLETED.value
        assert len(final_lb) == 4

        await db_session.refresh(pf0)
        # Seat 0's cash was exhausted to ₹0 and exact unpaid liability recorded in unfunded_settlement_debt (never waived!)
        assert pf0.available_cash == Decimal("0.0000")
        assert pf0.unfunded_settlement_debt > Decimal("0.0000")

        seat0_rank = next(s for s in final_lb if s.game_participant_id == seats[0].id)
        assert seat0_rank.final_net_worth < Decimal("0.0000")
        assert seat0_rank.final_net_worth == -pf0.unfunded_settlement_debt
        assert seat0_rank.rank == 4

        # Game is now strictly read-only
        with pytest.raises(InvalidGamePhaseError):
            async with db_session.begin_nested():
                await place_order(
                    db_session,
                    game_id=game.id,
                    game_participant_id=seats[1].id,
                    req=PlaceOrderRequest(symbol="INFY", intent="SELL_LONG", price_type="LIMIT", quantity=5, limit_price=Decimal("1000.00")),
                )

        audit = await verify_game_accounting_invariants(db_session, game.id)
        assert audit.passed, audit.violations
