import random
import uuid
from datetime import datetime, timezone
from decimal import Decimal
from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.decimal_utils import ZERO, to_dec
from app.core.exceptions import (
    InvalidGamePhaseError,
    OrderValidationError,
    ResourceNotFoundError,
)
from app.db.locks import acquire_game_lifecycle_lock
from app.models.enums import GameStatus, NewsApprovalStatus, NewsDirection, NewsType
from app.models.game import Game
from app.models.news import (
    EventImpactMapping,
    NewsCategoryRecord,
    NewsEvent,
    NewsRelease,
)
from app.models.stock import CompanyProfile, Stock
from app.models.user import User
from app.modules.audit.service import record_audit_event
from app.modules.news.catalog import (
    BUILTIN_NEWS_CATEGORIES,
    EVENT_CHAIN_BLUEPRINTS,
    SCENARIO_BLUEPRINTS,
)
from app.modules.news.schemas import (
    CreateCustomNewsRequest,
    CreateNewsCategoryRequest,
    CreateReversalEventRequest,
    GenerateNewsBatchRequest,
    ReleaseNewsRequest,
    UpdateNewsEventRequest,
)
from app.modules.pricing.service import (
    apply_released_news_to_market,
    calculate_event_stock_impacts,
)
from app.modules.tournament.service import compute_clock_state

SIMULATION_LABEL = "MTT TOURNAMENT SIMULATION — FICTIONAL FINANCIAL NEWS"


async def ensure_builtin_news_categories(session: AsyncSession) -> list[NewsCategoryRecord]:
    existing_codes = set(
        (await session.execute(select(NewsCategoryRecord.code))).scalars().all()
    )
    for item in BUILTIN_NEWS_CATEGORIES:
        if item["code"] not in existing_codes:
            session.add(
                NewsCategoryRecord(
                    code=item["code"],
                    display_name=item["display_name"],
                    domain_group=item["domain_group"],
                    default_factors=item["default_factors"],
                    is_builtin=True,
                )
            )
    await session.flush()
    return list(
        (await session.execute(select(NewsCategoryRecord).order_by(NewsCategoryRecord.code))).scalars().all()
    )


async def create_custom_news_category(
    session: AsyncSession,
    req: CreateNewsCategoryRequest,
    *,
    admin_user: User,
) -> NewsCategoryRecord:
    await ensure_builtin_news_categories(session)
    code = req.code.strip().upper().replace(" ", "_")
    existing = (
        await session.execute(select(NewsCategoryRecord).where(NewsCategoryRecord.code == code))
    ).scalar_one_or_none()
    if existing is not None:
        return existing

    rec = NewsCategoryRecord(
        code=code,
        display_name=req.display_name.strip(),
        domain_group=req.domain_group.strip(),
        default_factors=req.default_factors,
        is_builtin=False,
    )
    session.add(rec)
    await record_audit_event(
        session,
        actor_user_id=admin_user.id,
        actor_role=admin_user.role,
        action_type="NEWS_CATEGORY_CREATED",
        target_type="NEWS_CATEGORY",
        target_id=code,
        after_state={"display_name": rec.display_name},
    )
    await session.flush()
    return rec


async def _load_stocks_with_profiles(
    session: AsyncSession,
    game_id: uuid.UUID,
) -> tuple[dict[str, Stock], list[tuple[Stock, CompanyProfile]]]:
    rows = (
        await session.execute(
            select(Stock, CompanyProfile)
            .join(CompanyProfile, CompanyProfile.stock_id == Stock.id)
            .where(Stock.game_id == game_id)
            .order_by(Stock.symbol)
        )
    ).all()
    by_sym = {st.symbol: st for st, _ in rows}
    return by_sym, [(st, prof) for st, prof in rows]


