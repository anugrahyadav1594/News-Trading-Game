import uuid
from datetime import datetime, timezone
from typing import Any
from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, Field
from sqlalchemy import asc, desc, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import require_admin
from app.api.v1.games import _serialize_game_summary, build_stocks_watchlist
from app.core.decimal_utils import to_dec
from app.core.exceptions import InvalidGamePhaseError, ResourceNotFoundError
from app.db.locks import acquire_game_lifecycle_lock, acquire_stock_matching_lock
from app.db.session import atomic_tx, get_db_session
from app.models.audit import AuditLog
from app.models.enums import OrderStatus, UserRole
from app.models.game import Game, GameParticipant
from app.models.market import MarketReferencePrice
from app.models.news import EventImpactMapping, NewsCategoryRecord, NewsEvent
from app.models.order import Order, Trade
from app.models.shorting import ShortPosition
from app.models.stock import Stock
from app.models.user import Participant, User
from app.modules.accounting.reconcile import verify_game_accounting_invariants
from app.modules.audit.service import record_audit_event
from app.modules.auth.schemas import RegisterPlayerRequest
from app.modules.auth.service import get_user_by_id, register_player
from app.modules.matching.service import cancel_order, get_order_book_depth
from app.modules.news.schemas import (
    ApproveNewsRequest,
    CreateCustomNewsRequest,
    CreateNewsCategoryRequest,
    CreateReversalEventRequest,
    GenerateNewsBatchRequest,
    ReleaseNewsRequest,
    UpdateNewsEventRequest,
)
from app.modules.news.service import (
    create_custom_news_category,
    create_custom_news_event,
    create_event_reversal,
    ensure_builtin_news_categories,
    generate_news_library_for_game,
    release_or_schedule_news_event,
    set_news_approval,
    update_news_event,
)
from app.modules.realtime.hub import ws_hub
from app.modules.settlement.service import (
    build_and_persist_leaderboard,
    enter_short_settlement_phase,
    finalize_settlement_and_complete_game,
    pause_game,
    resume_game,
    start_main_trading,
)
from app.modules.shorting.service import compute_short_position_metrics
from app.modules.tournament.schemas import (
    BulkParticipantImportRequest,
    CreateGameRequest,
    UpdateGameConfigRequest,
)
from app.modules.tournament.service import (
    compute_clock_state,
    create_game,
    join_and_initialize_participant,
    update_pregame_config,
)

router = APIRouter(prefix="/admin", tags=["admin control room"])


class LifecycleActionRequest(BaseModel):
    reason: str = Field(default="Administrator control room action", max_length=300)


class ToggleStockTradingRequest(BaseModel):
    trading_enabled: bool
    reason: str = Field(min_length=3, max_length=255)


class EmergencyCancelOrdersRequest(BaseModel):
    symbol: str | None = None
    reason: str = Field(min_length=3, max_length=255)


class ToggleNewsHaltRequest(BaseModel):
    news_halted: bool
    reason: str = Field(min_length=3, max_length=255)


async def _serialize_news_event_admin(
    session: AsyncSession,
    ev: NewsEvent,
) -> dict[str, Any]:
    mappings = (
        await session.execute(
            select(EventImpactMapping)
            .where(EventImpactMapping.news_event_id == ev.id)
            .order_by(EventImpactMapping.symbol)
        )
    ).scalars().all()
    return {
        "id": str(ev.id),
        "event_code": ev.event_code,
        "chain_id": str(ev.chain_id) if ev.chain_id else None,
        "chain_name": ev.chain_name,
        "chain_stage": ev.chain_stage,
        "chain_total_stages": ev.chain_total_stages,
        "parent_event_id": str(ev.parent_event_id) if ev.parent_event_id else None,
        "reverses_event_id": str(ev.reverses_event_id) if ev.reverses_event_id else None,
        "category": ev.category,
        "news_type": ev.news_type,
        "headline": ev.headline,
        "body": ev.body,
        "primary_symbol": ev.primary_symbol,
        "secondary_symbols": ev.secondary_symbols,
        "affected_sectors": ev.affected_sectors,
        "factor_shocks": ev.factor_shocks,
        "direct_weights": ev.direct_weights,
        "indirect_weights": ev.indirect_weights,
        "direction": ev.direction,
        "severity": str(ev.severity),
        "credibility": str(ev.credibility),
        "surprise_factor": str(ev.surprise_factor),
        "impact_magnitude": str(ev.impact_magnitude),
        "permanent_fraction": str(ev.permanent_fraction),
        "expected_duration_sec": ev.expected_duration_sec,
        "approval_status": ev.approval_status,
        "scheduled_game_sec": ev.scheduled_game_sec,
        "released_at": ev.released_at.isoformat() if ev.released_at else None,
        "simulation_label": ev.simulation_label,
        "impacts": [
            {
                "symbol": m.symbol,
                "direct_exposure": str(m.direct_exposure),
                "indirect_exposure": str(m.indirect_exposure),
                "macro_sensitivity": str(m.macro_sensitivity),
                "combined_exposure": str(m.combined_exposure),
                "estimated_pct_delta": str(m.estimated_pct_delta),
                "applied_log_impulse": str(m.applied_log_impulse),
            }
            for m in mappings
        ],
    }


