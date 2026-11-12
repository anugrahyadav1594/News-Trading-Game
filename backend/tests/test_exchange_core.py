import asyncio
from datetime import datetime, timedelta, timezone
from decimal import Decimal
import uuid
import pytest
from sqlalchemy import select, text

from app.core.exceptions import (
    InsufficientFundsError,
    InsufficientSharesError,
)
from app.db.session import get_session_factory
from app.models.enums import OrderIntent, OrderPriceType, OrderStatus
from app.models.order import Order
from app.models.portfolio import PlayerPortfolio
from app.models.shorting import BorrowingPoolInventory
from app.models.stock import Stock
from app.modules.accounting.reconcile import verify_game_accounting_invariants
from app.modules.accounting.service import compute_participant_valuation
from app.modules.auth.schemas import RegisterPlayerRequest
from app.modules.auth.service import ensure_admin_user, get_user_by_id, register_player
from app.modules.matching.schemas import ModifyOrderRequest, PlaceOrderRequest
from app.modules.matching.service import (
    cancel_order,
    expire_stale_orders_for_stock,
    modify_order_cancel_replace,
    place_order,
)
from app.modules.settlement.service import start_main_trading
from app.modules.tournament.schemas import CreateGameRequest
from app.modules.tournament.service import create_game, join_and_initialize_participant


async def _setup_active_game_with_players(session, n_players: int = 3):
    tag = uuid.uuid4().hex[:6]
    admin = await ensure_admin_user(
        session,
        email=f"admin_{tag}@mtt.in",
        username=f"admin_{tag}",
        password="Password123!",
    )
    game = await create_game(
        session,
        CreateGameRequest(name=f"Exchange Test {tag}", code=f"EX-{tag.upper()}"),
        admin_user=admin,
    )
    seats = []
    users = []
    for i in range(n_players):
        reg = await register_player(
            session,
            RegisterPlayerRequest(
                email=f"p{i}_{tag}@mtt.in",
                username=f"p{i}_{tag}",
                password="Password123!",
                display_name=f"Player {i}",
            ),
        )
        u = await get_user_by_id(session, reg.user.user_id)
        gp = await join_and_initialize_participant(session, game_id=game.id, user=u)
        users.append(u)
        seats.append(gp)
    await start_main_trading(session, game.id, admin_user=admin)
    return game, admin, users, seats


@pytest.mark.asyncio
async def test_idempotent_initial_allocation_and_resting_price_match(db_session):
    async with db_session.begin():
        game, _, users, seats = await _setup_active_game_with_players(db_session, 2)
        # Call join_and_initialize_participant two additional times: must be strictly idempotent!
        gp_again_1 = await join_and_initialize_participant(db_session, game_id=game.id, user=users[0])
        gp_again_2 = await join_and_initialize_participant(db_session, game_id=game.id, user=users[0])
        assert gp_again_1.id == seats[0].id == gp_again_2.id

        val0 = await compute_participant_valuation(
            db_session,
            game_id=game.id,
            game_participant_id=seats[0].id,
            initial_net_worth=game.initial_net_worth,
        )
        assert val0.available_cash == Decimal("500000.0000")
        assert val0.long_market_value == Decimal("500000.0000")
        assert val0.net_worth == Decimal("1000000.0000")

        # Exact Master Prompt §5 Example:
        # Player B places existing SELL 10 RELIANCE @ ₹1,040
        sell_resp, sell_trades, _ = await place_order(
            db_session,
            game_id=game.id,
            game_participant_id=seats[1].id,
            req=PlaceOrderRequest(
                symbol="RELIANCE",
                intent=OrderIntent.SELL_LONG.value,
                price_type=OrderPriceType.LIMIT.value,
                quantity=10,
                limit_price=Decimal("1040.00"),
            ),
        )
        assert sell_resp.status == OrderStatus.OPEN.value
        assert len(sell_trades) == 0

        # Player A places BUY 10 RELIANCE @ ₹1,050 -> executes at resting ₹1,040!
        buy_resp, buy_trades, _ = await place_order(
            db_session,
            game_id=game.id,
            game_participant_id=seats[0].id,
            req=PlaceOrderRequest(
                symbol="RELIANCE",
                intent=OrderIntent.BUY_LONG.value,
                price_type=OrderPriceType.LIMIT.value,
                quantity=10,
                limit_price=Decimal("1050.00"),
                client_order_id="idem-key-001",
            ),
        )
        assert buy_resp.status == OrderStatus.FILLED.value
        assert len(buy_trades) == 1
        assert buy_trades[0].price == Decimal("1040.0000")
        assert buy_trades[0].quantity == 10

        # Duplicate idempotency key must NOT execute twice!
        dup_resp, dup_trades, _ = await place_order(
            db_session,
            game_id=game.id,
            game_participant_id=seats[0].id,
            req=PlaceOrderRequest(
                symbol="RELIANCE",
                intent=OrderIntent.BUY_LONG.value,
                price_type=OrderPriceType.LIMIT.value,
                quantity=10,
                limit_price=Decimal("1050.00"),
                client_order_id="idem-key-001",
            ),
        )
        assert dup_resp.id == buy_resp.id
        assert len(dup_trades) == 0

        pf_a = (
            await db_session.execute(
                select(PlayerPortfolio).where(PlayerPortfolio.game_participant_id == seats[0].id)
            )
        ).scalar_one()
        pf_b = (
            await db_session.execute(
                select(PlayerPortfolio).where(PlayerPortfolio.game_participant_id == seats[1].id)
            )
        ).scalar_one()
        # Player A paid ₹10,400 (₹100 price improvement refunded cleanly to available_cash!)
        assert pf_a.available_cash == Decimal("489600.0000")
        assert pf_a.order_reserved_cash == Decimal("0.0000")
        # Player B received ₹10,400
        assert pf_b.available_cash == Decimal("510400.0000")

        audit = await verify_game_accounting_invariants(db_session, game.id)
        assert audit.passed, audit.violations