async def _rebuild_event_impact_mappings(
    session: AsyncSession,
    *,
    game: Game,
    event: NewsEvent,
    stocks_with_profiles: list[tuple[Stock, CompanyProfile]],
) -> list[EventImpactMapping]:
    await session.execute(
        delete(EventImpactMapping).where(EventImpactMapping.news_event_id == event.id)
    )
    impacts = calculate_event_stock_impacts(
        game=game,
        stocks_with_profiles=stocks_with_profiles,
        event=event,
    )
    max_abs = max((abs(i["estimated_pct_delta"]) for i in impacts), default=ZERO)
    event.impact_magnitude = to_dec(max_abs)

    # Guarantee consistency between computed impact vector and event direction label
    pos_count = sum(1 for i in impacts if i["raw_log_impulse"] > Decimal("0.001"))
    neg_count = sum(1 for i in impacts if i["raw_log_impulse"] < Decimal("-0.001"))
    if pos_count > 0 and neg_count > 0:
        event.direction = NewsDirection.MIXED.value
    elif pos_count > 0:
        event.direction = NewsDirection.POSITIVE.value
    elif neg_count > 0:
        event.direction = NewsDirection.NEGATIVE.value

    created: list[EventImpactMapping] = []
    for item in impacts:
        row = EventImpactMapping(
            news_event_id=event.id,
            stock_id=item["stock_id"],
            symbol=item["symbol"],
            direct_exposure=item["direct_exposure"],
            indirect_exposure=item["indirect_exposure"],
            macro_sensitivity=item["macro_sensitivity"],
            combined_exposure=item["combined_exposure"],
            raw_log_impulse=item["raw_log_impulse"],
            applied_log_impulse=ZERO,
            estimated_pct_delta=item["estimated_pct_delta"],
        )
        session.add(row)
        created.append(row)
    await session.flush()
    return created


