from decimal import Decimal
import uuid
import pytest
from sqlalchemy import select

from app.models.enums import NewsApprovalStatus
from app.models.market import MarketReferencePrice
from app.models.news import EventImpactMapping, NewsEvent
from app.models.stock import Stock
from app.modules.accounting.reconcile import verify_game_accounting_invariants
from app.modules.news.schemas import (
    CreateCustomNewsRequest,
    CreateNewsCategoryRequest,
    CreateReversalEventRequest,
    GenerateNewsBatchRequest,
    ReleaseNewsRequest,
)
from app.modules.news.service import (
    create_custom_news_category,
    create_custom_news_event,
    create_event_reversal,
    ensure_builtin_news_categories,
    generate_news_library_for_game,
    release_or_schedule_news_event,
)
from app.modules.settlement.service import start_main_trading
from app.modules.tournament.schemas import CreateGameRequest
from app.modules.tournament.service import create_game
from app.modules.auth.service import ensure_admin_user


@pytest.mark.asyncio
async def test_news_categories_divergent_macro_chains_overlap_and_reversals(db_session):
    tag = uuid.uuid4().hex[:6]
    async with db_session.begin():
        admin = await ensure_admin_user(
            db_session,
            email=f"nadmin_{tag}@mtt.in",
            username=f"nadmin_{tag}",
            password="Password123!",
        )
        cats = await ensure_builtin_news_categories(db_session)
        assert len(cats) >= 25

        # Extensible 26th category without code changes
        custom_cat = await create_custom_news_category(
            db_session,
            CreateNewsCategoryRequest(
                code="SOVEREIGN_AI_COMPUTE",
                display_name="Sovereign AI Compute Policy",
                domain_group="Technology Policy",
                default_factors=["ai_cloud_deal_momentum"],
            ),
            admin_user=admin,
        )
        assert custom_cat.code == "SOVEREIGN_AI_COMPUTE"

        game = await create_game(
            db_session,
            CreateGameRequest(name=f"Market Sim {tag}", code=f"MK-{tag.upper()}"),
            admin_user=admin,
        )
        await start_main_trading(db_session, game.id, admin_user=admin)

        # Generate full 35-event library including 5-stage chains
        lib = await generate_news_library_for_game(
            db_session,
            game_id=game.id,
            req=GenerateNewsBatchRequest(count=35, include_chains=True, seed=42, auto_approve=True),
            admin_user=admin,
        )
        assert len(lib) == 35
        assert all("SIMULATION" in ev.simulation_label.upper() for ev in lib)

        # 1. Cross-sectional divergent macro event: USD/INR depreciation helps INFY & SUNPHARMA, hurts ICICIBANK/TATAMOTORS
        fx_ev = await create_custom_news_event(
            db_session,
            game_id=game.id,
            req=CreateCustomNewsRequest(
                category="INTERNATIONAL_TRADE",
                news_type="BREAKING",
                headline="INR Weakens Sharply vs USD",
                body="Simulated macro FX shock testing opposing company exposures.",
                factor_shocks={"usd_inr_depreciation": 1.0},
                severity=Decimal("0.80"),
                credibility=Decimal("1.00"),
                surprise_factor=Decimal("1.10"),
                permanent_fraction=Decimal("1.00"),
            ),
            admin_user=admin,
        )
        _, rel = await release_or_schedule_news_event(
            db_session,
            game_id=game.id,
            event_id=fx_ev.id,
            req=ReleaseNewsRequest(mode="IMMEDIATE"),
            admin_user=admin,
        )
        assert rel is not None
        post = {k: Decimal(v) for k, v in rel.post_release_ref_prices.items()}
        assert post["INFY"] > Decimal("1000.0000")
        assert post["SUNPHARMA"] > Decimal("1000.0000")
        assert post["TATAMOTORS"] < Decimal("1000.0000")
        assert post["ICICIBANK"] < Decimal("1000.0000")

        # 2. Full Event Reversal restores fundamental reference prices back to ₹1,000.00!
        rev_ev, rev_rel = await create_event_reversal(
            db_session,
            game_id=game.id,
            target_event_id=fx_ev.id,
            req=CreateReversalEventRequest(reversal_ratio=Decimal("1.0000"), release_immediately=True),
            admin_user=admin,
        )
        assert rev_ev.approval_status == NewsApprovalStatus.RELEASED.value
        assert rev_rel is not None
        restored = {k: Decimal(v) for k, v in rev_rel.post_release_ref_prices.items()}
        for sym in ("RELIANCE", "ICICIBANK", "TATAMOTORS", "SUNPHARMA", "INFY"):
            assert restored[sym] == Decimal("1000.0000")

        # 3. Overlapping events dampening: 2nd identical shock produces smaller marginal log impulse than 1st!
        ev_a = await create_custom_news_event(
            db_session,
            game_id=game.id,
            req=CreateCustomNewsRequest(
                category="PATENT_DISPUTES",
                headline="Sun Pharma Patent Win #1",
                body="Simulated positive shock 1.",
                primary_symbol="SUNPHARMA",
                direct_weights={"SUNPHARMA": 0.8},
                severity=Decimal("0.75"),
                credibility=Decimal("1.0"),
                surprise_factor=Decimal("1.0"),
            ),
            admin_user=admin,
        )
        ev_b = await create_custom_news_event(
            db_session,
            game_id=game.id,
            req=CreateCustomNewsRequest(
                category="PATENT_DISPUTES",
                headline="Sun Pharma Patent Win #2",
                body="Simulated overlapping positive shock 2.",
                primary_symbol="SUNPHARMA",
                direct_weights={"SUNPHARMA": 0.8},
                severity=Decimal("0.75"),
                credibility=Decimal("1.0"),
                surprise_factor=Decimal("1.0"),
            ),
            admin_user=admin,
        )
        await release_or_schedule_news_event(
            db_session, game_id=game.id, event_id=ev_a.id, req=ReleaseNewsRequest(mode="IMMEDIATE"), admin_user=admin
        )
        await release_or_schedule_news_event(
            db_session, game_id=game.id, event_id=ev_b.id, req=ReleaseNewsRequest(mode="IMMEDIATE"), admin_user=admin
        )
        m_a = (
            await db_session.execute(
                select(EventImpactMapping).where(
                    EventImpactMapping.news_event_id == ev_a.id,
                    EventImpactMapping.symbol == "SUNPHARMA",
                )
            )
        ).scalar_one()
        m_b = (
            await db_session.execute(
                select(EventImpactMapping).where(
                    EventImpactMapping.news_event_id == ev_b.id,
                    EventImpactMapping.symbol == "SUNPHARMA",
                )
            )
        ).scalar_one()
        assert m_b.applied_log_impulse < m_a.applied_log_impulse