@router.post("/games")
async def api_admin_create_game(
    req: CreateGameRequest,
    admin: User = Depends(require_admin),
    session: AsyncSession = Depends(get_db_session),
) -> dict[str, Any]:
    async with atomic_tx(session):
        game = await create_game(session, req, admin_user=admin)
        return _serialize_game_summary(game, 0, False)


@router.patch("/games/{game_id}/config")
async def api_admin_update_config(
    game_id: uuid.UUID,
    req: UpdateGameConfigRequest,
    admin: User = Depends(require_admin),
    session: AsyncSession = Depends(get_db_session),
) -> dict[str, Any]:
    async with atomic_tx(session):
        game = await update_pregame_config(session, game_id, req, admin_user=admin)
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
        return _serialize_game_summary(game, cnt, False)


@router.post("/games/{game_id}/participants/import")
async def api_admin_import_participants(
    game_id: uuid.UUID,
    req: BulkParticipantImportRequest,
    admin: User = Depends(require_admin),
    session: AsyncSession = Depends(get_db_session),
) -> dict[str, Any]:
    seated: list[dict[str, str]] = []
    async with atomic_tx(session):
        for item in req.participants:
            existing_u = (
                await session.execute(select(User).where(func.lower(User.email) == item.email.strip().lower()))
            ).scalar_one_or_none()
            if existing_u is None:
                reg = await register_player(
                    session,
                    RegisterPlayerRequest(
                        email=item.email,
                        username=item.username,
                        password=item.password,
                        display_name=item.display_name,
                        institution=item.institution,
                    ),
                )
                u = await get_user_by_id(session, reg.user.user_id)
            else:
                u = await get_user_by_id(session, existing_u.id)
            if u.role == UserRole.PLAYER.value:
                gp = await join_and_initialize_participant(session, game_id=game_id, user=u)
                seated.append(
                    {
                        "game_participant_id": str(gp.id),
                        "email": u.email,
                        "tournament_code": u.participant.tournament_code if u.participant else "",
                        "display_name": u.participant.display_name if u.participant else u.username,
                    }
                )
        await record_audit_event(
            session,
            actor_user_id=admin.id,
            actor_role=admin.role,
            action_type="PARTICIPANTS_IMPORTED",
            target_type="GAME",
            target_id=str(game_id),
            game_id=game_id,
            after_state={"imported_count": len(seated)},
        )
    return {"imported_count": len(seated), "participants": seated}


