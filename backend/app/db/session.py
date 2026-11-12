from contextlib import asynccontextmanager
import logging
import os
from pathlib import Path
from typing import AsyncGenerator

from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker, create_async_engine

from app.core.config import get_settings

logger = logging.getLogger(__name__)

_engine: AsyncEngine | None = None
_session_factory: async_sessionmaker[AsyncSession] | None = None
_embedded_pg_server = None
_active_database_url: str | None = None


def _ensure_embedded_postgres(pgdata_dir: str) -> str:
    global _embedded_pg_server
    if _embedded_pg_server is not None:
        raw_uri = _embedded_pg_server.get_uri()
        return raw_uri.replace("postgresql://", "postgresql+asyncpg://", 1)

    os.environ.setdefault("XDG_RUNTIME_DIR", "/tmp/mtt-runtime")
    rdir = Path(os.environ["XDG_RUNTIME_DIR"])
    rdir.mkdir(parents=True, exist_ok=True)
    rdir.chmod(0o700)
    target = Path(pgdata_dir)
    target.mkdir(parents=True, exist_ok=True)

    import pgserver

    _embedded_pg_server = pgserver.get_server(str(target))
    raw_uri = _embedded_pg_server.get_uri()
    async_uri = raw_uri.replace("postgresql://", "postgresql+asyncpg://", 1)
    logger.info(
        "Started embedded PostgreSQL 16 server",
        extra={"structured": {"pgdata": str(target), "uri": async_uri}},
    )
    return async_uri


def init_db_engine(database_url: str | None = None) -> AsyncEngine:
    global _engine, _session_factory, _active_database_url
    if _engine is not None and (database_url is None or database_url == _active_database_url):
        return _engine

    settings = get_settings()
    resolved_url = database_url or settings.DATABASE_URL
    if database_url is None and settings.USE_EMBEDDED_POSTGRES:
        resolved_url = _ensure_embedded_postgres(settings.EMBEDDED_POSTGRES_DIR)

    _active_database_url = resolved_url
    _engine = create_async_engine(
        resolved_url,
        pool_size=25,
        max_overflow=50,
        pool_pre_ping=True,
        echo=False,
    )
    _session_factory = async_sessionmaker(
        bind=_engine,
        class_=AsyncSession,
        expire_on_commit=False,
        autoflush=False,
    )
    return _engine


def get_active_database_url() -> str:
    if _active_database_url is None:
        init_db_engine()
    assert _active_database_url is not None
    return _active_database_url


def get_session_factory() -> async_sessionmaker[AsyncSession]:
    if _session_factory is None:
        init_db_engine()
    assert _session_factory is not None
    return _session_factory


async def get_db_session() -> AsyncGenerator[AsyncSession, None]:
    factory = get_session_factory()
    async with factory() as session:
        yield session


@asynccontextmanager
async def atomic_tx(session: AsyncSession) -> AsyncGenerator[AsyncSession, None]:
    """
    Commit-on-exit transaction context manager compatible with FastAPI dependencies
    (e.g., `get_current_user`) that have already triggered SQLAlchemy 2.0 `autobegin`.
    """
    if session.in_transaction():
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
    else:
        async with session.begin():
            yield session


async def close_db_engine() -> None:
    global _engine, _session_factory, _embedded_pg_server
    if _engine is not None:
        await _engine.dispose()
        _engine = None
        _session_factory = None
    if _embedded_pg_server is not None:
        _embedded_pg_server.cleanup()
        _embedded_pg_server = None