@pytest.mark.asyncio
async def test_price_time_priority_partial_fills_cancel_modify_and_expiry(db_session):
    async with db_session.begin():
        game, _, _, seats = await _setup_active_game_with_players(db_session, 4)

        # Seat 1 places Ask 10 @ ₹1,020 (seq earlier)
        o1, _, _ = await place_order(
            db_session,
            game_id=game.id,
            game_participant_id=seats[1].id,
            req=PlaceOrderRequest(symbol="INFY", intent="SELL_LONG", price_type="LIMIT", quantity=10, limit_price=Decimal("1020.00")),
        )
        # Seat 2 places Ask 10 @ ₹1,015 (better lower price!)
        o2, _, _ = await place_order(
            db_session,
            game_id=game.id,
            game_participant_id=seats[2].id,
            req=PlaceOrderRequest(symbol="INFY", intent="SELL_LONG", price_type="LIMIT", quantity=10, limit_price=Decimal("1015.00")),
        )
        # Seat 3 places Ask 10 @ ₹1,020 (same price as Seat 1, later sequence!)
        o3, _, _ = await place_order(
            db_session,
            game_id=game.id,
            game_participant_id=seats[3].id,
            req=PlaceOrderRequest(symbol="INFY", intent="SELL_LONG", price_type="LIMIT", quantity=10, limit_price=Decimal("1020.00")),
        )

        # Seat 0 buys 16 shares @ ₹1,025 -> should fill 10 from o2 (@1015), then 6 from o1 (@1020), leaving o1 with 4 remaining and o3 untouched!
        b_resp, trades, _ = await place_order(
            db_session,
            game_id=game.id,
            game_participant_id=seats[0].id,
            req=PlaceOrderRequest(symbol="INFY", intent="BUY_LONG", price_type="LIMIT", quantity=16, limit_price=Decimal("1025.00")),
        )
        assert b_resp.status == OrderStatus.FILLED.value
        assert len(trades) == 2
        assert (trades[0].sell_order_id, trades[0].price, trades[0].quantity) == (o2.id, Decimal("1015.0000"), 10)
        assert (trades[1].sell_order_id, trades[1].price, trades[1].quantity) == (o1.id, Decimal("1020.0000"), 6)

        o1_db = (await db_session.execute(select(Order).where(Order.id == o1.id))).scalar_one()
        o3_db = (await db_session.execute(select(Order).where(Order.id == o3.id))).scalar_one()
        assert o1_db.status == OrderStatus.PARTIALLY_FILLED.value and o1_db.remaining_quantity == 4
        assert o3_db.status == OrderStatus.OPEN.value and o3_db.remaining_quantity == 10

        # Cancel-and-replace o3 -> change price to ₹1,018 for 8 shares
        mod_resp, _, _ = await modify_order_cancel_replace(
            db_session,
            game_id=game.id,
            order_id=o3.id,
            game_participant_id=seats[3].id,
            req=ModifyOrderRequest(quantity=8, limit_price=Decimal("1018.00")),
        )
        assert mod_resp.status == OrderStatus.OPEN.value
        assert mod_resp.quantity == 8

        # Cancel partially filled o1 -> releases remaining 4 reserved shares
        canc_resp = await cancel_order(
            db_session,
            game_id=game.id,
            order_id=o1.id,
            actor_participant_id=seats[1].id,
        )
        assert canc_resp.status == OrderStatus.CANCELLED.value

        # Order expiry test: place GTD order with expires_in_sec=5 and advance clock
        exp_ord, _, _ = await place_order(
            db_session,
            game_id=game.id,
            game_participant_id=seats[0].id,
            req=PlaceOrderRequest(
                symbol="INFY",
                intent="BUY_LONG",
                price_type="LIMIT",
                quantity=5,
                limit_price=Decimal("980.00"),
                time_in_force="GTD",
                expires_in_sec=5,
            ),
        )
        st_infy = (await db_session.execute(select(Stock).where(Stock.game_id == game.id, Stock.symbol == "INFY"))).scalar_one()
        bp_infy = (await db_session.execute(select(BorrowingPoolInventory).where(BorrowingPoolInventory.stock_id == st_infy.id))).scalar_one()
        expired_list = await expire_stale_orders_for_stock(
            db_session,
            game=game,
            stock=st_infy,
            pool=bp_infy,
            now=datetime.now(timezone.utc) + timedelta(seconds=10),
        )
        assert any(o.id == exp_ord.id and o.status == OrderStatus.EXPIRED.value for o in expired_list)

        audit = await verify_game_accounting_invariants(db_session, game.id)
        assert audit.passed, audit.violations