@router.post("/games/{game_id}/lifecycle/{action}")
async def api_admin_lifecycle_action(
    game_id: uuid.UUID,
    action: str,
    req: LifecycleActionRequest = LifecycleActionRequest(),
    admin: User = Depends(require_admin),
    session: AsyncSession = Depends(get_db_session),
) -> dict[str, Any]:
    act = action.strip().lower()
    async with atomic_tx(session):
        if act == "start":
            game = await start_main_trading(session, game_id, admin_user=admin)
        elif act == "pause":
            game = await pause_game(session, game_id, admin_user=admin, reason=req.reason)
        elif act == "resume":
            game = await resume_game(session, game_id, admin_user=admin, reason=req.reason)
        elif act == "start-settlement":
            game, _ = await enter_short_settlement_phase(
                session, game_id, triggered_by="ADMIN_MANUAL", admin_user=admin
            )
        elif act in ("finalize", "emergency-settle"):
            game, _ = await finalize_settlement_and_complete_game(
                session,
                game_id,
                triggered_by="EMERGENCY" if act == "emergency-settle" else "ADMIN_MANUAL",
                admin_user=admin,
                reason=req.reason,
            )
        else:
            raise InvalidGamePhaseError(f"Unsupported lifecycle action '{action}'.")

        clock = compute_clock_state(game)
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
        summary = _serialize_game_summary(game, cnt, False)

    await ws_hub.broadcast_public(
        game_id=game_id,
        channel="public:clock",
        event="PHASE_CHANGED",
        phase=game.status,
        game_elapsed_ms=clock.trading_elapsed_ms,
        payload={"status": game.status, "clock": clock.model_dump(mode="json")},
    )
    return summary


# --- Admin News Studio ---

@router.get("/news/categories")
async def api_admin_list_categories(
    admin: User = Depends(require_admin),
    session: AsyncSession = Depends(get_db_session),
) -> list[dict[str, Any]]:
    async with atomic_tx(session):
        cats = await ensure_builtin_news_categories(session)
        return [
            {
                "code": c.code,
                "display_name": c.display_name,
                "domain_group": c.domain_group,
                "default_factors": c.default_factors,
                "is_builtin": c.is_builtin,
            }
            for c in cats
        ]


@router.post("/news/categories")
async def api_admin_create_category(
    req: CreateNewsCategoryRequest,
    admin: User = Depends(require_admin),
    session: AsyncSession = Depends(get_db_session),
) -> dict[str, Any]:
    async with atomic_tx(session):
        c = await create_custom_news_category(session, req, admin_user=admin)
        return {
            "code": c.code,
            "display_name": c.display_name,
            "domain_group": c.domain_group,
            "default_factors": c.default_factors,
            "is_builtin": c.is_builtin,
        }


@router.post("/games/{game_id}/news/generate")
async def api_admin_generate_news(
    game_id: uuid.UUID,
    req: GenerateNewsBatchRequest,
    admin: User = Depends(require_admin),
    session: AsyncSession = Depends(get_db_session),
) -> dict[str, Any]:
    async with atomic_tx(session):
        events = await generate_news_library_for_game(
            session, game_id=game_id, req=req, admin_user=admin
        )
        serialized = [await _serialize_news_event_admin(session, ev) for ev in events]
    return {"generated_count": len(serialized), "events": serialized}


@router.post("/games/{game_id}/news/custom")
async def api_admin_create_custom_news(
    game_id: uuid.UUID,
    req: CreateCustomNewsRequest,
    admin: User = Depends(require_admin),
    session: AsyncSession = Depends(get_db_session),
) -> dict[str, Any]:
    async with atomic_tx(session):
        ev = await create_custom_news_event(session, game_id=game_id, req=req, admin_user=admin)
        return await _serialize_news_event_admin(session, ev)


@router.get("/games/{game_id}/news")
async def api_admin_list_news(
    game_id: uuid.UUID,
    status: str | None = Query(default=None),
    admin: User = Depends(require_admin),
    session: AsyncSession = Depends(get_db_session),
) -> list[dict[str, Any]]:
    stmt = select(NewsEvent).where(NewsEvent.game_id == game_id)
    if status:
        stmt = stmt.where(NewsEvent.approval_status == status.upper())
    stmt = stmt.order_by(asc(NewsEvent.event_code))
    events = (await session.execute(stmt)).scalars().all()
    return [await _serialize_news_event_admin(session, ev) for ev in events]


@router.patch("/games/{game_id}/news/{event_id}")
async def api_admin_update_news(
    game_id: uuid.UUID,
    event_id: uuid.UUID,
    req: UpdateNewsEventRequest,
    admin: User = Depends(require_admin),
    session: AsyncSession = Depends(get_db_session),
) -> dict[str, Any]:
    async with atomic_tx(session):
        ev = await update_news_event(session, game_id=game_id, event_id=event_id, req=req, admin_user=admin)
        return await _serialize_news_event_admin(session, ev)


