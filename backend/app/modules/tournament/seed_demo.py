import logging
from decimal import Decimal
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.models.game import Game, GameParticipant
from app.models.news import NewsEvent
from app.models.user import User
from app.modules.auth.schemas import RegisterPlayerRequest
from app.modules.auth.service import ensure_admin_user, get_user_by_id, register_player
from app.modules.matching.schemas import PlaceOrderRequest
from app.modules.matching.service import place_order
from app.modules.news.schemas import GenerateNewsBatchRequest, ReleaseNewsRequest
from app.modules.news.service import (
    ensure_builtin_news_categories,
    generate_news_library_for_game,
    release_or_schedule_news_event,
)
from app.modules.settlement.service import start_main_trading
from app.modules.tournament.schemas import CreateGameRequest
from app.modules.tournament.service import create_game, join_and_initialize_participant

logger = logging.getLogger(__name__)

DEMO_PLAYERS = [
    ("aarav@mtt.in", "aarav_mehta", "Aarav Mehta", "IIT Bombay"),
    ("diya@mtt.in", "diya_kulkarni", "Diya Kulkarni", "IIM Ahmedabad"),
    ("rohan@mtt.in", "rohan_deshmukh", "Rohan Deshmukh", "VJTI Mumbai"),
    ("ananya@mtt.in", "ananya_iyer", "Ananya Iyer", "ISI Kolkata"),
    ("kabir@mtt.in", "kabir_shah", "Kabir Shah", "JBIMS Mumbai"),
    ("meera@mtt.in", "meera_nair", "Meera Nair", "BITS Pilani"),
]


