from decimal import Decimal
from functools import lru_cache
from pathlib import Path
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    APP_NAME: str = "NEWS TRADING — MTT"
    ENVIRONMENT: str = "development"
    LOG_LEVEL: str = "INFO"
    LOG_JSON: bool = True
    CORS_ORIGINS: str = "*"

    SECRET_KEY: str = "mtt-super-secret-jwt-key-change-in-production-2026-quantrelic"
    JWT_ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 480

    DATABASE_URL: str = "postgresql+asyncpg://mtt_user:mtt_password@localhost:5432/mtt_exchange"
    USE_EMBEDDED_POSTGRES: bool = True
    EMBEDDED_POSTGRES_DIR: str = str(Path.home() / ".cache" / "mtt_pgdata")

    REDIS_URL: str = "redis://localhost:6379/0"
    USE_FAKE_REDIS_FALLBACK: bool = True

    # Default Tournament Configuration (Overridable per game by Admin)
    DEFAULT_TRADING_DURATION_SEC: int = 2700       # 45 minutes
    DEFAULT_SETTLEMENT_DURATION_SEC: int = 300     # 5 minutes
    DEFAULT_INITIAL_CASH: Decimal = Decimal("500000.0000")
    DEFAULT_OPENING_PRICE: Decimal = Decimal("1000.0000")
    DEFAULT_SHARES_PER_STOCK: int = 100
    DEFAULT_INITIAL_MARGIN_RATIO: Decimal = Decimal("0.5000")
    DEFAULT_MAINTENANCE_MARGIN_RATIO: Decimal = Decimal("0.2500")
    DEFAULT_CRITICAL_MARGIN_RATIO: Decimal = Decimal("0.1250")
    DEFAULT_MARGIN_CALL_GRACE_SEC: int = 60
    DEFAULT_SHORT_POOL_PER_PLAYER: int = 50
    DEFAULT_MIN_SHORT_POOL_SHARES: int = 15000
    DEFAULT_SHORT_LIMIT_PER_STOCK: int = 500
    DEFAULT_TICK_SIZE: Decimal = Decimal("0.0500")
    DEFAULT_MARKET_COLLAR_PCT: Decimal = Decimal("0.1000")
    DEFAULT_SETTLEMENT_VWAP_WINDOW_SEC: int = 300
    DEFAULT_SETTLEMENT_LIQUIDITY_PIVOT: int = 500
    DEFAULT_SETTLEMENT_COLLAR_PCT: Decimal = Decimal("0.1500")

    # Rate Limiting & Broadcast Conflation
    ORDER_RATE_LIMIT_PER_10S: int = 60
    WS_MARKET_TICK_MS: int = 150
    WS_LEADERBOARD_TICK_MS: int = 2000

    # Seed Demo Tournament on Startup (for local/preview convenience)
    AUTO_SEED_DEMO: bool = True
    DEFAULT_ADMIN_EMAIL: str = "admin@quantrelic-mtt.in"
    DEFAULT_ADMIN_PASSWORD: str = "MttAdmin@2026!"


@lru_cache
def get_settings() -> Settings:
    return Settings()