@router.post("/games/{game_id}/news/{event_id}/approve")
async def api_admin_approve_news(
    game_id: uuid.UUID,
    event_id: uuid.UUID,
    req: ApproveNewsRequest,
    admin: User = Depends(require_admin),
    session: AsyncSession = Depends(get_db_session),
) -> dict[str, Any]:
    async with atomic_tx(session):
        ev = await set_news_approval(
            session, game_id=game_id, event_id=event_id, approve=req.approve, admin_user=admin
        )
        return await _serialize_news_event_admin(session, ev)


@router.post("/games/{game_id}/news/{event_id}/release")
async def api_admin_release_news(
    game_id: uuid.UUID,
    event_id: uuid.UUID,
    req: ReleaseNewsRequest,
    admin: User = Depends(require_admin),
    session: AsyncSession = Depends(get_db_session),
) -> dict[str, Any]:
    async with atomic_tx(session):
        ev, rel = await release_or_schedule_news_event(
            session, game_id=game_id, event_id=event_id, req=req, admin_user=admin
        )
        game = (await session.execute(select(Game).where(Game.id == game_id))).scalar_one()
        clock = compute_clock_state(game)
        ev_data = await _serialize_news_event_admin(session, ev)

    if rel is not None:
        for sym in ("RELIANCE", "ICICIBANK", "TATAMOTORS", "SUNPHARMA", "INFY"):
            ws_hub.mark_stock_dirty(game_id, sym)
        await ws_hub.broadcast_public(
            game_id=game_id,
            channel="public:news",
            event="NEWS_RELEASED",
            phase=game.status,
            game_elapsed_ms=clock.trading_elapsed_ms,
            payload={
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
            },
        )
    return ev_data


@router.post("/games/{game_id}/news/{event_id}/reverse")
async def api_admin_reverse_news(
    game_id: uuid.UUID,
    event_id: uuid.UUID,
    req: CreateReversalEventRequest,
    admin: User = Depends(require_admin),
    session: AsyncSession = Depends(get_db_session),
) -> dict[str, Any]:
    async with atomic_tx(session):
        ev, rel = await create_event_reversal(
            session, game_id=game_id, target_event_id=event_id, req=req, admin_user=admin
        )
        game = (await session.execute(select(Game).where(Game.id == game_id))).scalar_one()
        clock = compute_clock_state(game)
        ev_data = await _serialize_news_event_admin(session, ev)

    if rel is not None:
        for sym in ("RELIANCE", "ICICIBANK", "TATAMOTORS", "SUNPHARMA", "INFY"):
            ws_hub.mark_stock_dirty(game_id, sym)
        await ws_hub.broadcast_public(
            game_id=game_id,
            channel="public:news",
            event="NEWS_RELEASED",
            phase=game.status,
            game_elapsed_ms=clock.trading_elapsed_ms,
            payload={
                "id": str(ev.id),
                "event_code": ev.event_code,
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
            },
        )
    return ev_data


# --- Exchange Surveillance & Emergency Controls ---

