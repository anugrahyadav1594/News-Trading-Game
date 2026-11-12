import asyncio
import json
import logging
import uuid
from collections import defaultdict
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any

from fastapi import WebSocket

from app.core.redis_bus import redis_bus
from app.models.enums import UserRole

logger = logging.getLogger(__name__)


def _serialize_default(obj: Any) -> Any:
    if isinstance(obj, Decimal):
        return str(obj)
    if isinstance(obj, uuid.UUID):
        return str(obj)
    if hasattr(obj, "isoformat"):
        return obj.isoformat()
    raise TypeError(f"Not serializable: {type(obj)}")


class ClientConnection:
    def __init__(
        self,
        *,
        websocket: WebSocket,
        user_id: uuid.UUID,
        role: str,
        game_participant_id: uuid.UUID | None,
    ) -> None:
        self.websocket = websocket
        self.user_id = user_id
        self.role = role
        self.game_participant_id = game_participant_id


class RealtimeGameHub:
    """
    Multiplexed real-time WebSocket hub with:
      - Monotonic per-game sequence numbers (`seq`) for client gap detection & resynchronization.
      - Role-scoped private & admin channels (`private:user:{gp_id}`, `admin:surveillance`).
      - Conflated/dirty-flag market-data marking so bursts of orders coalesce into 150ms ticks
        instead of flooding 1,000 connected players on every individual order.
    """

    def __init__(self) -> None:
        self._connections_by_game: dict[uuid.UUID, set[ClientConnection]] = defaultdict(set)
        self._dirty_stocks_by_game: dict[uuid.UUID, set[str]] = defaultdict(set)
        self._dirty_leaderboard_games: set[uuid.UUID] = set()
        self._lock = asyncio.Lock()

    async def register(self, game_id: uuid.UUID, conn: ClientConnection) -> None:
        async with self._lock:
            self._connections_by_game[game_id].add(conn)

    async def unregister(self, game_id: uuid.UUID, conn: ClientConnection) -> None:
        async with self._lock:
            conns = self._connections_by_game.get(game_id)
            if conns and conn in conns:
                conns.remove(conn)

    def active_games_with_clients(self) -> list[uuid.UUID]:
        return [gid for gid, conns in self._connections_by_game.items() if len(conns) > 0]

    def mark_stock_dirty(self, game_id: uuid.UUID, symbol: str) -> None:
        self._dirty_stocks_by_game[game_id].add(symbol)
        self._dirty_leaderboard_games.add(game_id)

    def pop_dirty_stocks(self, game_id: uuid.UUID) -> set[str]:
        s = self._dirty_stocks_by_game.pop(game_id, set())
        return s

    def pop_dirty_leaderboard_games(self) -> set[uuid.UUID]:
        g = set(self._dirty_leaderboard_games)
        self._dirty_leaderboard_games.clear()
        return g

    async def broadcast_public(
        self,
        *,
        game_id: uuid.UUID,
        channel: str,
        event: str,
        phase: str,
        game_elapsed_ms: int,
        payload: dict[str, Any],
    ) -> int:
        seq = await redis_bus.next_game_seq(game_id)
        envelope = {
            "seq": seq,
            "channel": channel,
            "event": event,
            "game_id": str(game_id),
            "server_ts": datetime.now(timezone.utc).isoformat(),
            "game_elapsed_ms": game_elapsed_ms,
            "phase": phase,
            "payload": payload,
        }
        await redis_bus.publish_json(f"mtt:ws:{game_id}:public", envelope)
        raw = json.dumps(envelope, default=_serialize_default)
        await self._fanout(game_id, raw, target_filter=None)
        return seq

    async def send_private_to_participant(
        self,
        *,
        game_id: uuid.UUID,
        game_participant_id: uuid.UUID,
        event: str,
        phase: str,
        game_elapsed_ms: int,
        payload: dict[str, Any],
    ) -> None:
        seq = await redis_bus.current_game_seq(game_id)
        envelope = {
            "seq": seq,
            "channel": f"private:participant:{game_participant_id}",
            "event": event,
            "game_id": str(game_id),
            "server_ts": datetime.now(timezone.utc).isoformat(),
            "game_elapsed_ms": game_elapsed_ms,
            "phase": phase,
            "payload": payload,
        }
        raw = json.dumps(envelope, default=_serialize_default)
        await self._fanout(
            game_id,
            raw,
            target_filter=lambda c: c.game_participant_id == game_participant_id,
        )

    async def send_admin_surveillance(
        self,
        *,
        game_id: uuid.UUID,
        event: str,
        phase: str,
        game_elapsed_ms: int,
        payload: dict[str, Any],
    ) -> None:
        seq = await redis_bus.current_game_seq(game_id)
        envelope = {
            "seq": seq,
            "channel": "admin:surveillance",
            "event": event,
            "game_id": str(game_id),
            "server_ts": datetime.now(timezone.utc).isoformat(),
            "game_elapsed_ms": game_elapsed_ms,
            "phase": phase,
            "payload": payload,
        }
        raw = json.dumps(envelope, default=_serialize_default)
        await self._fanout(
            game_id,
            raw,
            target_filter=lambda c: c.role == UserRole.ADMIN.value,
        )

    async def _fanout(self, game_id: uuid.UUID, raw_message: str, target_filter=None) -> None:
        conns = list(self._connections_by_game.get(game_id, set()))
        if not conns:
            return
        stale: list[ClientConnection] = []
        for conn in conns:
            if target_filter is not None and not target_filter(conn):
                continue
            try:
                await conn.websocket.send_text(raw_message)
            except Exception:
                stale.append(conn)
        if stale:
            async with self._lock:
                active = self._connections_by_game.get(game_id)
                if active:
                    for s in stale:
                        active.discard(s)


ws_hub = RealtimeGameHub()