async def generate_news_library_for_game(
    session: AsyncSession,
    *,
    game_id: uuid.UUID,
    req: GenerateNewsBatchRequest,
    admin_user: User | None = None,
) -> list[NewsEvent]:
    """
    Deterministically generate a structured library of fictional simulated events
    covering all 25 categories plus multi-stage event chains.
    """
    await ensure_builtin_news_categories(session)
    game = (await session.execute(select(Game).where(Game.id == game_id))).scalar_one_or_none()
    if game is None:
        raise ResourceNotFoundError("Game not found.")

    stocks_by_sym, stocks_with_profiles = await _load_stocks_with_profiles(session, game_id)
    existing_cnt = int(
        (await session.execute(select(func.count(NewsEvent.id)).where(NewsEvent.game_id == game_id))).scalar_one()
    )
    rng = random.Random(req.seed if req.seed is not None else (existing_cnt + 20261112))
    status_val = NewsApprovalStatus.APPROVED.value if req.auto_approve else NewsApprovalStatus.GENERATED.value

    created_events: list[NewsEvent] = []
    seq_idx = existing_cnt + 1

    # 1. Include multi-stage event chains first if requested
    if req.include_chains:
        for chain_bp in EVENT_CHAIN_BLUEPRINTS:
            if len(created_events) >= req.count:
                break
            chain_uuid = uuid.uuid4()
            total_stages = len(chain_bp["stages"])
            prev_stage_id: uuid.UUID | None = None
            primary_sym = chain_bp["primary_symbol"]
            primary_stock = stocks_by_sym.get(primary_sym)

            for idx, stg in enumerate(chain_bp["stages"], start=1):
                if len(created_events) >= req.count:
                    break
                ev = NewsEvent(
                    game_id=game_id,
                    event_code=f"EVT-{seq_idx:04d}",
                    chain_id=chain_uuid,
                    chain_name=chain_bp["chain_name"],
                    chain_stage=idx,
                    chain_total_stages=total_stages,
                    parent_event_id=prev_stage_id,
                    category=chain_bp["category"],
                    news_type=stg["news_type"],
                    headline=stg["headline"],
                    body=stg["body"],
                    primary_stock_id=primary_stock.id if primary_stock else None,
                    primary_symbol=primary_sym,
                    secondary_symbols=chain_bp["secondary_symbols"],
                    affected_sectors=chain_bp["affected_sectors"],
                    factor_shocks={},
                    direct_weights=stg["direct_weights"],
                    indirect_weights=stg["indirect_weights"],
                    direction=stg["direction"],
                    severity=to_dec(stg["severity"]),
                    credibility=to_dec(stg["credibility"]),
                    surprise_factor=to_dec(stg["surprise_factor"]),
                    impact_magnitude=ZERO,
                    permanent_fraction=to_dec(stg["permanent_fraction"]),
                    expected_duration_sec=540,
                    approval_status=status_val,
                    simulation_label=SIMULATION_LABEL,
                    created_by_admin_id=admin_user.id if admin_user else None,
                    approved_by_admin_id=admin_user.id if (admin_user and req.auto_approve) else None,
                )
                session.add(ev)
                await session.flush()
                await _rebuild_event_impact_mappings(
                    session, game=game, event=ev, stocks_with_profiles=stocks_with_profiles
                )
                prev_stage_id = ev.id
                created_events.append(ev)
                seq_idx += 1

    # 2. Fill remaining requested count across all 25 scenario blueprints (with deterministic parameter variation on repeats)
    bp_pool = list(SCENARIO_BLUEPRINTS)
    cycle_num = 0
    while len(created_events) < req.count:
        if cycle_num > 0:
            rng.shuffle(bp_pool)
        for bp in bp_pool:
            if len(created_events) >= req.count:
                break
            jitter = 1.0 if cycle_num == 0 else round(rng.uniform(0.85, 1.15), 2)
            sev = min(Decimal("1.0000"), max(Decimal("0.2000"), to_dec(Decimal(bp["severity"]) * Decimal(str(jitter)))))
            surp = min(Decimal("1.5000"), max(Decimal("0.5000"), to_dec(bp["surprise_factor"])))
            p_sym = bp.get("primary_symbol")
            p_stock = stocks_by_sym.get(p_sym) if p_sym else None
            suffix = "" if cycle_num == 0 else f" (Update #{cycle_num + 1})"

            ev = NewsEvent(
                game_id=game_id,
                event_code=f"EVT-{seq_idx:04d}",
                category=bp["category"],
                news_type=bp["news_type"],
                headline=f"{bp['headline']}{suffix}",
                body=bp["body"],
                primary_stock_id=p_stock.id if p_stock else None,
                primary_symbol=p_sym,
                secondary_symbols=bp["secondary_symbols"],
                affected_sectors=bp["affected_sectors"],
                factor_shocks=bp["factor_shocks"],
                direct_weights=bp["direct_weights"],
                indirect_weights=bp["indirect_weights"],
                direction=bp["direction"],
                severity=sev,
                credibility=to_dec(bp["credibility"]),
                surprise_factor=surp,
                impact_magnitude=ZERO,
                permanent_fraction=to_dec(bp["permanent_fraction"]),
                expected_duration_sec=bp["duration_sec"],
                approval_status=status_val,
                simulation_label=SIMULATION_LABEL,
                created_by_admin_id=admin_user.id if admin_user else None,
                approved_by_admin_id=admin_user.id if (admin_user and req.auto_approve) else None,
            )
            session.add(ev)
            await session.flush()
            await _rebuild_event_impact_mappings(
                session, game=game, event=ev, stocks_with_profiles=stocks_with_profiles
            )
            created_events.append(ev)
            seq_idx += 1
        cycle_num += 1

    if admin_user is not None:
        await record_audit_event(
            session,
            actor_user_id=admin_user.id,
            actor_role=admin_user.role,
            action_type="NEWS_BATCH_GENERATED",
            target_type="GAME",
            target_id=str(game_id),
            game_id=game_id,
            after_state={"generated_count": len(created_events), "auto_approve": req.auto_approve},
        )
    await session.flush()
    return created_events