@router.get("/games/{game_id}/surveillance")
async def api_admin_surveillance(
    game_id: uuid.UUID,
    admin: User = Depends(require_admin),
    session: AsyncSession = Depends(get_db_session),
) -> dict[str, Any]:
    game = (await session.execute(select(Game).where(Game.id == game_id))).scalar_one_or_none()
    if game is None:
        raise ResourceNotFoundError("Game not found.")

    stocks = await build_stocks_watchlist(session, game_id)
    books: dict[str, Any] = {}
    for s in stocks:
        books[s["symbol"]] = await get_order_book_depth(
            session, game_id=game_id, stock_id=uuid.UUID(s["stock_id"]), levels=10
        )

    open_orders_rows = (
        await session.execute(
            select(Order, Stock.symbol, Participant.tournament_code, Participant.display_name)
            .join(Stock, Stock.id == Order.stock_id)
            .join(GameParticipant, GameParticipant.id == Order.game_participant_id)
            .join(Participant, Participant.id == GameParticipant.participant_id)
            .where(
                Order.game_id == game_id,
                Order.status.in_([OrderStatus.OPEN.value, OrderStatus.PARTIALLY_FILLED.value]),
            )
            .order_by(desc(Order.created_at))
            .limit(100)
        )
    ).all()
    open_orders = [
        {
            "id": str(o.id),
            "symbol": sym,
            "tournament_code": tcode,
            "display_name": dname,
            "intent": o.intent,
            "side": o.side,
            "price_type": o.price_type,
            "limit_price": str(to_dec(o.limit_price)) if o.limit_price else None,
            "quantity": o.quantity,
            "remaining_quantity": o.remaining_quantity,
            "status": o.status,
            "created_at": o.created_at.isoformat(),
        }
        for o, sym, tcode, dname in open_orders_rows
    ]

    short_rows = (
        await session.execute(
            select(ShortPosition, Stock.symbol, MarketReferencePrice.official_mtm_price, Participant.tournament_code, Participant.display_name)
            .join(Stock, Stock.id == ShortPosition.stock_id)
            .join(MarketReferencePrice, MarketReferencePrice.stock_id == ShortPosition.stock_id)
            .join(GameParticipant, GameParticipant.id == ShortPosition.game_participant_id)
            .join(Participant, Participant.id == GameParticipant.participant_id)
            .where(ShortPosition.game_id == game_id, ShortPosition.borrowed_shares > 0)
            .order_by(desc(ShortPosition.borrowed_shares))
            .limit(100)
        )
    ).all()
    active_shorts = []
    for sp, sym, mtm, tcode, dname in short_rows:
        m = compute_short_position_metrics(sp, mtm, game.maintenance_margin_ratio)
        m["symbol"] = sym
        m["tournament_code"] = tcode
        m["display_name"] = dname
        active_shorts.append(m)

    async with session.begin_nested():
        snaps = await build_and_persist_leaderboard(session, game=game)
    rankings = [
        {
            "rank": s.rank,
            "tournament_code": s.tournament_code,
            "display_name": s.display_name,
            "final_net_worth": str(to_dec(s.final_net_worth)),
            "net_pnl": str(to_dec(s.net_pnl)),
            "return_pct": str(to_dec(s.return_pct)),
            "realized_pnl": str(to_dec(s.realized_pnl)),
        }
        for s in snaps[:50]
    ]

    invariants = await verify_game_accounting_invariants(session, game_id)
    total_trades = int(
        (await session.execute(select(func.count(Trade.id)).where(Trade.game_id == game_id))).scalar_one()
    )

    return {
        "game": _serialize_game_summary(game, invariants.participant_count, False),
        "stocks": stocks,
        "order_books": books,
        "open_orders": open_orders,
        "active_short_positions": active_shorts,
        "rankings": rankings,
        "total_trades": total_trades,
        "accounting_integrity": {
            "passed": invariants.passed,
            "participant_count": invariants.participant_count,
            "total_player_cash": str(invariants.total_player_cash),
            "expected_total_cash": str(invariants.expected_total_cash),
            "violations": invariants.violations,
        },
    }


@router.post("/games/{game_id}/emergency/stocks/{symbol}/toggle")
async def api_admin_toggle_stock_trading(
    game_id: uuid.UUID,
    symbol: str,
    req: ToggleStockTradingRequest,
    admin: User = Depends(require_admin),
    session: AsyncSession = Depends(get_db_session),
) -> dict[str, Any]:
    sym = symbol.strip().upper()
    async with atomic_tx(session):
        st = (
            await session.execute(select(Stock).where(Stock.game_id == game_id, Stock.symbol == sym))
        ).scalar_one_or_none()
        if st is None:
            raise ResourceNotFoundError(f"Stock '{sym}' not found.")
        await acquire_stock_matching_lock(session, game_id, st.id)
        before = {"trading_enabled": st.trading_enabled, "halt_reason": st.halt_reason}
        st.trading_enabled = req.trading_enabled
        st.halt_reason = None if req.trading_enabled else req.reason
        await record_audit_event(
            session,
            actor_user_id=admin.id,
            actor_role=admin.role,
            action_type="STOCK_TRADING_ENABLED" if req.trading_enabled else "STOCK_TRADING_HALTED",
            target_type="STOCK",
            target_id=st.symbol,
            game_id=game_id,
            before_state=before,
            after_state={"trading_enabled": st.trading_enabled, "halt_reason": st.halt_reason},
            reason=req.reason,
        )
    ws_hub.mark_stock_dirty(game_id, sym)
    return {"symbol": sym, "trading_enabled": req.trading_enabled, "halt_reason": None if req.trading_enabled else req.reason}


