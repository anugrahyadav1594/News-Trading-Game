import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.decimal_utils import HUNDRED, ZERO, to_dec
from app.core.exceptions import InsufficientFundsError, InsufficientSharesError
from app.models.ledger import CashLedgerEntry, ShareLedgerEntry
from app.models.market import MarketReferencePrice
from app.models.portfolio import PlayerPortfolio, PlayerStockHolding
from app.models.shorting import ShortPosition
from app.models.stock import Stock


@dataclass
class ParticipantValuation:
    game_participant_id: uuid.UUID
    available_cash: Decimal
    order_reserved_cash: Decimal
    short_margin_locked: Decimal
    short_proceeds_locked: Decimal
    reserved_cash_total: Decimal
    unfunded_settlement_debt: Decimal
    long_market_value: Decimal
    short_liability: Decimal
    realized_pnl: Decimal
    unrealized_long_pnl: Decimal
    unrealized_short_pnl: Decimal
    unrealized_pnl_total: Decimal
    net_worth: Decimal
    net_pnl: Decimal
    return_pct: Decimal


async def lock_portfolios_canonical(
    session: AsyncSession,
    participant_ids: list[uuid.UUID],
) -> dict[uuid.UUID, PlayerPortfolio]:
    """
    Lock PlayerPortfolio rows in deterministic ascending UUID order
    to eliminate deadlocks during concurrent peer-to-peer trade settlement.
    """
    ordered_ids = sorted(set(participant_ids), key=lambda x: str(x))
    portfolios: dict[uuid.UUID, PlayerPortfolio] = {}
    for pid in ordered_ids:
        row = (
            await session.execute(
                select(PlayerPortfolio)
                .where(PlayerPortfolio.game_participant_id == pid)
                .with_for_update()
            )
        ).scalar_one()
        portfolios[pid] = row
    return portfolios


async def apply_cash_mutation(
    session: AsyncSession,
    portfolio: PlayerPortfolio,
    *,
    entry_type: str,
    reference_type: str,
    reference_id: uuid.UUID,
    idempotency_key: str,
    delta_available: Decimal = ZERO,
    delta_order_reserved: Decimal = ZERO,
    delta_short_margin: Decimal = ZERO,
    delta_short_proceeds: Decimal = ZERO,
    delta_unfunded_debt: Decimal = ZERO,
    realized_pnl_delta: Decimal = ZERO,
    notes: str | None = None,
) -> CashLedgerEntry:
    """
    Atomically mutate cash buckets on a locked PlayerPortfolio and write
    an immutable CashLedgerEntry in the same transaction.
    """
    d_avail = to_dec(delta_available)
    d_ord = to_dec(delta_order_reserved)
    d_margin = to_dec(delta_short_margin)
    d_proc = to_dec(delta_short_proceeds)
    d_debt = to_dec(delta_unfunded_debt)
    d_rpnl = to_dec(realized_pnl_delta)

    new_avail = to_dec(portfolio.available_cash + d_avail)
    new_ord = to_dec(portfolio.order_reserved_cash + d_ord)
    new_margin = to_dec(portfolio.short_margin_locked + d_margin)
    new_proc = to_dec(portfolio.short_proceeds_locked + d_proc)
    new_debt = to_dec(portfolio.unfunded_settlement_debt + d_debt)

    if new_avail < ZERO:
        raise InsufficientFundsError(
            f"Insufficient available cash: attempted balance {new_avail}",
            details={"available_cash": str(portfolio.available_cash), "delta": str(d_avail)},
        )
    if new_ord < ZERO or new_margin < ZERO or new_proc < ZERO or new_debt < ZERO:
        raise InsufficientFundsError(
            "Invalid negative reserved/collateral cash state in accounting mutation.",
            details={
                "new_ord": str(new_ord),
                "new_margin": str(new_margin),
                "new_proc": str(new_proc),
                "new_debt": str(new_debt),
            },
        )

    portfolio.available_cash = new_avail
    portfolio.order_reserved_cash = new_ord
    portfolio.short_margin_locked = new_margin
    portfolio.short_proceeds_locked = new_proc
    portfolio.unfunded_settlement_debt = new_debt
    portfolio.realized_pnl = to_dec(portfolio.realized_pnl + d_rpnl)
    portfolio.version += 1
    portfolio.updated_at = datetime.now(timezone.utc)

    total_cash = to_dec(new_avail + new_ord + new_margin + new_proc)

    ledger = CashLedgerEntry(
        game_id=portfolio.game_id,
        game_participant_id=portfolio.game_participant_id,
        entry_type=entry_type,
        delta_available=d_avail,
        delta_order_reserved=d_ord,
        delta_short_margin=d_margin,
        delta_short_proceeds=d_proc,
        delta_unfunded_debt=d_debt,
        balance_available_after=new_avail,
        balance_total_cash_after=total_cash,
        reference_type=reference_type,
        reference_id=reference_id,
        idempotency_key=idempotency_key,
        notes=notes,
    )
    session.add(ledger)
    await session.flush()
    return ledger


