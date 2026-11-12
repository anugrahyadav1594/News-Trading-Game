import json
import logging
from decimal import Decimal
from typing import Any
import uuid

import redis.asyncio as aioredis
from fakeredis import FakeServer
import fakeredis.aioredis as fake_aioredis

from app.core.config import get_settings

logger = logging.getLogger(__name__)


def _json_default(obj: Any) -> Any:
    if isinstance(obj, Decimal):
        return str(obj)
    if isinstance(obj, uuid.UUID):
        return str(obj)
    if hasattr(obj, "isoformat"):
        return obj.isoformat()
    raise TypeError(f"Object of type {type(obj).__name__} is not JSON serializable")


class RedisCoordBus:
    """
    Non-authoritative coordination & real-time pub/sub adapter.
    PostgreSQL remains the sole financial source of truth.
    Supports production Redis 7 and seamless FakeRedis fallback for isolated sandbox/tests.
    """

    def __init__(self) -> None:
        self._client: aioredis.Redis | None = None
        self._fake_server: FakeServer | None = None
        self.using_fallback: bool = False

    async def connect(self) -> None:
        if self._client is not None:
            return
        settings = get_settings()
        try:
            client = aioredis.from_url(
                settings.REDIS_URL,
                encoding="utf-8",
                decode_responses=True,
                socket_connect_timeout=1.5,
            )
            await client.ping()
            self._client = client
            self.using_fallback = False
            logger.info("Connected to external Redis", extra={"structured": {"redis_url": settings.REDIS_URL}})
        except Exception as exc:
            if not settings.USE_FAKE_REDIS_FALLBACK:
                raise
            self._fake_server = FakeServer()
            self._client = fake_aioredis.FakeRedis(server=self._fake_server, decode_responses=True)
            self.using_fallback = True
            logger.info(
                "External Redis unreachable; initialized embedded FakeRedis pub/sub bus",
                extra={"structured": {"reason": str(exc)}},
            )

    @property
    def client(self) -> aioredis.Redis:
        if self._client is None:
            raise RuntimeError("RedisCoordBus is not connected")
        return self._client

    async def publish_json(self, channel: str, data: dict[str, Any]) -> None:
        raw = json.dumps(data, default=_json_default)
        await self.client.publish(channel, raw)

    async def check_rate_limit(self, key: str, limit: int, window_sec: int) -> bool:
        """Sliding/bucketed rate limit check; returns True if allowed, False if exceeded."""
        current = await self.client.incr(key)
        if current == 1:
            await self.client.expire(key, window_sec)
        return current <= limit

    async def next_game_seq(self, game_id: uuid.UUID) -> int:
        return int(await self.client.incr(f"mtt:game:{game_id}:seq"))

    async def current_game_seq(self, game_id: uuid.UUID) -> int:
        val = await self.client.get(f"mtt:game:{game_id}:seq")
        return int(val) if val else 0

    async def close(self) -> None:
        if self._client is not None:
            await self._client.aclose()
            self._client = None


redis_bus = RedisCoordBus()
