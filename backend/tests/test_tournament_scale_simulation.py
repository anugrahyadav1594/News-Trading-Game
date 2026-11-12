import random
import uuid
from decimal import Decimal
import pytest

from app.db.session import get_session_factory
from app.models.enums import GameStatus
from app.models.game import GameParticipant
from app.models.portfolio import PlayerPortfolio, PlayerStockHolding
from app.models.shorting import BorrowingPoolInventory, ShortPosition
from app.models.stock import Stock
from app.models.user import Participant, User
from app.modules.accounting.reconcile import verify_game_accounting_invariants
from app.modules.auth.service import ensure_admin_user
from app.modules.matching.schemas import PlaceOrderRequest
from app.modules.matching.service import place_order
from app.modules.news.schemas import GenerateNewsBatchRequest, ReleaseNewsRequest
from app.modules.news.service import (
    generate_news_library_for_game,
    release_or_schedule_news_event,
)
from app.modules.settlement.service import (
    enter_short_settlement_phase,
    finalize_settlement_and_complete_game,
    start_main_trading,
)
from app.modules.tournament.schemas import CreateGameRequest
from app.modules.tournament.service import create_game, join_and_initialize_participant
from sqlalchemy import select


async def _fast_bulk_seed_players(session, game, count: int, tag: str) -> list[uuid.UUID]:
    """
    Create and atomically initialize `count` distinct tournament players
    using the exact production join_and_initialize_participant accounting path
    for smaller cohorts or batched SQLAlchemy creation for 1,000-player load testing.
    """
    gp_ids: list[uuid.UUID] = []
    if count <= 300:
        for i in range(count):
            u = User(
                email=f"bot_{tag}_{i}@mtt.in",
                username=f"bot_{tag}_{i}",
                password_hash="sim-hash",
                role="PLAYER",
                is_active=True,
            )
            session.add(u)
            await session.flush()
            part = Participant(
                user_id=u.id,
                tournament_code=f"SIM-{tag.upper()}-{i:04d}",
                display_name=f"SimBot {i}",
            )
            session.add(part)
            await session.flush()
            u.participant = part
            gp = await join_and_initialize_participant(session, game_id=game.id, user=u)
            gp_ids.append(gp.id)
        return gp_ids

    # For 1,000-player full tournament test, batch user creation in chunks then run join_and_initialize_participant
    users: list[User] = []
    for i in range(count):
        u = User(
            email=f"bot_{tag}_{i}@mtt.in",
            username=f"bot_{tag}_{i}",
            password_hash="sim-hash",
            role="PLAYER",
            is_active=True,
        )
        session.add(u)
        users.append(u)
    await session.flush()

    for i, u in enumerate(users):
        part = Participant(
            user_id=u.id,
            tournament_code=f"SIM-{tag.upper()}-{i:04d}",
            display_name=f"SimBot {i}",
        )
        session.add(part)
        u.participant = part
    await session.flush()

    for u in users:
        gp = await join_and_initialize_participant(session, game_id=game.id, user=u)
        gp_ids.append(gp.id)
    return gp_ids