async def apply_share_mutation(
    session: AsyncSession,
    *,
    game_id: uuid.UUID,
    game_participant_id: uuid.UUID,
    stock_id: uuid.UUID,
    holding: PlayerStockHolding,
    short_pos: ShortPosition | None,
    entry_type: str,
    reference_type: str,
    reference_id: uuid.UUID,
    idempotency_key: str,
    delta_long_available: int = 0,
    delta_long_reserved: int = 0,
    delta_short_borrowed: int = 0,
) -> ShareLedgerEntry:
    """
    Atomically mutate integer share holdings / short borrowed counts
    and append an immutable ShareLedgerEntry.
    """
    new_long_avail = holding.available_shares + delta_long_available
    new_long_res = holding.reserved_shares + delta_long_reserved
    if new_long_avail < 0 or new_long_res < 0:
        raise InsufficientSharesError(
            "Insufficient long shares for requested operation.",
            details={
                "available_shares": holding.available_shares,
                "reserved_shares": holding.reserved_shares,
                "delta_avail": delta_long_available,
                "delta_res": delta_long_reserved,
            },
        )

    current_short = short_pos.borrowed_shares if short_pos else 0
    new_short = current_short + delta_short_borrowed
    if new_short < 0:
        raise InsufficientSharesError("Short borrowed shares cannot become negative.")

    holding.available_shares = new_long_avail
    holding.reserved_shares = new_long_res
    holding.updated_at = datetime.now(timezone.utc)
    if short_pos is not None and delta_short_borrowed != 0:
        short_pos.borrowed_shares = new_short
        short_pos.updated_at = datetime.now(timezone.utc)

    ledger = ShareLedgerEntry(
        game_id=game_id,
        game_participant_id=game_participant_id,
        stock_id=stock_id,
        entry_type=entry_type,
        delta_long_available=delta_long_available,
        delta_long_reserved=delta_long_reserved,
        delta_short_borrowed=delta_short_borrowed,
        long_available_after=new_long_avail,
        long_reserved_after=new_long_res,
        short_borrowed_after=new_short,
        reference_type=reference_type,
        reference_id=reference_id,
        idempotency_key=idempotency_key,
    )
    session.add(ledger)
    await session.flush()
    return ledger


async def compute_participant_valuation(
    session: AsyncSession,
    *,
    game_id: uuid.UUID,
    game_participant_id: uuid.UUID,
    initial_net_worth: Decimal,
    use_final_settlement_price: bool = False,
    price_map_override: dict[uuid.UUID, Decimal] | None = None,
) -> ParticipantValuation:
    """
    Server-authoritative Net Worth & P&L calculator (Section 11):
      Final Net Worth = Available Cash + Reserved Cash + Long Stock Market Value
                        - Outstanding Short Liabilities - Unfunded Settlement Debt
    where Reserved Cash = order_reserved_cash + short_margin_locked + short_proceeds_locked.
    """
    portfolio = (
        await session.execute(
            select(PlayerPortfolio).where(PlayerPortfolio.game_participant_id == game_participant_id)
        )
    ).scalar_one()

    if price_map_override is not None:
        mark_prices = price_map_override
    else:
        refs = (
            await session.execute(
                select(MarketReferencePrice).where(MarketReferencePrice.game_id == game_id)
            )
        ).scalars().all()
        mark_prices = {}
        for r in refs:
            if use_final_settlement_price and r.final_settlement_price is not None:
                mark_prices[r.stock_id] = to_dec(r.final_settlement_price)
            else:
                mark_prices[r.stock_id] = to_dec(r.official_mtm_price)

    holdings = (
        await session.execute(
            select(PlayerStockHolding).where(PlayerStockHolding.game_participant_id == game_participant_id)
        )
    ).scalars().all()

    shorts = (
        await session.execute(
            select(ShortPosition).where(ShortPosition.game_participant_id == game_participant_id)
        )
    ).scalars().all()

    long_val = ZERO
    unrealized_long = ZERO
    for h in holdings:
        total_long_qty = h.available_shares + h.reserved_shares
        if total_long_qty > 0:
            px = mark_prices.get(h.stock_id, ZERO)
            val = to_dec(px * Decimal(total_long_qty))
            cost = to_dec(h.avg_entry_price * Decimal(total_long_qty))
            long_val = to_dec(long_val + val)
            unrealized_long = to_dec(unrealized_long + (val - cost))

    short_liab = ZERO
    unrealized_short = ZERO
    for sp in shorts:
        if sp.borrowed_shares > 0:
            px = mark_prices.get(sp.stock_id, ZERO)
            liab = to_dec(px * Decimal(sp.borrowed_shares))
            short_liab = to_dec(short_liab + liab)
            unrealized_short = to_dec(unrealized_short + (sp.sale_proceeds_locked - liab))

    reserved_total = to_dec(
        portfolio.order_reserved_cash + portfolio.short_margin_locked + portfolio.short_proceeds_locked
    )
    net_worth = to_dec(
        portfolio.available_cash
        + reserved_total
        + long_val
        - short_liab
        - portfolio.unfunded_settlement_debt
    )
    net_pnl = to_dec(net_worth - initial_net_worth)
    return_pct = to_dec((net_pnl / initial_net_worth) * HUNDRED) if initial_net_worth > ZERO else ZERO

    return ParticipantValuation(
        game_participant_id=game_participant_id,
        available_cash=to_dec(portfolio.available_cash),
        order_reserved_cash=to_dec(portfolio.order_reserved_cash),
        short_margin_locked=to_dec(portfolio.short_margin_locked),
        short_proceeds_locked=to_dec(portfolio.short_proceeds_locked),
        reserved_cash_total=reserved_total,
        unfunded_settlement_debt=to_dec(portfolio.unfunded_settlement_debt),
        long_market_value=long_val,
        short_liability=short_liab,
        realized_pnl=to_dec(portfolio.realized_pnl),
        unrealized_long_pnl=unrealized_long,
        unrealized_short_pnl=unrealized_short,
        unrealized_pnl_total=to_dec(unrealized_long + unrealized_short),
        net_worth=net_worth,
        net_pnl=net_pnl,
        return_pct=return_pct,
    )
