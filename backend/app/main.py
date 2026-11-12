from contextlib import asynccontextmanager
import logging
from pathlib import Path
import uuid

from alembic import command
from alembic.config import Config
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import AsyncEngine

from app.api.v1.router import api_v1_router
from app.api.v1.ws import ws_router
from app.core.config import get_settings
from app.core.exceptions import ExchangeError
from app.core.logging import configure_logging, correlation_id_ctx
from app.core.redis_bus import redis_bus
from app.db.session import close_db_engine, get_active_database_url, get_session_factory, init_db_engine
from app.modules.tournament.seed_demo import ensure_demo_tournament_seeded
from app.workers.runtime import background_loops

logger = logging.getLogger(__name__)


def _upgrade_with_connection(connection: Connection, alembic_cfg: Config) -> None:
    alembic_cfg.attributes["connection"] = connection
    command.upgrade(alembic_cfg, "head")


async def apply_alembic_migrations_async(engine: AsyncEngine) -> None:
    backend_root = Path(__file__).resolve().parent.parent
    alembic_cfg = Config(str(backend_root / "alembic.ini"))
    alembic_cfg.set_main_option("script_location", str(backend_root / "alembic"))
    alembic_cfg.set_main_option("sqlalchemy.url", get_active_database_url())
    alembic_cfg.attributes["configure_logger"] = False
    async with engine.begin() as conn:
        await conn.run_sync(_upgrade_with_connection, alembic_cfg)
    logger.info("Alembic database schema verified at head (28 tables + immutability triggers)")


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()
    configure_logging(settings.LOG_LEVEL, settings.LOG_JSON)
    engine = init_db_engine()
    await apply_alembic_migrations_async(engine)
    await redis_bus.connect()

    if settings.AUTO_SEED_DEMO:
        factory = get_session_factory()
        async with factory() as session:
            async with session.begin():
                await ensure_demo_tournament_seeded(session)

    background_loops.start()
    logger.info(
        "NEWS TRADING — MTT Exchange Engine ONLINE (API: /api/v1, Docs: /docs, WS: /ws/v1)",
    )
    try:
        yield
    finally:
        await background_loops.stop()
        await redis_bus.close()
        await close_db_engine()


def create_app() -> FastAPI:
    settings = get_settings()
    app = FastAPI(
        title="NEWS TRADING — MTT Exchange API",
        version="1.0.0",
        description="Mumbai Trading Tournament — Independent Peer-to-Peer Simulated Stock Exchange",
        lifespan=lifespan,
    )

    origins = [o.strip() for o in settings.CORS_ORIGINS.split(",") if o.strip()]
    app.add_middleware(
        CORSMiddleware,
        allow_origins=origins or ["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @app.middleware("http")
    async def correlation_id_middleware(request: Request, call_next):
        cid = request.headers.get("X-Correlation-ID") or str(uuid.uuid4())
        token = correlation_id_ctx.set(cid)
        try:
            response = await call_next(request)
            response.headers["X-Correlation-ID"] = cid
            return response
        finally:
            correlation_id_ctx.reset(token)

    @app.exception_handler(ExchangeError)
    async def handle_exchange_error(_request: Request, exc: ExchangeError) -> JSONResponse:
        return JSONResponse(
            status_code=exc.status_code,
            content={
                "error": {
                    "code": exc.code,
                    "message": exc.message,
                    "details": exc.details,
                }
            },
        )

    @app.get("/")
    async def root_status() -> dict:
        return {
            "service": "NEWS TRADING — MTT Exchange Engine",
            "organizer": "Quantrelic Analytics",
            "status": "online",
            "docs": "/docs",
            "simulation_disclaimer": "Fictional tournament simulation platform — not real NSE/BSE data.",
        }

    @app.get("/health/live")
    async def health_live() -> dict:
        return {"status": "ok"}

    app.include_router(api_v1_router)
    app.include_router(ws_router)
    return app


app = create_app()