async def create_custom_news_event(
    session: AsyncSession,
    *,
    game_id: uuid.UUID,
    req: CreateCustomNewsRequest,
    admin_user: User,
) -> NewsEvent:
    await ensure_builtin_news_categories(session)
    game = (await session.execute(select(Game).where(Game.id == game_id))).scalar_one_or_none()
    if game is None:
        raise ResourceNotFoundError("Game not found.")

    cat_code = req.category.strip().upper()
    cat = (
        await session.execute(select(NewsCategoryRecord).where(NewsCategoryRecord.code == cat_code))
    ).scalar_one_or_none()
    if cat is None:
        raise OrderValidationError(f"Unknown news category '{cat_code}'; register category first.")

    stocks_by_sym, stocks_with_profiles = await _load_stocks_with_profiles(session, game_id)
    p_sym = req.primary_symbol.strip().upper() if req.primary_symbol else None
    p_stock = stocks_by_sym.get(p_sym) if p_sym else None

    cnt = int(
        (await session.execute(select(func.count(NewsEvent.id)).where(NewsEvent.game_id == game_id))).scalar_one()
    )
    headline_clean = req.headline.strip()
    if "[SIMULATED" not in headline_clean.upper():
        headline_clean = f"[SIMULATED] {headline_clean}"

    ev = NewsEvent(
        game_id=game_id,
        event_code=f"EVT-{cnt + 1:04d}",
        reverses_event_id=req.reverses_event_id,
        category=cat_code,
        news_type=req.news_type.upper(),
        headline=headline_clean,
        body=req.body.strip(),
        primary_stock_id=p_stock.id if p_stock else None,
        primary_symbol=p_sym,
        secondary_symbols=[s.upper() for s in req.secondary_symbols],
        affected_sectors=req.affected_sectors,
        factor_shocks=req.factor_shocks,
        direct_weights={k.upper(): v for k, v in req.direct_weights.items()},
        indirect_weights={k.upper(): v for k, v in req.indirect_weights.items()},
        direction=req.direction.upper(),
        severity=to_dec(req.severity),
        credibility=to_dec(req.credibility),
        surprise_factor=to_dec(req.surprise_factor),
        impact_magnitude=ZERO,
        permanent_fraction=to_dec(req.permanent_fraction),
        reversal_ratio=to_dec(req.reversal_ratio),
        expected_duration_sec=req.expected_duration_sec,
        approval_status=NewsApprovalStatus.APPROVED.value if req.auto_approve else NewsApprovalStatus.GENERATED.value,
        simulation_label=SIMULATION_LABEL,
        created_by_admin_id=admin_user.id,
        approved_by_admin_id=admin_user.id if req.auto_approve else None,
    )
    session.add(ev)
    await session.flush()
    await _rebuild_event_impact_mappings(session, game=game, event=ev, stocks_with_profiles=stocks_with_profiles)

    await record_audit_event(
        session,
        actor_user_id=admin_user.id,
        actor_role=admin_user.role,
        action_type="NEWS_EVENT_CREATED",
        target_type="NEWS_EVENT",
        target_id=str(ev.id),
        game_id=game_id,
        after_state={"event_code": ev.event_code, "headline": ev.headline},
    )
    await session.flush()
    return ev


async def update_news_event(
    session: AsyncSession,
    *,
    game_id: uuid.UUID,
    event_id: uuid.UUID,
    req: UpdateNewsEventRequest,
    admin_user: User,
) -> NewsEvent:
    ev = (
        await session.execute(select(NewsEvent).where(NewsEvent.id == event_id, NewsEvent.game_id == game_id))
    ).scalar_one_or_none()
    if ev is None:
        raise ResourceNotFoundError("News event not found.")
    if ev.approval_status == NewsApprovalStatus.RELEASED.value:
        raise InvalidGamePhaseError("Cannot edit a news event after it has already been released to the market.")

    game = (await session.execute(select(Game).where(Game.id == game_id))).scalar_one()
    before = {"headline": ev.headline, "severity": str(ev.severity), "credibility": str(ev.credibility)}

    updates = req.model_dump(exclude_none=True)
    for k, val in updates.items():
        if k == "headline" and "[SIMULATED" not in val.upper():
            val = f"[SIMULATED] {val}"
        setattr(ev, k, to_dec(val) if isinstance(val, Decimal) else val)

    if ev.approval_status == NewsApprovalStatus.GENERATED.value:
        ev.approval_status = NewsApprovalStatus.EDITED.value

    _, stocks_with_profiles = await _load_stocks_with_profiles(session, game_id)
    await _rebuild_event_impact_mappings(session, game=game, event=ev, stocks_with_profiles=stocks_with_profiles)

    await record_audit_event(
        session,
        actor_user_id=admin_user.id,
        actor_role=admin_user.role,
        action_type="NEWS_EVENT_UPDATED",
        target_type="NEWS_EVENT",
        target_id=str(ev.id),
        game_id=game_id,
        before_state=before,
        after_state=updates,
    )
    await session.flush()
    return ev


