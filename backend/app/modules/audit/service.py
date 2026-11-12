import hashlib
import json
import uuid
from typing import Any
from sqlalchemy import desc, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.audit import AuditLog


def _canonical_json(data: Any) -> str:
    return json.dumps(data, sort_keys=True, default=str, separators=(",", ":"))


async def record_audit_event(
    session: AsyncSession,
    *,
    actor_user_id: uuid.UUID | None,
    actor_role: str,
    action_type: str,
    target_type: str,
    target_id: str,
    game_id: uuid.UUID | None = None,
    before_state: dict[str, Any] | None = None,
    after_state: dict[str, Any] | None = None,
    reason: str | None = None,
    ip_address: str | None = None,
) -> AuditLog:
    """
    Append an immutable, SHA-256 hash-chained audit record.
    Serializes per-game or global audit chain head via advisory lock.
    """
    chain_key = f"mtt:audit:{game_id or 'global'}"
    await session.execute(
        text("SELECT pg_advisory_xact_lock(109, hashtext(:chain_key))"),
        {"chain_key": chain_key},
    )

    stmt = (
        select(AuditLog.record_hash)
        .where(AuditLog.game_id == game_id if game_id else AuditLog.game_id.is_(None))
        .order_by(desc(AuditLog.id))
        .limit(1)
    )
    prev_hash = (await session.execute(stmt)).scalar_one_or_none() or ("0" * 64)

    payload_to_hash = _canonical_json(
        {
            "prev": prev_hash,
            "game_id": str(game_id) if game_id else None,
            "actor_user_id": str(actor_user_id) if actor_user_id else None,
            "actor_role": actor_role,
            "action_type": action_type,
            "target_type": target_type,
            "target_id": target_id,
            "before": before_state,
            "after": after_state,
            "reason": reason,
        }
    )
    digest = hashlib.sha256(payload_to_hash.encode("utf-8")).hexdigest()

    entry = AuditLog(
        game_id=game_id,
        actor_user_id=actor_user_id,
        actor_role=actor_role,
        action_type=action_type,
        target_type=target_type,
        target_id=target_id,
        before_state=before_state,
        after_state=after_state,
        reason=reason,
        ip_address=ip_address,
        prev_record_hash=prev_hash,
        record_hash=digest,
    )
    session.add(entry)
    await session.flush()
    return entry
