import uuid
from dataclasses import dataclass
from decimal import Decimal
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.decimal_utils import ZERO, to_dec
from app.models.enums import ExecutionKind, OrderStatus
from app.models.game import Game, GameParticipant
from app.models.ledger import CashLedgerEntry, ShareLedgerEntry
from app.models.order import Order, OrderExecution
from app.models.portfolio import PlayerPortfolio, PlayerStockHolding
from app.models.shorting import BorrowingPoolInventory, ShortPosition
from app.models.stock import Stock


@dataclass
class InvariantAuditReport:
    passed: bool
    participant_count: int
    total_player_cash: Decimal
    expected_total_cash: Decimal
    violations: list[str]


async def verify_game_accounting_invariants(
    session: AsyncSession,
    game_id: uuid.UUID,
) -> InvariantAuditReport:
    """
    Exhaustively verify every financial & inventory conservation invariant for a game:
      1. Cash Ledger sum == PlayerPortfolio cash buckets for every participant.
      2. Share Ledger sum == PlayerStockHolding + ShortPosition quantities for every participant/stock.
      3. Open/Partially-Filled Order reservations == Portfolio & Pool reserved balances.
      4. BorrowingPoolInventory: available + reserved + borrowed == total, and borrowed == sum(short_positions).
      5. Global Zero-Sum Cash Conservation (accounting for administrative forced settlement flows and fees).
      6. Global Share Conservation across all players + borrowed shares + admin settled short shares.
    """
    violations: list[str] = []

    game = (await session.execute(select(Game).where(Game.id == game_id))).scalar_one()
    participants = (
        await session.execute(
            select(GameParticipant).where(
                GameParticipant.game_id == game_id,
                GameParticipant.allocation_initialized.is_(True),
            )
        )
    ).scalars().all()
    n_players = len(participants)

    portfolios = {
        p.game_participant_id: p
        for p in (
            await session.execute(select(PlayerPortfolio).where(PlayerPortfolio.game_id == game_id))
        ).scalars().all()
    }

    # 1. Reconcile every participant's Cash Ledger against PlayerPortfolio
    cash_sums = (
        await session.execute(
            select(
                CashLedgerEntry.game_participant_id,
                func.coalesce(func.sum(CashLedgerEntry.delta_available), ZERO),
                func.coalesce(func.sum(CashLedgerEntry.delta_order_reserved), ZERO),
                func.coalesce(func.sum(CashLedgerEntry.delta_short_margin), ZERO),
                func.coalesce(func.sum(CashLedgerEntry.delta_short_proceeds), ZERO),
                func.coalesce(func.sum(CashLedgerEntry.delta_unfunded_debt), ZERO),
            )
            .where(CashLedgerEntry.game_id == game_id)
            .group_by(CashLedgerEntry.game_participant_id)
        )
    ).all()
    cash_sum_map = {row[0]: row[1:] for row in cash_sums}

    for gp in participants:
        pf = portfolios.get(gp.id)
        if pf is None:
            violations.append(f"Missing PlayerPortfolio for initialized participant {gp.id}")
            continue
        sums = cash_sum_map.get(gp.id, (ZERO, ZERO, ZERO, ZERO, ZERO))
        if to_dec(sums[0]) != to_dec(pf.available_cash):
            violations.append(f"Participant {gp.id} available_cash ({pf.available_cash}) != ledger ({sums[0]})")
        if to_dec(sums[1]) != to_dec(pf.order_reserved_cash):
            violations.append(f"Participant {gp.id} order_reserved_cash ({pf.order_reserved_cash}) != ledger ({sums[1]})")
        if to_dec(sums[2]) != to_dec(pf.short_margin_locked):
            violations.append(f"Participant {gp.id} short_margin_locked ({pf.short_margin_locked}) != ledger ({sums[2]})")
        if to_dec(sums[3]) != to_dec(pf.short_proceeds_locked):
            violations.append(f"Participant {gp.id} short_proceeds_locked ({pf.short_proceeds_locked}) != ledger ({sums[3]})")
        if to_dec(sums[4]) != to_dec(pf.unfunded_settlement_debt):
            violations.append(f"Participant {gp.id} unfunded_settlement_debt ({pf.unfunded_settlement_debt}) != ledger ({sums[4]})")

    # 2. Reconcile Share Ledger against PlayerStockHolding & ShortPosition
    share_sums = (
        await session.execute(
            select(
                ShareLedgerEntry.game_participant_id,
                ShareLedgerEntry.stock_id,
                func.coalesce(func.sum(ShareLedgerEntry.delta_long_available), 0),
                func.coalesce(func.sum(ShareLedgerEntry.delta_long_reserved), 0),
                func.coalesce(func.sum(ShareLedgerEntry.delta_short_borrowed), 0),
            )
            .where(ShareLedgerEntry.game_id == game_id)
            .group_by(ShareLedgerEntry.game_participant_id, ShareLedgerEntry.stock_id)
        )
    ).all()
    share_sum_map = {(r[0], r[1]): (int(r[2]), int(r[3]), int(r[4])) for r in share_sums}

    holdings = (
        await session.execute(select(PlayerStockHolding).where(PlayerStockHolding.game_id == game_id))
    ).scalars().all()
    shorts = (
        await session.execute(select(ShortPosition).where(ShortPosition.game_id == game_id))
    ).scalars().all()
    short_map = {(s.game_participant_id, s.stock_id): s for s in shorts}

    for h in holdings:
        la, lr, sb = share_sum_map.get((h.game_participant_id, h.stock_id), (0, 0, 0))
        if la != h.available_shares or lr != h.reserved_shares:
            violations.append(
                f"Share ledger mismatch for ({h.game_participant_id}, {h.stock_id}): "
                f"holding=({h.available_shares},{h.reserved_shares}) vs ledger=({la},{lr})"
            )
        sp = short_map.get((h.game_participant_id, h.stock_id))
        actual_sb = sp.borrowed_shares if sp else 0
        if sb != actual_sb:
            violations.append(
                f"Short ledger mismatch for ({h.game_participant_id}, {h.stock_id}): "
                f"short_pos={actual_sb} vs ledger={sb}"
            )

    # 3. Reconcile Active Order Reservations
    active_orders = (
        await session.execute(
            select(Order).where(
                Order.game_id == game_id,
                Order.status.in_([OrderStatus.OPEN.value, OrderStatus.PARTIALLY_FILLED.value]),
            )
        )
    ).scalars().all()

    ord_cash_by_part: dict[uuid.UUID, Decimal] = {}
    ord_short_margin_by_part: dict[uuid.UUID, Decimal] = {}
    ord_long_by_ps: dict[tuple[uuid.UUID, uuid.UUID], int] = {}
    ord_cover_by_ps: dict[tuple[uuid.UUID, uuid.UUID], int] = {}
    ord_borrow_by_stock: dict[uuid.UUID, int] = {}

    for o in active_orders:
        ord_cash_by_part[o.game_participant_id] = to_dec(
            ord_cash_by_part.get(o.game_participant_id, ZERO) + o.reserved_cash
        )
        ord_short_margin_by_part[o.game_participant_id] = to_dec(
            ord_short_margin_by_part.get(o.game_participant_id, ZERO) + o.reserved_short_margin
        )
        ps_key = (o.game_participant_id, o.stock_id)
        ord_long_by_ps[ps_key] = ord_long_by_ps.get(ps_key, 0) + o.reserved_long_shares
        ord_cover_by_ps[ps_key] = ord_cover_by_ps.get(ps_key, 0) + o.reserved_cover_shares
        ord_borrow_by_stock[o.stock_id] = ord_borrow_by_stock.get(o.stock_id, 0) + o.reserved_borrow_shares

    pos_margin_by_part: dict[uuid.UUID, Decimal] = {}
    pos_proceeds_by_part: dict[uuid.UUID, Decimal] = {}
    for sp in shorts:
        pos_margin_by_part[sp.game_participant_id] = to_dec(
            pos_margin_by_part.get(sp.game_participant_id, ZERO) + sp.margin_collateral_locked
        )
        pos_proceeds_by_part[sp.game_participant_id] = to_dec(
            pos_proceeds_by_part.get(sp.game_participant_id, ZERO) + sp.sale_proceeds_locked
        )

    for pid, pf in portfolios.items():
        expected_ord_cash = ord_cash_by_part.get(pid, ZERO)
        if to_dec(pf.order_reserved_cash) != expected_ord_cash:
            violations.append(
                f"Order cash reservation mismatch for {pid}: portfolio={pf.order_reserved_cash} vs active_orders={expected_ord_cash}"
            )
        expected_short_margin = to_dec(
            ord_short_margin_by_part.get(pid, ZERO) + pos_margin_by_part.get(pid, ZERO)
        )
        if to_dec(pf.short_margin_locked) != expected_short_margin:
            violations.append(
                f"Short margin locked mismatch for {pid}: portfolio={pf.short_margin_locked} vs orders+positions={expected_short_margin}"
            )
        expected_short_proc = pos_proceeds_by_part.get(pid, ZERO)
        if to_dec(pf.short_proceeds_locked) != expected_short_proc:
            violations.append(
                f"Short proceeds locked mismatch for {pid}: portfolio={pf.short_proceeds_locked} vs positions={expected_short_proc}"
            )

    for h in holdings:
        exp_long_res = ord_long_by_ps.get((h.game_participant_id, h.stock_id), 0)
        if h.reserved_shares != exp_long_res:
            violations.append(
                f"Long share reservation mismatch for ({h.game_participant_id}, {h.stock_id}): "
                f"holding={h.reserved_shares} vs orders={exp_long_res}"
            )

    for sp in shorts:
        exp_cover = ord_cover_by_ps.get((sp.game_participant_id, sp.stock_id), 0)
        if sp.pending_cover_shares != exp_cover:
            violations.append(
                f"Pending cover reservation mismatch for ({sp.game_participant_id}, {sp.stock_id}): "
                f"short_pos={sp.pending_cover_shares} vs orders={exp_cover}"
            )

    # 4 & 6. Borrowing Pool & Global Share Conservation per Stock
    stocks = (await session.execute(select(Stock).where(Stock.game_id == game_id))).scalars().all()
    pools = {
        bp.stock_id: bp
        for bp in (
            await session.execute(select(BorrowingPoolInventory).where(BorrowingPoolInventory.game_id == game_id))
        ).scalars().all()
    }
    admin_settled_rows = (
        await session.execute(
            select(
                OrderExecution.stock_id,
                func.coalesce(func.sum(OrderExecution.quantity), 0),
                func.coalesce(func.sum(OrderExecution.gross_amount), ZERO),
            )
            .where(
                OrderExecution.game_id == game_id,
                OrderExecution.execution_kind == ExecutionKind.ADMIN_FINAL_SHORT_SETTLEMENT.value,
            )
            .group_by(OrderExecution.stock_id)
        )
    ).all()
    admin_settled_qty_map = {r[0]: int(r[1]) for r in admin_settled_rows}
    admin_settled_cash_total = sum((to_dec(r[2]) for r in admin_settled_rows), ZERO)

    for st in stocks:
        bp = pools.get(st.id)
        if bp is None:
            violations.append(f"Missing BorrowingPoolInventory for stock {st.symbol}")
            continue
        if bp.available_pool_shares + bp.reserved_pool_shares + bp.borrowed_shares != bp.total_pool_shares:
            violations.append(f"Borrowing pool sum violation for {st.symbol}")
        exp_pool_res = ord_borrow_by_stock.get(st.id, 0)
        if bp.reserved_pool_shares != exp_pool_res:
            violations.append(
                f"Pool reserved shares mismatch for {st.symbol}: pool={bp.reserved_pool_shares} vs orders={exp_pool_res}"
            )
        total_short_open = sum(sp.borrowed_shares for sp in shorts if sp.stock_id == st.id)
        if bp.borrowed_shares != total_short_open:
            violations.append(
                f"Pool borrowed shares mismatch for {st.symbol}: pool={bp.borrowed_shares} vs short_positions={total_short_open}"
            )

        total_long = sum(
            h.available_shares + h.reserved_shares for h in holdings if h.stock_id == st.id
        )
        admin_settled_qty = admin_settled_qty_map.get(st.id, 0)
        # Every short sale sold borrowed shares to a long buyer (+1 Long, +1 ShortBorrowed -> Long - ShortBorrowed == Initial).
        # When an open short is administratively liquidated at end of Phase B without buying back from a long holder,
        # ShortBorrowed drops by admin_settled_qty while the buyer keeps their long share, so:
        # total_long - total_short_open - admin_settled_qty == n_players * st.initial_allocation_shares
        expected_net_shares = n_players * st.initial_allocation_shares
        actual_net_shares = total_long - total_short_open - admin_settled_qty
        if actual_net_shares != expected_net_shares:
            violations.append(
                f"Global share conservation violated for {st.symbol}: "
                f"long({total_long}) - short({total_short_open}) - admin_settled({admin_settled_qty}) "
                f"= {actual_net_shares} != expected {expected_net_shares}"
            )

    # 5. Global Zero-Sum Cash Conservation
    total_player_cash = sum(
        (
            to_dec(pf.available_cash + pf.order_reserved_cash + pf.short_margin_locked + pf.short_proceeds_locked)
            for pf in portfolios.values()
        ),
        ZERO,
    )
    total_unfunded_debt = sum((to_dec(pf.unfunded_settlement_debt) for pf in portfolios.values()), ZERO)
    total_fees = to_dec(
        (
            await session.execute(
                select(func.coalesce(func.sum(OrderExecution.fee_amount), ZERO)).where(
                    OrderExecution.game_id == game_id
                )
            )
        ).scalar_one()
    )
    # Cash actually paid out to central settlement pool = admin_settled_cash_total - total_unfunded_debt
    admin_cash_collected = to_dec(admin_settled_cash_total - total_unfunded_debt)
    expected_total_cash = to_dec(Decimal(n_players) * to_dec(game.initial_cash))
    reconstructed_cash = to_dec(total_player_cash + admin_cash_collected + total_fees)

    if reconstructed_cash != expected_total_cash:
        violations.append(
            f"Global cash conservation violated: player_cash({total_player_cash}) + "
            f"admin_settled_paid({admin_cash_collected}) + fees({total_fees}) = "
            f"{reconstructed_cash} != expected {expected_total_cash}"
        )

    return InvariantAuditReport(
        passed=len(violations) == 0,
        participant_count=n_players,
        total_player_cash=total_player_cash,
        expected_total_cash=expected_total_cash,
        violations=violations,
    )