@pytest.mark.asyncio
async def test_insufficient_balance_and_concurrent_double_spend_protection(test_app):
    factory = get_session_factory()
    async with factory() as s:
        async with s.begin():
            game, _, _, seats = await _setup_active_game_with_players(s, 2)
            gid = game.id
            p0_id = seats[0].id

    # 1. Insufficient cash (> ₹5,00,000) must fail
    async with factory() as s:
        with pytest.raises(InsufficientFundsError):
            async with s.begin():
                await place_order(
                    s,
                    game_id=gid,
                    game_participant_id=p0_id,
                    req=PlaceOrderRequest(
                        symbol="RELIANCE",
                        intent="BUY_LONG",
                        price_type="LIMIT",
                        quantity=600,
                        limit_price=Decimal("1000.00"),
                    ),
                )

    # 2. Insufficient long shares (> 100 initial shares) must fail
    async with factory() as s:
        with pytest.raises(InsufficientSharesError):
            async with s.begin():
                await place_order(
                    s,
                    game_id=gid,
                    game_participant_id=p0_id,
                    req=PlaceOrderRequest(
                        symbol="RELIANCE",
                        intent="SELL_LONG",
                        price_type="LIMIT",
                        quantity=150,
                        limit_price=Decimal("1000.00"),
                    ),
                )

    # 3. Two simultaneous concurrent orders each trying to spend ₹4,00,000 out of ₹5,00,000 available cash:
    #    Exactly ONE must succeed and ONE must fail with InsufficientFundsError!
    async def submit_4lakh_order(sym: str):
        async with factory() as s_conc:
            async with s_conc.begin():
                return await place_order(
                    s_conc,
                    game_id=gid,
                    game_participant_id=p0_id,
                    req=PlaceOrderRequest(
                        symbol=sym,
                        intent="BUY_LONG",
                        price_type="LIMIT",
                        quantity=400,
                        limit_price=Decimal("1000.00"),
                    ),
                )

    results = await asyncio.gather(
        submit_4lakh_order("RELIANCE"),
        submit_4lakh_order("ICICIBANK"),
        return_exceptions=True,
    )
    successes = [r for r in results if not isinstance(r, Exception)]
    failures = [r for r in results if isinstance(r, InsufficientFundsError)]
    assert len(successes) == 1
    assert len(failures) == 1

    async with factory() as s_verify:
        audit = await verify_game_accounting_invariants(s_verify, gid)
        assert audit.passed, audit.violations


@pytest.mark.asyncio
async def test_postgres_ledger_immutability_trigger(db_session):
    async with db_session.begin():
        game, _, _, _ = await _setup_active_game_with_players(db_session, 1)

    with pytest.raises(Exception, match="immutable"):
        async with db_session.begin():
            await db_session.execute(
                text("UPDATE cash_ledger_entries SET delta_available = 9999999 WHERE game_id = :gid"),
                {"gid": str(game.id)},
            )