async def set_news_approval(
    session: AsyncSession,
    *,
    game_id: uuid.UUID,
    event_id: uuid.UUID,
    approve: bool,
    admin_user: User,
) -> NewsEvent:
    ev = (
        await session.execute(select(NewsEvent).where(NewsEvent.id == event_id, NewsEvent.game_id == game_id))
    ).scalar_one_or_none()
    if ev is None:
        raise ResourceNotFoundError("News event not found.")
    if ev.approval_status == NewsApprovalStatus.RELEASED.value:
        raise InvalidGamePhaseError("Event is already released.")

    ev.approval_status = NewsApprovalStatus.APPROVED.value if approve else NewsApprovalStatus.REJECTED.value
    ev.approved_by_admin_id = admin_user.id if approve else None
    await record_audit_event(
        session,
        actor_user_id=admin_user.id,
        actor_role=admin_user.role,
        action_type="NEWS_APPROVED" if approve else "NEWS_REJECTED",
        target_type="NEWS_EVENT",
        target_id=str(ev.id),
        game_id=game_id,
    )
    await session.flush()
    return ev


async def release_or_schedule_news_event(
    session: AsyncSession,
    *,
    game_id: uuid.UUID,
    event_id: uuid.UUID,
    req: ReleaseNewsRequest,
    admin_user: User | None = None,
) -> tuple[NewsEvent, NewsRelease | None]:
    """
    Either schedule an approved event for a target game second or release it immediately
    during Phase A (MAIN_TRADING). Prohibits releasing news during Phase B (SHORT_SETTLEMENT)
    or when news releases are administratively halted.
    """
    await acquire_game_lifecycle_lock(session, game_id)
    game = (await session.execute(select(Game).where(Game.id == game_id).with_for_update())).scalar_one_or_none()
    if game is None:
        raise ResourceNotFoundError("Game not found.")
    if game.news_halted:
        raise InvalidGamePhaseError("News releases are currently halted by emergency control.")

    ev = (
        await session.execute(
            select(NewsEvent).where(NewsEvent.id == event_id, NewsEvent.game_id == game_id).with_for_update()
        )
    ).scalar_one_or_none()
    if ev is None:
        raise ResourceNotFoundError("News event not found.")
    if ev.approval_status == NewsApprovalStatus.REJECTED.value:
        raise InvalidGamePhaseError("Rejected news events cannot be released without approval.")
    if ev.approval_status == NewsApprovalStatus.RELEASED.value:
        existing_rel = (
            await session.execute(select(NewsRelease).where(NewsRelease.news_event_id == ev.id))
        ).scalar_one_or_none()
        return ev, existing_rel

    mode = req.mode.upper()
    if mode == "SCHEDULED":
        if req.scheduled_game_sec is None:
            raise OrderValidationError("scheduled_game_sec is required when mode == 'SCHEDULED'.")
        if req.scheduled_game_sec >= game.trading_duration_sec:
            raise OrderValidationError("News can only be scheduled within the Main Trading Round duration.")
        ev.scheduled_game_sec = req.scheduled_game_sec
        ev.approval_status = NewsApprovalStatus.SCHEDULED.value
        if admin_user:
            ev.approved_by_admin_id = admin_user.id
            await record_audit_event(
                session,
                actor_user_id=admin_user.id,
                actor_role=admin_user.role,
                action_type="NEWS_SCHEDULED",
                target_type="NEWS_EVENT",
                target_id=str(ev.id),
                game_id=game_id,
                after_state={"scheduled_game_sec": req.scheduled_game_sec},
            )
        await session.flush()
        return ev, None

    # IMMEDIATE release: strictly allowed during Phase A (MAIN_TRADING) only!
    if game.status != GameStatus.MAIN_TRADING.value:
        raise InvalidGamePhaseError(
            f"News can only be released during MAIN_TRADING (45-minute round), not in '{game.status}'."
        )

    now = datetime.now(timezone.utc)
    clock = compute_clock_state(game, now)
    pre_prices, post_prices = await apply_released_news_to_market(session, game=game, event=ev, now=now)

    ev.approval_status = NewsApprovalStatus.RELEASED.value
    ev.released_at = now
    if admin_user and ev.approved_by_admin_id is None:
        ev.approved_by_admin_id = admin_user.id

    release = NewsRelease(
        game_id=game_id,
        news_event_id=ev.id,
        release_mode=mode,
        game_elapsed_sec=clock.trading_elapsed_ms // 1000,
        released_at=now,
        released_by_admin_id=admin_user.id if admin_user else None,
        pre_release_ref_prices=pre_prices,
        post_release_ref_prices=post_prices,
        idempotency_key=f"news:rel:{ev.id}",
    )
    session.add(release)

    await record_audit_event(
        session,
        actor_user_id=admin_user.id if admin_user else None,
        actor_role=admin_user.role if admin_user else "SYSTEM_SCHEDULER",
        action_type="NEWS_RELEASED",
        target_type="NEWS_EVENT",
        target_id=str(ev.id),
        game_id=game_id,
        before_state=pre_prices,
        after_state={"headline": ev.headline, "post_ref_prices": post_prices},
    )
    await session.flush()
    return ev, release