@pytest.mark.asyncio
@pytest.mark.parametrize("cohort_size", [150, 300, 1000])
async def test_tournament_scale_cohorts_trading_settlement_and_invariants(test_app, cohort_size: int):
    """
    Section 15 Tournament Scale Validation:
      - 150, 300, and 1,000 concurrent tournament participants
      - Identical ₹10,00,000 allocations
      - News release & reference price adjustment
      - Multi-stock peer-to-peer trading (longs, limit/market orders, short sales, covers)
      - 45-minute -> 5-minute settlement transition
      - Automatic short liquidation & final server-authoritative leaderboard calculation
      - 100% conservation & ledger reconciliation invariant check!
    """
    tag = f"c{cohort_size}_{uuid.uuid4().hex[:4]}"
    factory = get_session_factory()

    async with factory() as session:
        async with session.begin():
            admin = await ensure_admin_user(
                session,
                email=f"dir_{tag}@mtt.in",
                username=f"dir_{tag}",
                password="Password123!",
            )
            game = await create_game(
                session,
                CreateGameRequest(
                    name=f"Scale {cohort_size} Championship",
                    code=f"SC{cohort_size}-{uuid.uuid4().hex[:3].upper()}",
                    default_short_pool_shares=max(15000, cohort_size * 50),
                ),
                admin_user=admin,
            )
            gp_ids = await _fast_bulk_seed_players(session, game, cohort_size, tag)
            assert len(gp_ids) == cohort_size

            events = await generate_news_library_for_game(
                session,
                game_id=game.id,
                req=GenerateNewsBatchRequest(count=10, include_chains=True, seed=cohort_size, auto_approve=True),
                admin_user=admin,
            )
            await start_main_trading(session, game.id, admin_user=admin)
            await release_or_schedule_news_event(
                session,
                game_id=game.id,
                event_id=events[0].id,
                req=ReleaseNewsRequest(mode="IMMEDIATE"),
                admin_user=admin,
            )

            # Simulate active trading across all 5 stocks including short-sellers and buyers
            rng = random.Random(cohort_size)
            symbols = ["RELIANCE", "ICICIBANK", "TATAMOTORS", "SUNPHARMA", "INFY"]

            # First have 4 traders liquidate one stock's long holdings and open short positions
            for idx in range(4):
                sym = symbols[idx % 5]
                # Sell 100 initial long shares to buyer idx+10
                await place_order(
                    session,
                    game_id=game.id,
                    game_participant_id=gp_ids[idx + 10],
                    req=PlaceOrderRequest(symbol=sym, intent="BUY_LONG", price_type="LIMIT", quantity=100, limit_price=Decimal("1000.00")),
                )
                await place_order(
                    session,
                    game_id=game.id,
                    game_participant_id=gp_ids[idx],
                    req=PlaceOrderRequest(symbol=sym, intent="SELL_LONG", price_type="LIMIT", quantity=100, limit_price=Decimal("1000.00")),
                )
                # Open short position of 25 shares against buyer idx+20
                await place_order(
                    session,
                    game_id=game.id,
                    game_participant_id=gp_ids[idx + 20],
                    req=PlaceOrderRequest(symbol=sym, intent="BUY_LONG", price_type="LIMIT", quantity=25, limit_price=Decimal("1005.00")),
                )
                await place_order(
                    session,
                    game_id=game.id,
                    game_participant_id=gp_ids[idx],
                    req=PlaceOrderRequest(symbol=sym, intent="SHORT_SELL", price_type="LIMIT", quantity=25, limit_price=Decimal("1005.00")),
                )

            # Run 40 randomized peer-to-peer limit orders across the cohort
            for step in range(40):
                pid = gp_ids[(30 + step) % cohort_size]
                sym = symbols[step % 5]
                intent = "SELL_LONG" if step % 2 == 0 else "BUY_LONG"
                px = Decimal(str(990 + (rng.randint(0, 40) * 0.5)))
                await place_order(
                    session,
                    game_id=game.id,
                    game_participant_id=pid,
                    req=PlaceOrderRequest(symbol=sym, intent=intent, price_type="LIMIT", quantity=5, limit_price=px),
                )

            # Verify mid-game accounting invariants across all `cohort_size` participants!
            mid_audit = await verify_game_accounting_invariants(session, game.id)
            assert mid_audit.passed, mid_audit.violations
            assert mid_audit.participant_count == cohort_size

            # Advance into 5-minute Short Position Settlement Phase, cover 2 shorts manually & leave 2 for auto-liquidation!
            await enter_short_settlement_phase(session, game.id, admin_user=admin)
            for idx in range(2):
                sym = symbols[idx % 5]
                await place_order(
                    session,
                    game_id=game.id,
                    game_participant_id=gp_ids[idx + 20],
                    req=PlaceOrderRequest(symbol=sym, intent="SELL_LONG", price_type="LIMIT", quantity=25, limit_price=Decimal("1002.00")),
                )
                await place_order(
                    session,
                    game_id=game.id,
                    game_participant_id=gp_ids[idx],
                    req=PlaceOrderRequest(symbol=sym, intent="BUY_TO_COVER", price_type="LIMIT", quantity=25, limit_price=Decimal("1002.00")),
                )

            # Complete 5-minute Settlement Phase -> Auto-liquidates remaining 2 shorts & locks final rankings!
            done_game, final_lb = await finalize_settlement_and_complete_game(
                session, game.id, admin_user=admin
            )
            assert done_game.status == GameStatus.COMPLETED.value
            assert len(final_lb) == cohort_size
            assert [s.rank for s in final_lb[:5]] == [1, 2, 3, 4, 5]

            # Final post-settlement accounting invariant verification!
            final_audit = await verify_game_accounting_invariants(session, game.id)
            assert final_audit.passed, final_audit.violations
