import asyncio
import os
import tempfile
import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from alembic import command
from alembic.config import Config
from pathlib import Path

os.environ["AUTO_SEED_DEMO"] = "false"
os.environ["USE_FAKE_REDIS_FALLBACK"] = "true"
os.environ["ORDER_RATE_LIMIT_PER_10S"] = "10000"

from app.core.redis_bus import redis_bus
from app.db.session import close_db_engine, get_active_database_url, get_session_factory, init_db_engine
from app.main import create_app


@pytest_asyncio.fixture(scope="session", loop_scope="session")
async def test_app():
    tmp_pg = tempfile.mkdtemp(prefix="mtt_pg_pytest_")
    os.environ["EMBEDDED_POSTGRES_DIR"] = tmp_pg
    os.environ["USE_EMBEDDED_POSTGRES"] = "true"

    from app.core.config import get_settings
    get_settings.cache_clear()

    import pgserver
    pg_srv = pgserver.get_server(tmp_pg)
    async_uri = pg_srv.get_uri().replace("postgresql://", "postgresql+asyncpg://", 1)
    init_db_engine(async_uri)

    backend_root = Path(__file__).resolve().parent.parent
    alembic_cfg = Config(str(backend_root / "alembic.ini"))
    alembic_cfg.set_main_option("script_location", str(backend_root / "alembic"))
    alembic_cfg.set_main_option("sqlalchemy.url", get_active_database_url())
    await asyncio.to_thread(command.upgrade, alembic_cfg, "head")

    await redis_bus.connect()
    app = create_app()

    yield app

    await redis_bus.close()
    await close_db_engine()
    pg_srv.cleanup()


@pytest_asyncio.fixture(loop_scope="session")
async def db_session(test_app):
    factory = get_session_factory()
    async with factory() as session:
        yield session


@pytest_asyncio.fixture(loop_scope="session")
async def api_client(test_app):
    transport = ASGITransport(app=test_app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        yield client