async def create_event_reversal(
    session: AsyncSession,
    *,
    game_id: uuid.UUID,
    target_event_id: uuid.UUID,
    req: CreateReversalEventRequest,
    admin_user: User,
) -> tuple[NewsEvent, NewsRelease | None]:
    """Create a linked REVERSAL / CLARIFICATION event reversing a prior released event."""
    target = (
        await session.execute(select(NewsEvent).where(NewsEvent.id == target_event_id, NewsEvent.game_id == game_id))
    ).scalar_one_or_none()
    if target is None or target.approval_status != NewsApprovalStatus.RELEASED.value:
        raise InvalidGamePhaseError("Can only create a reversal for an already-released news event.")

    flip_dir = (
        NewsDirection.POSITIVE.value
        if target.direction == NewsDirection.NEGATIVE.value
        else (NewsDirection.NEGATIVE.value if target.direction == NewsDirection.POSITIVE.value else NewsDirection.MIXED.value)
    )
    rev_headline = req.headline or f"[SIMULATED REVERSAL] Official Clarification Retracts Earlier Report ({target.event_code})"
    rev_body = req.body or (
        f"SIMULATION WIRE: Official exchange clarification reverses earlier simulated report "
        f"('{target.headline}'), restoring prior fundamental guidance."
    )

    custom_req = CreateCustomNewsRequest(
        category=target.category,
        news_type=NewsType.REVERSAL.value,
        headline=rev_headline,
        body=rev_body,
        primary_symbol=target.primary_symbol,
        secondary_symbols=target.secondary_symbols,
        affected_sectors=target.affected_sectors,
        direction=flip_dir,
        severity=target.severity,
        credibility=Decimal("1.0000"),
        surprise_factor=Decimal("1.0000"),
        permanent_fraction=Decimal("1.0000"),
        expected_duration_sec=target.expected_duration_sec,
        direct_weights={k: -float(v) for k, v in (target.direct_weights or {}).items()},
        indirect_weights={k: -float(v) for k, v in (target.indirect_weights or {}).items()},
        factor_shocks={k: -float(v) for k, v in (target.factor_shocks or {}).items()},
        reverses_event_id=target.id,
        reversal_ratio=req.reversal_ratio,
        auto_approve=True,
    )
    rev_ev = await create_custom_news_event(session, game_id=game_id, req=custom_req, admin_user=admin_user)
    rev_ev.parent_event_id = target.id
    if target.chain_id:
        rev_ev.chain_id = target.chain_id
    await session.flush()

    if req.release_immediately:
        return await release_or_schedule_news_event(
            session,
            game_id=game_id,
            event_id=rev_ev.id,
            req=ReleaseNewsRequest(mode="IMMEDIATE"),
            admin_user=admin_user,
        )
    return rev_ev, None