@pytest.mark.asyncio
async def test_rbac_security_and_anti_cheating_via_http(api_client):
    tag = uuid.uuid4().hex[:6]
    # Register two players
    r1 = await api_client.post(
        "/api/v1/auth/register",
        json={
            "email": f"sec1_{tag}@mtt.in",
            "username": f"sec1_{tag}",
            "password": "Password123!",
            "display_name": "Sec One",
        },
    )
    assert r1.status_code == 200
    tok1 = r1.json()["access_token"]

    # Player attempting to access Admin Game Creation MUST receive 403 FORBIDDEN!
    forb = await api_client.post(
        "/api/v1/admin/games",
        headers={"Authorization": f"Bearer {tok1}"},
        json={"name": "Unauthorized Hack Game"},
    )
    assert forb.status_code == 403


@pytest.mark.asyncio
async def test_demo_tournament_seeder_and_accounting_invariants(db_session, api_client):
    from app.models.game import Game
    from app.modules.accounting.reconcile import verify_game_accounting_invariants
    from app.modules.tournament.seed_demo import ensure_demo_tournament_seeded
    from sqlalchemy import select

    async with db_session.begin():
        await ensure_demo_tournament_seeded(db_session)
        # Idempotency check: second invocation must be a clean no-op
        await ensure_demo_tournament_seeded(db_session)

        live_game = (
            await db_session.execute(select(Game).where(Game.code == "MTT-ROUND1"))
        ).scalar_one()
        inv = await verify_game_accounting_invariants(db_session, live_game.id)
        assert inv.passed, f"Demo seeded game violated invariants: {inv.violations}"

    # Verify HTTP endpoints for seeded demo player & admin surveillance
    p_login = await api_client.post(
        "/api/v1/auth/login",
        json={"email": "aarav@mtt.in", "password": "MttPlayer@2026!"},
    )
    assert p_login.status_code == 200
    p_tok = p_login.json()["access_token"]

    games_res = await api_client.get(
        "/api/v1/games", headers={"Authorization": f"Bearer {p_tok}"}
    )
    assert games_res.status_code == 200
    round1 = next(g for g in games_res.json() if g["code"] == "MTT-ROUND1")

    pf_res = await api_client.get(
        f"/api/v1/games/{round1['id']}/portfolio",
        headers={"Authorization": f"Bearer {p_tok}"},
    )
    assert pf_res.status_code == 200
    assert len(pf_res.json()["long_holdings"]) == 5

    # Exercise all remaining Player & Admin HTTP endpoints end-to-end
    for path in (
        f"/api/v1/games/{round1['id']}/lobby",
        f"/api/v1/games/{round1['id']}/stocks",
        f"/api/v1/games/{round1['id']}/stocks/RELIANCE",
        f"/api/v1/games/{round1['id']}/stocks/RELIANCE/candles?interval_sec=5",
        f"/api/v1/games/{round1['id']}/news",
        f"/api/v1/games/{round1['id']}/leaderboard",
        f"/api/v1/games/{round1['id']}/orders",
        f"/api/v1/games/{round1['id']}/trades",
        f"/api/v1/games/{round1['id']}/state",
    ):
        r = await api_client.get(path, headers={"Authorization": f"Bearer {p_tok}"})
        assert r.status_code == 200, f"Failed GET {path}: {r.text}"

    a_login = await api_client.post(
        "/api/v1/auth/login",
        json={"email": "admin@quantrelic-mtt.in", "password": "MttAdmin@2026!"},
    )
    assert a_login.status_code == 200
    a_tok = a_login.json()["access_token"]

    for admin_path in (
        f"/api/v1/admin/games/{round1['id']}/surveillance",
        f"/api/v1/admin/games/{round1['id']}/news",
        f"/api/v1/admin/games/{round1['id']}/audit-logs",
        "/api/v1/admin/news/categories",
    ):
        ar = await api_client.get(admin_path, headers={"Authorization": f"Bearer {a_tok}"})
        assert ar.status_code == 200, f"Failed GET {admin_path}: {ar.text}"

    # Verify HTTP POST/PUT/DELETE order placement, modification, and cancellation
    ord_post = await api_client.post(
        f"/api/v1/games/{round1['id']}/orders",
        headers={"Authorization": f"Bearer {p_tok}"},
        json={
            "symbol": "RELIANCE",
            "intent": "BUY_LONG",
            "price_type": "LIMIT",
            "quantity": 5,
            "limit_price": "980.00",
        },
    )
    assert ord_post.status_code == 200, ord_post.text
    oid = ord_post.json()["id"]

    ord_put = await api_client.put(
        f"/api/v1/games/{round1['id']}/orders/{oid}",
        headers={"Authorization": f"Bearer {p_tok}"},
        json={"quantity": 6, "limit_price": "981.00"},
    )
    assert ord_put.status_code == 200, ord_put.text
    new_oid = ord_put.json()["id"]

    ord_del = await api_client.delete(
        f"/api/v1/games/{round1['id']}/orders/{new_oid}",
        headers={"Authorization": f"Bearer {p_tok}"},
    )
    assert ord_del.status_code == 200, ord_del.text

