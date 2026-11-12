import uuid
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession


async def acquire_stock_matching_lock(
    session: AsyncSession,
    game_id: uuid.UUID,
    stock_id: uuid.UUID,
) -> None:
    """
    Serialize all order-book mutations (submit, match, cancel, replace, expire)
    for a single (game_id, stock_id) inside the current PostgreSQL transaction,
    while permitting concurrent trading across different stocks.
    """
    lock_key = f"mtt:book:{game_id}:{stock_id}"
    await session.execute(
        text("SELECT pg_advisory_xact_lock(101, hashtext(:lock_key))"),
        {"lock_key": lock_key},
    )


async def acquire_game_lifecycle_lock(
    session: AsyncSession,
    game_id: uuid.UUID,
) -> None:
    """
    Serialize game-level lifecycle transitions, participant allocation,
    news releases, and end-of-game settlement for a given game_id.
    """
    lock_key = f"mtt:game:{game_id}"
    await session.execute(
        text("SELECT pg_advisory_xact_lock(102, hashtext(:lock_key))"),
        {"lock_key": lock_key},
    )