async def ensure_demo_tournament_seeded(session: AsyncSession) -> None:
    """
    Idempotently seed:
      1. Built-in 25 news categories.
      2. Default Tournament Director Admin (`admin@quantrelic-mtt.in` / `MttAdmin@2026!`).
      3. 6 Demo Participant accounts (`aarav@mtt.in` .. `meera@mtt.in`, password `MttPlayer@2026!`).
      4. Active Championship Game `MTT-ROUND1` with real peer-to-peer resting order books,
         initial trades, a 35-event news library, and 2 released simulated breaking news items,
         plus a `MTT-LOBBY` upcoming game for testing the Lobby countdown view.
    """
    settings = get_settings()
    await ensure_builtin_news_categories(session)

    admin = await ensure_admin_user(
        session,
        email=settings.DEFAULT_ADMIN_EMAIL,
        username="mtt_director",
        password=settings.DEFAULT_ADMIN_PASSWORD,
    )

    existing_live = (
        await session.execute(select(Game).where(Game.code == "MTT-ROUND1"))
    ).scalar_one_or_none()
    if existing_live is not None:
        return

    # 1. Create active tournament game MTT-ROUND1
    live_game = await create_game(
        session,
        CreateGameRequest(
            name="Mumbai Trading Tournament — Round 1 Live Championship",
            code="MTT-ROUND1",
            trading_duration_sec=2700,
            settlement_duration_sec=300,
        ),
        admin_user=admin,
    )

    # 2. Create upcoming lobby game MTT-LOBBY
    lobby_game = await create_game(
        session,
        CreateGameRequest(
            name="Mumbai Trading Tournament — Evening Qualifier Heat",
            code="MTT-LOBBY",
            trading_duration_sec=2700,
            settlement_duration_sec=300,
        ),
        admin_user=admin,
    )

    seats: list[GameParticipant] = []
    for email, uname, dname, inst in DEMO_PLAYERS:
        u = (await session.execute(select(User).where(User.email == email))).scalar_one_or_none()
        if u is None:
            reg = await register_player(
                session,
                RegisterPlayerRequest(
                    email=email,
                    username=uname,
                    password="MttPlayer@2026!",
                    display_name=dname,
                    institution=inst,
                ),
            )
            u = await get_user_by_id(session, reg.user.user_id)
        else:
            u = await get_user_by_id(session, u.id)

        gp_live = await join_and_initialize_participant(session, game_id=live_game.id, user=u)
        await join_and_initialize_participant(session, game_id=lobby_game.id, user=u)
        seats.append(gp_live)

    # 3. Generate 34-event structured news library for both games
    events = await generate_news_library_for_game(
        session,
        game_id=live_game.id,
        req=GenerateNewsBatchRequest(count=34, include_chains=True, seed=2026, auto_approve=True),
        admin_user=admin,
    )
    await generate_news_library_for_game(
        session,
        game_id=lobby_game.id,
        req=GenerateNewsBatchRequest(count=25, include_chains=True, seed=2027, auto_approve=True),
        admin_user=admin,
    )

    # 4. Start trading on MTT-ROUND1 and seed genuine peer-to-peer resting order books & initial executions
    await start_main_trading(session, live_game.id, admin_user=admin)

    # Release 2 opening simulated headlines so reference prices & news feed are immediately dynamic
    if len(events) >= 12:
        await release_or_schedule_news_event(
            session,
            game_id=live_game.id,
            event_id=events[0].id,
            req=ReleaseNewsRequest(mode="IMMEDIATE"),
            admin_user=admin,
        )
        await release_or_schedule_news_event(
            session,
            game_id=live_game.id,
            event_id=events[10].id,
            req=ReleaseNewsRequest(mode="IMMEDIATE"),
            admin_user=admin,
        )

    # Place real peer-to-peer limit orders across the 6 demo players so every stock has live two-sided depth & trades
    sample_book_orders = [
        # (seat_idx, symbol, intent, qty, price)
        (1, "RELIANCE", "SELL_LONG", 15, Decimal("1006.00")),
        (2, "RELIANCE", "SELL_LONG", 20, Decimal("1010.50")),
        (3, "RELIANCE", "BUY_LONG", 15, Decimal("997.50")),
        (4, "RELIANCE", "BUY_LONG", 25, Decimal("994.00")),
        (0, "RELIANCE", "BUY_LONG", 10, Decimal("1006.00")),  # Matches seat 1 -> prints ₹1006.00!

        (2, "ICICIBANK", "SELL_LONG", 20, Decimal("1008.00")),
        (3, "ICICIBANK", "SELL_LONG", 15, Decimal("1012.00")),
        (4, "ICICIBANK", "BUY_LONG", 20, Decimal("999.00")),
        (5, "ICICIBANK", "BUY_LONG", 18, Decimal("995.50")),
        (1, "ICICIBANK", "BUY_LONG", 12, Decimal("1008.00")),  # Prints ₹1008.00!

        (3, "TATAMOTORS", "SELL_LONG", 18, Decimal("1015.00")),
        (4, "TATAMOTORS", "SELL_LONG", 20, Decimal("1019.50")),
        (1, "TATAMOTORS", "BUY_LONG", 20, Decimal("1004.00")),
        (2, "TATAMOTORS", "BUY_LONG", 15, Decimal("1000.50")),
        (5, "TATAMOTORS", "BUY_LONG", 10, Decimal("1015.00")),  # Prints ₹1015.00!

        (4, "SUNPHARMA", "SELL_LONG", 15, Decimal("1022.00")),
        (5, "SUNPHARMA", "SELL_LONG", 20, Decimal("1026.00")),
        (0, "SUNPHARMA", "BUY_LONG", 15, Decimal("1012.00")),
        (2, "SUNPHARMA", "BUY_LONG", 20, Decimal("1008.50")),
        (1, "SUNPHARMA", "BUY_LONG", 8, Decimal("1022.00")),   # Prints ₹1022.00!

        (5, "INFY", "SELL_LONG", 20, Decimal("1005.00")),
        (1, "INFY", "SELL_LONG", 15, Decimal("1009.50")),
        (2, "INFY", "BUY_LONG", 20, Decimal("996.00")),
        (3, "INFY", "BUY_LONG", 25, Decimal("992.50")),
        (4, "INFY", "BUY_LONG", 10, Decimal("1005.00")),       # Prints ₹1005.00!
    ]
    for s_idx, sym, intent, qty, px in sample_book_orders:
        await place_order(
            session,
            game_id=live_game.id,
            game_participant_id=seats[s_idx].id,
            req=PlaceOrderRequest(
                symbol=sym,
                intent=intent,
                price_type="LIMIT",
                quantity=qty,
                limit_price=px,
            ),
        )

    logger.info(
        "Seeded demo MTT tournament games (MTT-ROUND1 live & MTT-LOBBY)",
        extra={"structured": {"live_game_id": str(live_game.id), "lobby_game_id": str(lobby_game.id)}},
    )