@router.post("/games/{game_id}/emergency/cancel-orders")
async def api_admin_emergency_cancel_orders(
    game_id: uuid.UUID,
    req: EmergencyCancelOrdersRequest,
    admin: User = Depends(require_admin),
    session: AsyncSession = Depends(get_db_session),
) -> dict[str, Any]:
    async with atomic_tx(session):
        stmt = select(Order.id, Stock.symbol).join(Stock, Stock.id == Order.stock_id).where(
            Order.game_id == game_id,
            Order.status.in_([OrderStatus.OPEN.value, OrderStatus.PARTIALLY_FILLED.value]),
        )
        if req.symbol:
            stmt = stmt.where(Stock.symbol == req.symbol.strip().upper())
        rows = (await session.execute(stmt)).all()
        for oid, sym in rows:
            await cancel_order(
                session,
                game_id=game_id,
                order_id=oid,
                is_admin_or_system=True,
                reason=f"ADMIN_EMERGENCY_CANCEL: {req.reason}",
            )
            ws_hub.mark_stock_dirty(game_id, sym)

        await record_audit_event(
            session,
            actor_user_id=admin.id,
            actor_role=admin.role,
            action_type="EMERGENCY_ORDERS_CANCELLED",
            target_type="GAME",
            target_id=str(game_id),
            game_id=game_id,
            after_state={"cancelled_count": len(rows), "symbol_filter": req.symbol},
            reason=req.reason,
        )
    return {"cancelled_count": len(rows)}


@router.post("/games/{game_id}/emergency/news-halt")
async def api_admin_toggle_news_halt(
    game_id: uuid.UUID,
    req: ToggleNewsHaltRequest,
    admin: User = Depends(require_admin),
    session: AsyncSession = Depends(get_db_session),
) -> dict[str, Any]:
    async with atomic_tx(session):
        await acquire_game_lifecycle_lock(session, game_id)
        game = (await session.execute(select(Game).where(Game.id == game_id).with_for_update())).scalar_one_or_none()
        if game is None:
            raise ResourceNotFoundError("Game not found.")
        prev = game.news_halted
        game.news_halted = req.news_halted
        game.updated_at = datetime.now(timezone.utc)
        await record_audit_event(
            session,
            actor_user_id=admin.id,
            actor_role=admin.role,
            action_type="NEWS_HALT_TOGGLED",
            target_type="GAME",
            target_id=str(game_id),
            game_id=game_id,
            before_state={"news_halted": prev},
            after_state={"news_halted": req.news_halted},
            reason=req.reason,
        )
    return {"game_id": str(game_id), "news_halted": req.news_halted}


@router.get("/games/{game_id}/audit-logs")
async def api_admin_audit_logs(
    game_id: uuid.UUID,
    limit: int = Query(default=150, ge=1, le=500),
    admin: User = Depends(require_admin),
    session: AsyncSession = Depends(get_db_session),
) -> list[dict[str, Any]]:
    logs = (
        await session.execute(
            select(AuditLog)
            .where(AuditLog.game_id == game_id)
            .order_by(desc(AuditLog.id))
            .limit(limit)
        )
    ).scalars().all()
    return [
        {
            "id": lg.id,
            "actor_user_id": str(lg.actor_user_id) if lg.actor_user_id else None,
            "actor_role": lg.actor_role,
            "action_type": lg.action_type,
            "target_type": lg.target_type,
            "target_id": lg.target_id,
            "before_state": lg.before_state,
            "after_state": lg.after_state,
            "reason": lg.reason,
            "prev_record_hash": lg.prev_record_hash,
            "record_hash": lg.record_hash,
            "created_at": lg.created_at.isoformat(),
        }
        for lg in logs
    ]
