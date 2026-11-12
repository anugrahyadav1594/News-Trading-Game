# NEWS TRADING — MTT: Master System Architecture & Financial Engineering Specification

**Project:** Mumbai Trading Tournament (MTT) — Independent Multiplayer Simulated Stock Exchange  
**Organizer Context:** Quantrelic Analytics (Standalone Tournament Platform — Zero coupling to Insyte/Quantrelic production apps)  
**Document Status:** Phase 0 — Initial Architecture Deliverable (Awaiting Approval Before Implementation)  
**Simulation Notice:** Every stock price, company metric, order book, trade, and news item in this system is 100% simulated for competitive tournament play and carries mandatory simulation watermarks.

---

## 0. Development Environment Audit

Per Section 17 (Rule 1–3), the workspace and runtime environment were inspected prior to writing any code:

- **Repository Root:** `/home/user/News-Trading-Game` (clean independent Git repository on branch `arena/e2e90572-news-trading-game`, containing only `README.md`; no external or unrelated repositories exist or will be modified).
- **OS / Compute:** Debian GNU/Linux 12 (Bookworm), x86_64, 2 vCPUs, 3.8 GiB RAM, 20 GiB free disk.
- **Runtimes & Tooling:**
  - Node.js `v22.22.3`, `npm 10.9.8`, `yarn 1.22.22`.
  - System Python `3.11.2`, with `uv` (`0.13.x`) available via PyPI to provision standalone **Python 3.12** directly from GitHub (`astral-sh/python-build-standalone`).
  - **PostgreSQL & Redis Strategy:**
    - **Production Deployment:** Full `Dockerfile`s and `docker-compose.yml` / `docker-compose.prod.yml` orchestrating `postgres:16-alpine`, `redis:7-alpine`, `backend` (Python 3.12 + FastAPI/Uvicorn), `frontend` (Next.js standalone), and automated `pg_dump` backup sidecar.
    - **Sandbox Verification & CI Testing:** Because container sandboxes do not run a nested Docker daemon, automated tests and live preview servers will run against a genuine embedded **PostgreSQL** server binary (`pgserver` wheel) so all SQLAlchemy 2.0 queries, Alembic migrations, `NUMERIC(18,4)` constraints, row-level locks (`SELECT ... FOR UPDATE`), and transaction-scoped advisory locks (`pg_advisory_xact_lock`) execute on real PostgreSQL, paired with a dual-mode Redis adapter (`redis.asyncio` in production; `fakeredis.aioredis` + in-process pub/sub broker when no external Redis daemon is bound).
  - **Preview Networking:** Next.js frontend binds to `0.0.0.0:3006` and proxies `/api/*`, `/health/*`, and `/ws/*` to FastAPI (`0.0.0.0:8000`) using relative browser paths so browser clients never call `localhost` directly.

---

## 1. Complete System Architecture

### 1.1 High-Level Component Topology

```
┌──────────────────────────────────────────────────────────────────────────────────────┐
│                              CLIENT TIER (Desktop Web)                               │
│                                                                                      │
│  ┌─────────────────────────────────────┐    ┌─────────────────────────────────────┐  │
│  │       PLAYER TRADING TERMINAL       │    │    ADMIN NEWS & EXCHANGE CONTROL    │  │
│  │  Next.js + React + TS + Tailwind    │    │  Game Setup • News Studio •         │  │
│  │  Zustand Store • Lightweight Charts │    │  Surveillance • Circuit Breakers    │  │
│  └──────────────┬───────────┬──────────┘    └──────────┬───────────────┬──────────┘  │
└─────────────────┼───────────┼──────────────────────────┼───────────────┼─────────────┘
                  │ HTTPS     │ WSS (/ws/v1)             │ HTTPS         │ WSS (/ws/v1)
                  ▼           ▼                          ▼               ▼
┌──────────────────────────────────────────────────────────────────────────────────────┐
│                       FASTAPI APPLICATION & GATEWAY TIER (Python 3.12)               │
│                                                                                      │
│  ┌────────────────┐  ┌──────────────────┐  ┌──────────────────┐  ┌────────────────┐  │
│  │ Auth & RBAC    │  │ Rate Limiter &   │  │ Idempotency      │  │ WebSocket Hub  │  │
│  │ (JWT + Single  │  │ Anti-Replay      │  │ Middleware       │  │ & State Resync │  │
│  │  Seat Guard)   │  │ Guard            │  │ (ClientOrderKey) │  │ (Seq Cursors)  │  │
│  └───────┬────────┘  └────────┬─────────┘  └────────┬─────────┘  └────────▲───────┘  │
│          └────────────────────┴──────────┬──────────┴─────────────────────┤          │
│                                          ▼                                │          │
│  ┌────────────────────────────────────────────────────────────────────────┴───────┐  │
│  │                         DOMAIN ENGINE LAYER (Modular)                          │  │
│  │                                                                                │  │
│  │  ┌──────────────────┐  ┌──────────────────┐  ┌──────────────────────────────┐  │  │
│  │  │ Tournament &     │  │ Central Matching │  │ Portfolio & Double-Entry     │  │  │
│  │  │ Clock Engine     │  │ Engine (CDA)     │  │ Ledger Accounting Engine     │  │  │
│  │  │ (45m + 5m FSM)   │  │ Price-Time Prior.│  │ Cash + Share + Reservations  │  │  │
│  │  └────────┬─────────┘  └────────┬─────────┘  └──────────────┬───────────────┘  │  │
│  │           │                     │                           │                  │  │
│  │  ┌────────▼─────────┐  ┌────────▼─────────┐  ┌──────────────▼───────────────┐  │  │
│  │  │ Short-Selling &  │  │ Market Pricing & │  │ Deterministic News &         │  │  │
│  │  │ Margin Risk      │  │ Valuation Engine │  │ Exposure Simulation Engine   │  │  │
│  │  │ Engine (Pool)    │  │ Ref + LTP + MTM  │  │ 25+ Cats • Chains • Approval │  │  │
│  │  └────────┬─────────┘  └────────┬─────────┘  └──────────────┬───────────────┘  │  │
│  │           │                     │                           │                  │  │
│  │  ┌────────▼─────────────────────▼───────────────────────────▼───────────────┐  │  │
│  │  │        Settlement, Final Ranking & Immutable Audit Trail Engine          │  │  │
│  │  └──────────────────────────────────────────────────────────────────────────┘  │  │
│  └───────────────────────────────────────┬────────────────────────────────────────┘  │
└──────────────────────────────────────────┼───────────────────────────────────────────┘
                                           │
                     ┌─────────────────────┴─────────────────────┐
                     ▼                                           ▼
┌─────────────────────────────────────────┐ ┌──────────────────────────────────────────┐
│     POSTGRESQL 16 (Authoritative DB)    │ │      REDIS 7 (Coordination & Fanout)     │
│  • ACID Financial Transactions          │ │  • Pub/Sub Event Bus (News, Fills, Clock)│
│  • Immutable Cash & Share Ledgers       │ │  • Conflated Market Data Tick Coalescer  │
│  • Per-Stock Advisory Serialization     │ │  • Sliding-Window API Rate Limiting      │
│  • Orders, Trades, Short Pool, Audit    │ │  • Ephemeral WS Session Presence         │
│  • NUMERIC(18,4) Exact Rupee Arithmetic │ │  (NEVER authoritative for balances)      │
└─────────────────────────────────────────┘ └──────────────────────────────────────────┘
```

### 1.2 Architectural Principles

1. **PostgreSQL as Sole Financial Authority:** Cash balances, share balances, borrowing pool inventory, order state, trades, and final rankings are persisted and validated inside ACID PostgreSQL transactions. Redis is strictly used for real-time pub/sub distribution, market-data coalescing, presence, and rate-limiting.
2. **Exact Fixed-Point Financial Math:** Every monetary value in Python (`decimal.Decimal`) and PostgreSQL (`NUMERIC(18, 4)`) uses exact fixed-point representation. IEEE-754 floating-point (`float`) is banned from accounting, order matching, margin, and settlement calculations. Share quantities are strictly positive integers (`INTEGER` / `BIGINT`).
3. **Per-Stock Serialized Matching with Deadlock-Free Portfolio Locking:** Matching for different stocks (`RELIANCE` vs `INFY`) runs concurrently. Within a single `(game_id, stock_id)`, order submission/cancellation acquires a PostgreSQL transaction-scoped advisory lock `pg_advisory_xact_lock(key)` ensuring deterministic sequence ordering without race conditions. When settling a match between Buyer and Seller, `player_portfolios` and `player_stock_holdings` rows are locked in ascending `(game_participant_id)` order, eliminating deadlocks mathematically.
4. **Server-Authoritative Game Clock & Phase State Machine:** All phase transitions (`DRAFT` $\to$ `LOBBY` $\to$ `MAIN_TRADING` [45:00] $\to$ `SHORT_SETTLEMENT` [05:00] $\to$ `SETTLING` $\to$ `COMPLETED`, plus administrative `PAUSED`) are driven by monotonic server timestamps broadcast to clients via periodic clock-sync heartbeats.
5. **Throttled / Conflated Market Broadcasts:** Under 1,000 concurrent players, individual private order acknowledgements and fills are pushed immediately to the affected participants, whereas public order-book depth (L2 top 15 levels), ticker stats, and leaderboard previews are coalesced and broadcast at configurable tick intervals (`150ms` for L2/tickers, `2s` for live leaderboard preview), preventing $O(N^2)$ WebSocket amplification storms.

---

## 2. Repository and Folder Structure

```text
News-Trading-Game/
├── README.md
├── .env.example
├── .gitignore
├── docker-compose.yml                 # Local & tournament deployment stack
├── docker-compose.prod.yml            # Production overrides, resource limits, backup cron
├── Makefile                           # Common dev, migration, test, simulation commands
├── docs/
│   ├── ARCHITECTURE.md                # Master architectural & mathematical specification
│   ├── PROGRESS.md                    # Living module-by-module development & test tracker
│   ├── API_SPEC.md                    # Detailed REST & WebSocket protocol documentation
│   └── MATH_SPEC.md                   # Pricing, exposure, margin & settlement proofs
├── infra/
│   ├── postgres/
│   │   ├── init.sql
│   │   └── backup.sh                  # Automated pg_dump snapshot & retention script
│   └── nginx/
│       └── nginx.conf                 # Production reverse proxy & WS upgrade config
├── backend/
│   ├── Dockerfile
│   ├── pyproject.toml                 # Python 3.12 dependencies & pytest/ruff/mypy config
│   ├── alembic.ini
│   ├── alembic/
│   │   ├── env.py
│   │   └── versions/                  # Versioned schema migrations
│   ├── app/
│   │   ├── main.py                    # FastAPI app factory, lifespan, middleware wiring
│   │   ├── core/
│   │   │   ├── config.py              # Pydantic Settings (100% env-configurable)
│   │   │   ├── security.py            # Argon2/bcrypt hashing, JWT signing, RBAC guards
│   │   │   ├── logging.py             # Structured JSON logging with correlation IDs
│   │   │   ├── decimal_utils.py       # Tick rounding, paise quantization, assertions
│   │   │   └── exceptions.py          # Structured domain error codes
│   │   ├── db/
│   │   │   ├── base.py                # SQLAlchemy 2.0 DeclarativeBase & naming conventions
│   │   │   ├── session.py             # AsyncEngine & transactional Unit-of-Work
│   │   │   └── locks.py               # Advisory lock & ordered row-lock helpers
│   │   ├── models/                    # Normalized SQLAlchemy 2.0 ORM entities
│   │   │   ├── user.py
│   │   │   ├── game.py
│   │   │   ├── stock.py
│   │   │   ├── portfolio.py
│   │   │   ├── ledger.py
│   │   │   ├── order.py
│   │   │   ├── shorting.py
│   │   │   ├── news.py
│   │   │   ├── market.py
│   │   │   ├── leaderboard.py
│   │   │   └── audit.py
│   │   ├── modules/                   # Strictly decoupled domain engines
│   │   │   ├── auth/                  # Registration, login, single-account-per-game guard
│   │   │   ├── tournament/            # Game creation, atomic init, phase timer FSM
│   │   │   ├── accounting/            # Cash/Share ledgers, reservations, reconciliation
│   │   │   ├── matching/              # Continuous Double Auction engine & order lifecycle
│   │   │   ├── shorting/              # Borrowing pool, collateral, margin calls, forced liq
│   │   │   ├── pricing/               # Reference price model, OHLCV candles, VWAP/MTM
│   │   │   ├── news/                  # 25+ categories, company exposures, event chains
│   │   │   ├── settlement/            # Phase B enforcement, auto short liquidation, ranking
│   │   │   ├── realtime/              # Redis Pub/Sub bus, WS connection manager, coalescer
│   │   │   └── audit/                 # Append-only immutable admin & system audit trail
│   │   ├── api/
│   │   │   ├── deps.py
│   │   │   └── v1/
│   │   │       ├── router.py
│   │   │       ├── auth.py
│   │   │       ├── lobby.py
│   │   │       ├── market.py
│   │   │       ├── orders.py
│   │   │       ├── portfolio.py
│   │   │       ├── leaderboard.py
│   │   │       ├── admin_games.py
│   │   │       ├── admin_news.py
│   │   │       ├── admin_monitor.py
│   │   │       ├── admin_emergency.py
│   │   │       └── ws.py
│   │   └── workers/
│   │       ├── clock_scheduler.py     # Authoritative game clock, scheduled news, order expiry
│   │       ├── margin_monitor.py      # Continuous MTM margin evaluation & liquidation trigger
│   │       └── market_broadcaster.py  # 150ms conflated L2/ticker/candle publisher
│   └── tests/
│       ├── conftest.py
│       ├── invariants.py              # Global accounting & conservation-law verifier
│       ├── unit/
│       ├── integration/
│       └── simulation/                # 150 / 300 / 1,000 concurrent bot tournament runner
└── frontend/
    ├── Dockerfile
    ├── package.json
    ├── tsconfig.json
    ├── next.config.ts                 # API & WS proxy rules + preview host configuration
    ├── src/
    │   ├── app/
    │   │   ├── layout.tsx
    │   │   ├── page.tsx               # Entry / role router + simulation disclaimer banner
    │   │   ├── login/
    │   │   ├── games/[gameId]/
    │   │   │   ├── lobby/             # Screen A: Game Lobby & Countdown
    │   │   │   ├── terminal/          # Screen B: Main Competitive Trading Terminal
    │   │   │   ├── stocks/[symbol]/   # Screen C: Stock Detail & Company Exposure View
    │   │   │   ├── portfolio/         # Screen D: Full Portfolio, Margin & Ledger View
    │   │   │   ├── history/           # Screen E: Order & Trade Execution History
    │   │   │   └── leaderboard/       # Screen F: Live & Final Official Leaderboard
    │   │   └── admin/
    │   │       ├── page.tsx           # Games overview & creation wizard
    │   │       └── games/[gameId]/
    │   │           ├── setup/         # Allocations, pool limits, margin & pricing config
    │   │           ├── news/          # News generator, library, chain builder, scheduler
    │   │           ├── monitor/       # Live 5-stock surveillance, books, shorts, rankings
    │   │           ├── emergency/     # Circuit breakers, stock halts, emergency settle
    │   │           └── audit/         # Immutable timestamped audit log inspector
    │   ├── components/
    │   │   ├── terminal/              # Watchlist, OrderTicket, OrderBook, RecentTrades, NewsFeed
    │   │   ├── charts/                # Lightweight-Charts candle + Ref Price overlay + News markers
    │   │   ├── portfolio/             # HoldingsTable, ShortPositionsPanel, MarginGauge
    │   │   ├── admin/                 # NewsEditorModal, ImpactPreviewMatrix, EmergencyControls
    │   │   └── ui/                    # High-density dark-orange terminal primitives
    │   ├── stores/                    # Zustand stores (gameClock, marketData, portfolio, wsState)
    │   ├── lib/
    │   │   ├── api.ts                 # Typed REST client with automatic Idempotency-Key generation
    │   │   ├── ws.ts                  # Reconnecting WS client with sequence gap resync
    │   │   └── format.ts              # Indian numbering system formatter (₹10,00,000.00)
    │   └── mocks/                     # Strictly isolated UI preview fixtures (NEVER imported in prod)
    └── tests/
```

---

## 3. Database Entity Relationship Design

All monetary columns use `NUMERIC(18, 4)`. All share counts use `BIGINT` with `CHECK` constraints prohibiting negative available/reserved quantities. Every financial mutation writes immutable ledger rows within the same database transaction as materialized portfolio updates.

### 3.1 Core Identity & Access Tables

1. **`users`**
   - `id` (`UUID`, PK), `email` (`VARCHAR(255)`, UNIQUE, NOT NULL), `username` (`VARCHAR(64)`, UNIQUE, NOT NULL), `password_hash` (`VARCHAR(255)`, NOT NULL), `role` (`ENUM('PLAYER','ADMIN')`, NOT NULL), `is_active` (`BOOLEAN`), `created_at` (`TIMESTAMPTZ`).
2. **`participants`**
   - `id` (`UUID`, PK), `user_id` (`UUID`, FK $\to$ `users.id`, UNIQUE), `tournament_code` (`VARCHAR(32)`, UNIQUE, e.g. `MTT-2026-0142` used for privacy-safe counterparty/leaderboard display), `display_name` (`VARCHAR(120)`), `institution` (`VARCHAR(160)`), `device_fingerprint_hash` (`VARCHAR(128)`), `kyc_verified` (`BOOLEAN`), `created_at`.
3. **`administrator_accounts`**
   - `id` (`UUID`, PK), `user_id` (`UUID`, FK $\to$ `users.id`, UNIQUE), `admin_level` (`ENUM('TOURNAMENT_DIRECTOR','NEWS_DESK','RISK_OFFICER')`), `can_emergency_halt` (`BOOLEAN`), `created_at`.

### 3.2 Tournament, Game Lifecycle & Stock Universe Tables

4. **`games`**
   - `id` (`UUID`, PK), `code` (`VARCHAR(32)`, UNIQUE), `name` (`VARCHAR(160)`), `status` (`ENUM('DRAFT','LOBBY','MAIN_TRADING','PAUSED','SHORT_SETTLEMENT','SETTLING','COMPLETED','CANCELLED')`),
   - **Lifecycle Config:** `trading_duration_sec` (default `2700` = 45m), `settlement_duration_sec` (default `300` = 5m), `scheduled_start_at` (`TIMESTAMPTZ`), `trading_started_at`, `settlement_started_at`, `completed_at`, `paused_at`, `accumulated_pause_ms` (`BIGINT`, default `0`), `news_halted` (`BOOLEAN`, default `FALSE`),
   - **Financial & Risk Config (Admin-configurable before game start):**
     - `initial_cash` (`NUMERIC(18,4)`, default `500000.0000`),
     - `default_opening_price` (`NUMERIC(18,4)`, default `1000.0000`),
     - `default_initial_shares_per_stock` (`BIGINT`, default `100`),
     - `initial_margin_ratio` (`NUMERIC(8,4)`, default `0.5000` = 50%),
     - `maintenance_margin_ratio` (`NUMERIC(8,4)`, default `0.2500` = 25%),
     - `margin_call_grace_sec` (`INTEGER`, default `60`),
     - `short_position_limit_per_stock` (`BIGINT`, configurable max short shares per participant per stock),
     - `market_order_collar_pct` (`NUMERIC(8,4)`, default `0.1000` = 10% slippage protection),
     - `settlement_vwap_window_sec` (`INTEGER`, default `300`),
     - `settlement_liquidity_pivot_shares` (`BIGINT`, default `500`),
     - `settlement_max_deviation_from_ref_pct` (`NUMERIC(8,4)`, default `0.1500`),
     - `allow_simultaneous_long_short` (`BOOLEAN`, default `FALSE`),
     - `transaction_fee_bps` (`NUMERIC(8,4)`, default `0.0000`),
   - `created_by_admin_id` (`UUID`, FK $\to$ `users.id`), `created_at`, `updated_at`.
5. **`game_phases`**
   - `id` (`UUID`, PK), `game_id` (`UUID`, FK $\to$ `games.id`), `phase` (`VARCHAR(32)`), `entered_at` (`TIMESTAMPTZ`), `exited_at` (`TIMESTAMPTZ`, nullable), `triggered_by` (`ENUM('SYSTEM_CLOCK','ADMIN_MANUAL','EMERGENCY')`), `actor_user_id` (`UUID`, nullable), `notes` (`TEXT`).
   - *Index:* `(game_id, entered_at)`.
6. **`stocks`**
   - `id` (`UUID`, PK), `game_id` (`UUID`, FK $\to$ `games.id`), `symbol` (`VARCHAR(16)`: `RELIANCE`, `ICICIBANK`, `TATAMOTORS`, `SUNPHARMA`, `INFY`), `company_name` (`VARCHAR(160)`), `sector` (`VARCHAR(80)`), `opening_price` (`NUMERIC(18,4)`, default `1000.0000`), `tick_size` (`NUMERIC(18,4)`, default `0.0500`), `lot_size` (`INTEGER`, default `1`), `trading_enabled` (`BOOLEAN`, default `TRUE`), `halt_reason` (`VARCHAR(255)`, nullable), `next_order_seq` (`BIGINT`, default `1`).
   - *Unique:* `(game_id, symbol)`.
7. **`company_profiles`**
   - `id` (`UUID`, PK), `stock_id` (`UUID`, FK $\to$ `stocks.id`, UNIQUE), `sub_sectors` (`JSONB`), `description` (`TEXT`), `factor_exposures` (`JSONB` — structured sensitivity weights across 30+ macro/sectoral/input factors in `[-1.0, +1.0]`), `base_volatility` (`NUMERIC(8,4)`), `simulated_market_cap_cr` (`NUMERIC(18,2)`), `simulated_pe_ratio` (`NUMERIC(8,2)`).
8. **`game_participants`**
   - `id` (`UUID`, PK), `game_id` (`UUID`, FK $\to$ `games.id`), `participant_id` (`UUID`, FK $\to$ `participants.id`), `user_id` (`UUID`, FK $\to$ `users.id`), `allocation_initialized` (`BOOLEAN`, default `FALSE`), `allocation_idempotency_key` (`VARCHAR(128)`, UNIQUE), `is_disqualified` (`BOOLEAN`, default `FALSE`), `joined_at` (`TIMESTAMPTZ`).
   - *Anti-Multi-Account Constraints:* `UNIQUE (game_id, participant_id)` and `UNIQUE (game_id, user_id)`.
9. **`initial_allocations`**
   - `id` (`UUID`, PK), `game_id` (`UUID`, FK $\to$ `games.id`), `game_participant_id` (`UUID`, FK $\to$ `game_participants.id`), `stock_id` (`UUID`, FK $\to$ `stocks.id`, nullable for cash row), `asset_type` (`ENUM('CASH','STOCK')`), `quantity` (`BIGINT`, nullable), `cash_amount` (`NUMERIC(18,4)`, nullable), `valuation_at_open` (`NUMERIC(18,4)`), `created_at` (`TIMESTAMPTZ`).
   - *Idempotency Constraint:* `UNIQUE NULLS NOT DISTINCT (game_participant_id, asset_type, stock_id)`.

### 3.3 Portfolio, Double-Entry Ledgers & Short-Selling Tables

10. **`player_portfolios`**
    - `id` (`UUID`, PK), `game_id` (`UUID`, FK), `game_participant_id` (`UUID`, FK, UNIQUE),
    - `available_cash` (`NUMERIC(18,4)`, NOT NULL, `CHECK >= 0`),
    - `order_reserved_cash` (`NUMERIC(18,4)`, NOT NULL, `CHECK >= 0`),
    - `short_margin_locked` (`NUMERIC(18,4)`, NOT NULL, `CHECK >= 0`),
    - `short_proceeds_locked` (`NUMERIC(18,4)`, NOT NULL, `CHECK >= 0`),
    - `unfunded_settlement_debt` (`NUMERIC(18,4)`, NOT NULL, default `0`, `CHECK >= 0` — records any unpaid liability if forced settlement exceeds total cash + liquidated assets, never silently waived!),
    - `realized_pnl` (`NUMERIC(18,4)`, NOT NULL, default `0`),
    - `last_net_worth` (`NUMERIC(18,4)`, NOT NULL, default `1000000.0000`),
    - `peak_net_worth_achieved_at` (`TIMESTAMPTZ` — tracks earliest timestamp current final net worth was reached for deterministic tie-breaking),
    - `version` (`BIGINT`, NOT NULL, default `1`), `updated_at` (`TIMESTAMPTZ`).
11. **`player_stock_holdings`**
    - `id` (`UUID`, PK), `game_id` (`UUID`, FK), `game_participant_id` (`UUID`, FK), `stock_id` (`UUID`, FK),
    - `available_shares` (`BIGINT`, NOT NULL, `CHECK >= 0`),
    - `reserved_shares` (`BIGINT`, NOT NULL, `CHECK >= 0` — locked in open `SELL_LONG` orders),
    - `avg_entry_price` (`NUMERIC(18,4)`, NOT NULL, default `1000.0000`),
    - `realized_pnl` (`NUMERIC(18,4)`, NOT NULL, default `0`),
    - `updated_at` (`TIMESTAMPTZ`).
    - *Unique:* `(game_participant_id, stock_id)`.
12. **`cash_ledger_entries`** *(Immutable — UPDATE/DELETE prohibited)*
    - `id` (`BIGSERIAL`, PK), `game_id` (`UUID`, FK), `game_participant_id` (`UUID`, FK),
    - `entry_type` (`ENUM('INITIAL_GRANT','ORDER_CASH_RESERVE','ORDER_CASH_RELEASE','BUY_SETTLEMENT','SELL_SETTLEMENT','SHORT_MARGIN_RESERVE','SHORT_MARGIN_RELEASE','SHORT_PROCEEDS_LOCK','SHORT_COVER_SETTLEMENT','MARGIN_TOPUP','FORCED_SETTLEMENT_DEBIT','UNFUNDED_LIABILITY_RECORDED','FEE_DEBIT','ADMIN_AUDIT_ADJUSTMENT')`),
    - `delta_available` (`NUMERIC(18,4)`), `delta_order_reserved` (`NUMERIC(18,4)`), `delta_short_margin` (`NUMERIC(18,4)`), `delta_short_proceeds` (`NUMERIC(18,4)`), `delta_unfunded_debt` (`NUMERIC(18,4)`),
    - `balance_available_after` (`NUMERIC(18,4)`), `balance_total_cash_after` (`NUMERIC(18,4)`),
    - `reference_type` (`VARCHAR(32)`: `'INIT'`, `'ORDER'`, `'TRADE'`, `'SETTLEMENT'`, `'ADMIN'`), `reference_id` (`UUID`), `idempotency_key` (`VARCHAR(128)`, UNIQUE), `created_at` (`TIMESTAMPTZ`).
    - *Indexes:* `(game_participant_id, id)`, `(game_id, created_at)`, `(reference_type, reference_id)`.
13. **`share_ledger_entries`** *(Immutable — UPDATE/DELETE prohibited)*
    - `id` (`BIGSERIAL`, PK), `game_id` (`UUID`, FK), `game_participant_id` (`UUID`, FK), `stock_id` (`UUID`, FK),
    - `entry_type` (`ENUM('INITIAL_GRANT','SELL_ORDER_RESERVE','SELL_ORDER_RELEASE','BUY_FILL_CREDIT','SELL_FILL_DEBIT','SHORT_BORROW_OPEN','SHORT_COVER_RETURN','FORCED_SHORT_SETTLEMENT_RETURN','ADMIN_AUDIT_ADJUSTMENT')`),
    - `delta_long_available` (`BIGINT`), `delta_long_reserved` (`BIGINT`), `delta_short_borrowed` (`BIGINT`),
    - `long_available_after` (`BIGINT`), `long_reserved_after` (`BIGINT`), `short_borrowed_after` (`BIGINT`),
    - `reference_type` (`VARCHAR(32)`), `reference_id` (`UUID`), `idempotency_key` (`VARCHAR(128)`, UNIQUE), `created_at` (`TIMESTAMPTZ`).
    - *Indexes:* `(game_participant_id, stock_id, id)`, `(game_id, stock_id, created_at)`.
14. **`borrowing_pool_inventory`**
    - `id` (`UUID`, PK), `game_id` (`UUID`, FK), `stock_id` (`UUID`, FK, UNIQUE),
    - `total_pool_shares` (`BIGINT`, NOT NULL, `CHECK >= 0`),
    - `available_pool_shares` (`BIGINT`, NOT NULL, `CHECK >= 0`),
    - `reserved_pool_shares` (`BIGINT`, NOT NULL, `CHECK >= 0` — locked by resting `SHORT_SELL` orders),
    - `borrowed_shares` (`BIGINT`, NOT NULL, `CHECK >= 0` — currently held in open short positions),
    - `CHECK (available_pool_shares + reserved_pool_shares + borrowed_shares = total_pool_shares)`,
    - `updated_at` (`TIMESTAMPTZ`).
15. **`short_positions`**
    - `id` (`UUID`, PK), `game_id` (`UUID`, FK), `game_participant_id` (`UUID`, FK), `stock_id` (`UUID`, FK),
    - `borrowed_shares` (`BIGINT`, NOT NULL, `CHECK >= 0`),
    - `pending_cover_shares` (`BIGINT`, NOT NULL, `CHECK >= 0` — locked by open `BUY_TO_COVER` orders so player cannot over-cover beyond borrowed quantity),
    - `weighted_avg_open_price` (`NUMERIC(18,4)`, NOT NULL),
    - `sale_proceeds_locked` (`NUMERIC(18,4)`, NOT NULL, `CHECK >= 0`),
    - `margin_collateral_locked` (`NUMERIC(18,4)`, NOT NULL, `CHECK >= 0`),
    - `realized_pnl` (`NUMERIC(18,4)`, NOT NULL, default `0`),
    - `margin_status` (`ENUM('HEALTHY','WARNING','MARGIN_CALL','LIQUIDATING','SETTLED')`, default `'HEALTHY'`),
    - `margin_call_triggered_at` (`TIMESTAMPTZ`, nullable),
    - `updated_at` (`TIMESTAMPTZ`).
    - *Unique:* `(game_participant_id, stock_id)`.
16. **`margin_records`**
    - `id` (`UUID`, PK), `game_id` (`UUID`, FK), `game_participant_id` (`UUID`, FK), `stock_id` (`UUID`, FK), `short_position_id` (`UUID`, FK),
    - `mark_price` (`NUMERIC(18,4)`), `current_liability` (`NUMERIC(18,4)`), `position_equity` (`NUMERIC(18,4)`), `margin_ratio_actual` (`NUMERIC(8,4)`), `maintenance_ratio_req` (`NUMERIC(8,4)`),
    - `event_type` (`ENUM('MTM_CHECK','MARGIN_CALL_ISSUED','MARGIN_CALL_RESOLVED','FORCED_LIQUIDATION_TRIGGERED')`),
    - `created_at` (`TIMESTAMPTZ`).

### 3.4 Exchange Orders, Executions & Order-Book Tables

17. **`orders`**
    - `id` (`UUID`, PK), `game_id` (`UUID`, FK), `game_participant_id` (`UUID`, FK), `stock_id` (`UUID`, FK),
    - `client_order_id` (`VARCHAR(128)`, NOT NULL — idempotency key per participant),
    - `sequence_num` (`BIGINT`, NOT NULL — monotonic per `(game_id, stock_id)` for strict FIFO priority),
    - `intent` (`ENUM('BUY_LONG','SELL_LONG','SHORT_SELL','BUY_TO_COVER')`, NOT NULL),
    - `side` (`ENUM('BUY','SELL')`, NOT NULL),
    - `price_type` (`ENUM('MARKET','LIMIT')`, NOT NULL),
    - `time_in_force` (`ENUM('GTC','IOC','GTD')`, NOT NULL, default `'GTC'`),
    - `limit_price` (`NUMERIC(18,4)`, nullable for `MARKET`, required for `LIMIT`),
    - `collar_price` (`NUMERIC(18,4)` — effective worst-case reservation price for `MARKET` buy/cover orders),
    - `quantity` (`BIGINT`, NOT NULL, `CHECK (quantity > 0)`),
    - `filled_quantity` (`BIGINT`, NOT NULL, default `0`),
    - `remaining_quantity` (`BIGINT`, NOT NULL, `CHECK (remaining_quantity >= 0 AND filled_quantity + remaining_quantity = quantity)`),
    - `reserved_cash` (`NUMERIC(18,4)`, NOT NULL, default `0`),
    - `reserved_long_shares` (`BIGINT`, NOT NULL, default `0`),
    - `reserved_borrow_shares` (`BIGINT`, NOT NULL, default `0`),
    - `status` (`ENUM('OPEN','PARTIALLY_FILLED','FILLED','CANCELLED','EXPIRED','REJECTED')`, NOT NULL),
    - `cancel_reason` (`VARCHAR(120)`, nullable),
    - `replaces_order_id` (`UUID`, FK $\to$ `orders.id`, nullable),
    - `replaced_by_order_id` (`UUID`, FK $\to$ `orders.id`, nullable),
    - `is_forced_liquidation` (`BOOLEAN`, default `FALSE`),
    - `expires_at` (`TIMESTAMPTZ`, nullable), `created_at` (`TIMESTAMPTZ`), `updated_at` (`TIMESTAMPTZ`).
    - *Unique:* `(game_participant_id, client_order_id)`.
    - *Matching Book Indexes:*
      - Bids: `(game_id, stock_id, side, limit_price DESC, sequence_num ASC) WHERE status IN ('OPEN','PARTIALLY_FILLED')`
      - Asks: `(game_id, stock_id, side, limit_price ASC, sequence_num ASC) WHERE status IN ('OPEN','PARTIALLY_FILLED')`
18. **`trades`** *(Immutable Peer-to-Peer Matches)*
    - `id` (`UUID`, PK), `game_id` (`UUID`, FK), `stock_id` (`UUID`, FK), `trade_seq` (`BIGINT`, NOT NULL),
    - `buy_order_id` (`UUID`, FK $\to$ `orders.id`), `sell_order_id` (`UUID`, FK $\to$ `orders.id`),
    - `buyer_participant_id` (`UUID`, FK $\to$ `game_participants.id`), `seller_participant_id` (`UUID`, FK $\to$ `game_participants.id`),
    - `aggressor_side` (`ENUM('BUY','SELL')`),
    - `price` (`NUMERIC(18,4)`, NOT NULL, `CHECK (price > 0)`),
    - `quantity` (`BIGINT`, NOT NULL, `CHECK (quantity > 0)`),
    - `notional_value` (`NUMERIC(18,4)`, NOT NULL),
    - `executed_at` (`TIMESTAMPTZ`, NOT NULL).
    - *Indexes:* `(game_id, stock_id, executed_at DESC)`, `(buyer_participant_id, executed_at DESC)`, `(seller_participant_id, executed_at DESC)`.
19. **`order_executions`** *(Per-Participant Execution & Settlement Legs — covers both P2P Trades and Phase-End Administrative Forced Short Settlements)*
    - `id` (`UUID`, PK), `game_id` (`UUID`, FK), `stock_id` (`UUID`, FK), `game_participant_id` (`UUID`, FK),
    - `order_id` (`UUID`, FK $\to$ `orders.id`, nullable for phase-end administrative settlement),
    - `trade_id` (`UUID`, FK $\to$ `trades.id`, nullable for phase-end administrative settlement),
    - `execution_kind` (`ENUM('P2P_TRADE','ADMIN_FINAL_SHORT_SETTLEMENT')`, NOT NULL),
    - `intent` (`ENUM('BUY_LONG','SELL_LONG','SHORT_SELL','BUY_TO_COVER','AUTO_SHORT_SETTLEMENT')`),
    - `price` (`NUMERIC(18,4)`), `quantity` (`BIGINT`), `gross_amount` (`NUMERIC(18,4)`), `realized_pnl_delta` (`NUMERIC(18,4)`),
    - `counterparty_tournament_code` (`VARCHAR(32)`, `'CENTRAL_SETTLEMENT_POOL'` for administrative settlement),
    - `executed_at` (`TIMESTAMPTZ`).
20. **`order_book_snapshots`**
    - `id` (`BIGSERIAL`, PK), `game_id` (`UUID`, FK), `stock_id` (`UUID`, FK), `bids_json` (`JSONB`), `asks_json` (`JSONB`), `best_bid` (`NUMERIC(18,4)`), `best_ask` (`NUMERIC(18,4)`), `spread` (`NUMERIC(18,4)`), `captured_at` (`TIMESTAMPTZ`).

### 3.5 News Engine, Market Pricing, Leaderboard & Audit Tables

21. **`news_events`**
    - `id` (`UUID`, PK), `game_id` (`UUID`, FK), `event_code` (`VARCHAR(32)`), `chain_id` (`UUID`, nullable), `chain_stage` (`INTEGER`, nullable), `parent_event_id` (`UUID`, FK $\to$ `news_events.id`, nullable),
    - `category` (`VARCHAR(64)` — extensible registry seeded with all 25 required categories),
    - `news_type` (`ENUM('BREAKING','OFFICIAL','RUMOUR','FOLLOW_UP','CONFLICTING','REVERSAL','CHAIN_STAGE')`),
    - `headline` (`VARCHAR(280)`), `body` (`TEXT`),
    - `primary_stock_id` (`UUID`, FK $\to$ `stocks.id`, nullable for pure macro events),
    - `secondary_stock_ids` (`JSONB`), `affected_sectors` (`JSONB`), `factor_shocks` (`JSONB`),
    - `direction` (`ENUM('POSITIVE','NEGATIVE','MIXED')`),
    - `severity` (`NUMERIC(6,4)` in `[0,1]`), `credibility` (`NUMERIC(6,4)` in `[0,1]`), `surprise_factor` (`NUMERIC(6,4)` in `[0,1.5]`), `impact_magnitude` (`NUMERIC(8,4)`), `expected_duration_sec` (`INTEGER`),
    - `reverses_event_id` (`UUID`, FK $\to$ `news_events.id`, nullable),
    - `approval_status` (`ENUM('GENERATED','EDITED','APPROVED','REJECTED','SCHEDULED','RELEASED')`),
    - `simulation_label` (`VARCHAR(120)`, NOT NULL, default `'MTT SIMULATED MARKET EVENT — FICTIONAL'`),
    - `created_by_admin_id` (`UUID`, nullable), `approved_by_admin_id` (`UUID`, nullable), `created_at`, `updated_at`.
22. **`event_impact_mappings`**
    - `id` (`UUID`, PK), `news_event_id` (`UUID`, FK $\to$ `news_events.id`), `stock_id` (`UUID`, FK $\to$ `stocks.id`),
    - `direct_exposure` (`NUMERIC(8,4)`), `indirect_exposure` (`NUMERIC(8,4)`), `macro_sensitivity` (`NUMERIC(8,4)`),
    - `raw_impulse_pct` (`NUMERIC(8,4)`), `damped_log_impulse` (`NUMERIC(10,6)`), `permanent_fraction` (`NUMERIC(6,4)`), `half_life_sec` (`INTEGER`).
    - *Unique:* `(news_event_id, stock_id)`.
23. **`news_releases`**
    - `id` (`UUID`, PK), `game_id` (`UUID`, FK), `news_event_id` (`UUID`, FK, UNIQUE),
    - `release_mode` (`ENUM('IMMEDIATE','SCHEDULED')`), `scheduled_game_second` (`INTEGER`, nullable),
    - `released_at` (`TIMESTAMPTZ`, nullable), `released_by_admin_id` (`UUID`, FK $\to$ `users.id`),
    - `pre_release_ref_prices` (`JSONB`), `post_release_ref_prices` (`JSONB`), `idempotency_key` (`VARCHAR(128)`, UNIQUE).
24. **`market_reference_prices`**
    - `id` (`UUID`, PK), `game_id` (`UUID`, FK), `stock_id` (`UUID`, FK, UNIQUE),
    - `fundamental_ref_price` (`NUMERIC(18,4)`), `cumulative_permanent_log_shift` (`NUMERIC(12,6)`), `active_transient_impulses` (`JSONB`),
    - `last_traded_price` (`NUMERIC(18,4)`), `has_trades` (`BOOLEAN`, default `FALSE`),
    - `best_bid` (`NUMERIC(18,4)`, nullable), `best_ask` (`NUMERIC(18,4)`, nullable),
    - `official_mtm_price` (`NUMERIC(18,4)`), `final_settlement_price` (`NUMERIC(18,4)`, nullable),
    - `total_volume` (`BIGINT`, default `0`), `rolling_vwap` (`NUMERIC(18,4)`, nullable), `realized_volatility_pct` (`NUMERIC(8,4)`, default `0`),
    - `updated_at` (`TIMESTAMPTZ`).
25. **`market_price_history`**
    - `id` (`BIGSERIAL`, PK), `game_id` (`UUID`, FK), `stock_id` (`UUID`, FK), `interval_sec` (`INTEGER` — `5` and `60`), `bucket_start` (`TIMESTAMPTZ`),
    - `open_price` (`NUMERIC(18,4)`), `high_price` (`NUMERIC(18,4)`), `low_price` (`NUMERIC(18,4)`), `close_price` (`NUMERIC(18,4)`),
    - `ref_price_close` (`NUMERIC(18,4)`), `mtm_price_close` (`NUMERIC(18,4)`), `volume` (`BIGINT`), `trade_count` (`INTEGER`).
    - *Unique:* `(game_id, stock_id, interval_sec, bucket_start)`.
26. **`leaderboard_snapshots`**
    - `id` (`UUID`, PK), `game_id` (`UUID`, FK), `game_participant_id` (`UUID`, FK), `snapshot_type` (`ENUM('LIVE','SETTLEMENT_PRE','FINAL_OFFICIAL','ADMIN_AMENDED')`),
    - `rank` (`INTEGER`, NOT NULL), `available_cash` (`NUMERIC(18,4)`), `reserved_cash_total` (`NUMERIC(18,4)`), `long_market_value` (`NUMERIC(18,4)`), `short_liability` (`NUMERIC(18,4)`), `unfunded_debt` (`NUMERIC(18,4)`),
    - `final_net_worth` (`NUMERIC(18,4)`, NOT NULL), `net_pnl` (`NUMERIC(18,4)`, NOT NULL), `return_pct` (`NUMERIC(10,4)`, NOT NULL), `realized_pnl` (`NUMERIC(18,4)`, NOT NULL), `achieved_at` (`TIMESTAMPTZ`), `is_immutable` (`BOOLEAN`, default `FALSE`), `captured_at` (`TIMESTAMPTZ`).
27. **`audit_logs`** *(Immutable Append-Only Table)*
    - `id` (`BIGSERIAL`, PK), `game_id` (`UUID`, FK, nullable), `actor_user_id` (`UUID`, FK, nullable), `actor_role` (`VARCHAR(32)`),
    - `action_type` (`VARCHAR(80)`), `target_type` (`VARCHAR(64)`), `target_id` (`VARCHAR(128)`),
    - `before_state` (`JSONB`), `after_state` (`JSONB`), `reason` (`TEXT`), `ip_address` (`VARCHAR(64)`), `prev_record_hash` (`VARCHAR(64)`), `record_hash` (`VARCHAR(64)`), `created_at` (`TIMESTAMPTZ`).

---

## 4. Exchange Matching Algorithm Design

### 4.1 Supported Order Types & Phase Permissions

Every order specifies `(intent, price_type)` which maps deterministically to book side and phase permissions:

| Order Category | `intent` | Book `side` | `price_type` | Allowed in Phase A (45m) | Allowed in Phase B (5m Settlement) | Pre-Match Reservation |
|---|---|---|---|---|---|---|
| Market Buy | `BUY_LONG` | `BUY` | `MARKET` | Yes | **No** (Speculative open blocked) | `qty × collar_price` from `available_cash` |
| Limit Buy | `BUY_LONG` | `BUY` | `LIMIT` | Yes | **No** (Speculative open blocked) | `qty × limit_price` from `available_cash` |
| Market Sell | `SELL_LONG` | `SELL` | `MARKET` | Yes | **Yes** (Closes existing long) | `qty` from `available_shares` |
| Limit Sell | `SELL_LONG` | `SELL` | `LIMIT` | Yes | **Yes** (Closes existing long) | `qty` from `available_shares` |
| Short Sell | `SHORT_SELL` | `SELL` | `MARKET` / `LIMIT` | Yes | **No** (New shorts blocked) | `qty` from `borrowing_pool` + initial margin from `available_cash` |
| Buy to Cover | `BUY_TO_COVER` | `BUY` | `MARKET` / `LIMIT` | Yes | **Yes** (Closes existing short) | `qty` capped to `borrowed_shares - pending_cover_shares`; excess cash over locked collateral if needed |

### 4.2 Continuous Double Auction (CDA) Execution Pipeline

All operations on `(game_id, stock_id)` run inside a single ACID database transaction:

1. **Idempotency Check:** Query `orders` by `(game_participant_id, client_order_id)`. If found, return existing order state immediately (never double-execute).
2. **Game & Stock Gate:** Verify `game.status` allows `intent`, server clock has not crossed phase boundary, and `stock.trading_enabled == TRUE`.
3. **Per-Stock Serialization Lock:** Execute `SELECT pg_advisory_xact_lock(hashtext(game_id || ':' || stock_id))`. Assign monotonic `sequence_num = stock.next_order_seq++`.
4. **Validation & Atomic Reservation:**
   - Validate integer `quantity >= 1` and `limit_price % tick_size == 0` (for `LIMIT`).
   - Lock submitter's `player_portfolios` / `player_stock_holdings` / `short_positions` row (`FOR UPDATE`).
   - Verify sufficient unencumbered cash, long inventory, or borrowing pool shares + initial margin; write reservation ledger entries.
5. **Price-Time Priority Book Walk:**
   - **Incoming BUY (`BUY_LONG` or `BUY_TO_COVER`):** Select resting `SELL` orders where `status IN ('OPEN','PARTIALLY_FILLED')` and (`price_type == 'MARKET'` with `ask.limit_price <= collar_price`, or `ask.limit_price <= buy.limit_price`), ordered by `limit_price ASC, sequence_num ASC`.
   - **Incoming SELL (`SELL_LONG` or `SHORT_SELL`):** Select resting `BUY` orders where `status IN ('OPEN','PARTIALLY_FILLED')` and (`price_type == 'MARKET'` with `bid.limit_price >= collar_price`, or `bid.limit_price >= sell.limit_price`), ordered by `limit_price DESC, sequence_num ASC`.
   - **Self-Trade Prevention (STP):** If a resting order belongs to the same `game_participant_id`, cancel the resting order (releasing its reservations) rather than matching against oneself, preventing artificial wash-trade LTP manipulation.
6. **Execution at Resting Order's Price ($P_{\text{exec}} = P_{\text{resting}}$):**
   - For each matched resting order:
     - `fill_qty = min(incoming.remaining_quantity, resting.remaining_quantity)`
     - `exec_price = resting.limit_price`
     - Lock counterparty portfolio rows in canonical `game_participant_id` order.
     - Atomically settle Buyer leg (`BUY_LONG` credits shares & refunds `(reserved_unit_price - exec_price) × fill_qty` price improvement to `available_cash`; `BUY_TO_COVER` reduces `short_position.borrowed_shares`, settles from `short_proceeds_locked` + `short_margin_locked`, releases surplus collateral/profit to `available_cash`, and restores `fill_qty` to `borrowing_pool.available_pool_shares`).
     - Atomically settle Seller leg (`SELL_LONG` debits `reserved_shares` and credits `exec_price × fill_qty` to `available_cash`; `SHORT_SELL` moves `fill_qty` from `reserved_pool_shares` $\to$ `borrowed_shares`, locks `exec_price × fill_qty` into `short_proceeds_locked`, and adjusts `short_margin_locked` to exact `initial_margin_ratio × exec_price × fill_qty`).
     - Insert immutable `trades`, `order_executions` (2 legs), `cash_ledger_entries`, and `share_ledger_entries`.
     - Update `market_reference_prices.last_traded_price = exec_price` and `total_volume += fill_qty`.
7. **Post-Walk Remainder Handling:**
   - If `incoming.remaining_quantity > 0`:
     - If `price_type == 'MARKET'` or `time_in_force == 'IOC'`: immediately cancel remainder and release all unused cash/share/borrow reservations in the same transaction.
     - If `price_type == 'LIMIT'` (`GTC` / `GTD`): rest `remaining_quantity` on the order book with active reservations intact.
8. **Cancel & Cancel-Replace:**
   - Cancellation acquires the same per-stock advisory lock, verifies `status IN ('OPEN','PARTIALLY_FILLED')`, transitions status to `CANCELLED`, and atomically releases remaining reserved cash, long shares, or borrowing pool shares.
   - Modification executes atomic cancel-and-replace inside one transaction (new `sequence_num` assigned if quantity increases or price changes).

---

## 5. Short-Selling Accounting Design

### 5.1 Four-Bucket Cash Architecture (Zero Double-Counting Proof)

A common bug in naive trading simulators is crediting short-sale proceeds directly into `available_cash` or miscounting collateral in Net Worth. MTT prevents this via four mutually exclusive, collectively exhaustive cash buckets per participant:

1. $C_{\text{avail}}$ (`available_cash`): Unencumbered cash spendable on new orders or margin.
2. $C_{\text{ord}}$ (`order_reserved_cash`): Cash locked for resting `BUY` orders.
3. $C_{\text{margin}}$ (`short_margin_locked`): Participant's own cash posted as margin collateral backing open/pending short positions.
4. $C_{\text{proc}}$ (`short_proceeds_locked`): Segregated cash proceeds received from buyers when executing `SHORT_SELL` trades (held in escrow until short shares are covered).

Define **Total Reserved/Encumbered Cash**:
$$C_{\text{res\_total}} = C_{\text{ord}} + C_{\text{margin}} + C_{\text{proc}}$$
And **Total Cash Owned**:
$$C_{\text{total}} = C_{\text{avail}} + C_{\text{res\_total}}$$

#### Worked Proof of Accounting Conservation

1. **Initial Grant:** $C_{\text{avail}} = ₹5,00,000$, $C_{\text{res\_total}} = 0$, Long Value $V_{\text{long}} = ₹5,00,000$, Short Liability $L_{\text{short}} = 0$.  
   $$\text{Net Worth} = C_{\text{avail}} + C_{\text{res\_total}} + V_{\text{long}} - L_{\text{short}} = ₹10,00,000.$$
2. **Open Short Sell of 10 shares @ ₹1,000** (with Initial Margin $m_0 = 50\%$):
   - Buyer pays ₹10,000 $\implies C_{\text{proc}}$ increases by $+₹10,000$ (real peer-to-peer cash transferred from Buyer!).
   - Seller posts $50\% \times ₹10,000 = ₹5,000$ margin from $C_{\text{avail}} \to C_{\text{margin}}$.
   - State immediately after trade: $C_{\text{avail}} = ₹4,95,000$, $C_{\text{margin}} = ₹5,000$, $C_{\text{proc}} = ₹10,000 \implies C_{\text{total}} = ₹5,10,000$. Short Liability $L_{\text{short}} = 10 \times ₹1,000 = ₹10,000$.
   - **Net Worth** $= ₹4,95,000 + (₹5,000 + ₹10,000) + ₹5,00,000 - ₹10,000 = \mathbf{₹10,00,000}$!
   - Equivalent Unrealized P&L identity:
     $$\text{Net Worth} = C_{\text{avail}} + C_{\text{ord}} + C_{\text{margin}} + V_{\text{long}} + \underbrace{(C_{\text{proc}} - L_{\text{short}})}_{\text{Short Unrealized P\&L}}$$
3. **Price Rises to ₹1,150:** $L_{\text{short}} = ₹11,500$, Short Unrealized P&L $= ₹10,000 - ₹11,500 = -₹1,500$, Net Worth $= ₹9,98,500$.
   - Position Equity $= (C_{\text{proc}} + C_{\text{margin}}) - L_{\text{short}} = ₹15,000 - ₹11,500 = ₹3,500$.
   - Actual Margin Ratio $= \frac{₹3,500}{₹11,500} = 30.43\% > m_{\text{maint}} (25\%)$ $\to$ `HEALTHY`.
4. **Price Rises to ₹1,220 (Margin Call & Forced Liquidation):**
   - $L_{\text{short}} = ₹12,200$, Position Equity $= ₹15,000 - ₹12,200 = ₹2,800$, Margin Ratio $= \frac{₹2,800}{₹12,200} = 22.95\% < 25\%$.
   - Margin monitor records a `MARGIN_CALL` in `margin_records` and notifies player via WebSocket; if unaddressed within `margin_call_grace_sec` or if ratio breaches stop-out threshold (configurable, e.g. $12.5\%$), engine cancels margin-consuming orders and submits forced `BUY_TO_COVER` order(s).
5. **Buy to Cover 10 shares @ ₹920 (Profitable Close):**
   - Seller of cover trade receives $10 \times ₹920 = ₹9,200$ paid out of $C_{\text{proc}}$ ($₹10,000$).
   - Remaining $₹800$ profit in $C_{\text{proc}}$ plus $₹5,000$ in $C_{\text{margin}}$ ($= ₹5,800$) release to $C_{\text{avail}} \implies C_{\text{avail}} = ₹5,00,800$, $C_{\text{proc}} = 0$, $C_{\text{margin}} = 0$, $L_{\text{short}} = 0$.
   - 10 shares return to `borrowing_pool_inventory.available_pool_shares`.
   - Realized P&L $= +₹800$, Net Worth $= ₹10,00,800$.
6. **Phase B End ($T = 50:00$) Unsettled Short Administrative Liquidation:**
   - Any remaining `borrowed_shares > 0` are settled at Official Final Settlement Price $P_i^{\text{settle}}$.
   - Cash obligation $O = \text{borrowed\_shares} \times P_i^{\text{settle}}$ is deducted in priority order from: (1) $C_{\text{proc}}$, (2) $C_{\text{margin}}$, (3) $C_{\text{avail}}$.
   - If $O > C_{\text{proc}} + C_{\text{margin}} + C_{\text{avail}}$, cash buckets go to `0.0000` and the exact shortfall $D = O - (C_{\text{proc}} + C_{\text{margin}} + C_{\text{avail}})$ is recorded in `unfunded_settlement_debt` (`UNFUNDED_LIABILITY_RECORDED` ledger entry). Borrowed shares are returned to the central borrowing pool, trading is locked, and Final Net Worth subtracts `unfunded_settlement_debt` (`Long Stock Market Value - unfunded_settlement_debt`), allowing negative or reduced net worth without ever silently forgiving debt!

---

## 6. Market Pricing Mathematical Specification

### 6.1 Three-Price Architecture

For each stock $i \in \{1..5\}$ at server time $t$:

1. **Fundamental Reference Price $P_i^{\text{ref}}(t)$:** News-driven theoretical valuation ($P_i^{\text{ref}}(0) = ₹1,000.00$).
2. **Last Traded Price $P_i^{\text{ltp}}(t)$:** Price of the latest executed P2P transaction (never fabricated).
3. **Order-Book Executable Prices $B_i(t), A_i(t)$:** Best Bid and Best Ask currently resting on the book.

### 6.2 Deterministic Multi-Factor News Impact Model

Let $X_i(t) = \ln\!\left(\frac{P_i^{\text{ref}}(t)}{P_{i,0}}\right)$ denote the fundamental log-price relative to $P_{i,0} = ₹1,000$. Using log-returns guarantees strict positivity $P_i^{\text{ref}}(t) > 0$ and time-symmetry ($+10\%$ followed by reversal $-10\%$ in log space returns to exact ₹1,000.00).

When news event $e$ is released at $t_e$:

1. **Raw Exposure Score $E_{i,e}$:**
   $$E_{i,e} = \alpha_{\text{dir}} \, d_{i,e} + \alpha_{\text{ind}} \, u_{i,e} + \alpha_{\text{sec}} \sum_{f \in \mathcal{F}} \beta_{i,f} \, s_{e,f}$$
   where:
   - $d_{i,e} \in [-1, +1]$: direct company impact signed weight (`0` if unaffected directly),
   - $u_{i,e} \in [-1, +1]$: indirect / competitor / supply-chain spillover weight,
   - $\beta_{i,f} \in [-1, +1]$: stock $i$'s structured exposure to macro/sector factor $f$,
   - $s_{e,f} \in [-1, +1]$: event $e$'s signed shock to factor $f$,
   - $(\alpha_{\text{dir}}, \alpha_{\text{ind}}, \alpha_{\text{sec}})$: configurable blend weights (default `1.0, 0.5, 0.6`).

2. **Raw Log-Return Impulse $r_{i,e}$:**
   $$r_{i,e} = \gamma_{\max} \cdot E_{i,e} \cdot \sigma_e \cdot \kappa_e \cdot \xi_e$$
   where $\sigma_e \in [0,1]$ is event severity, $\kappa_e \in [0,1]$ is source credibility (e.g. Rumour $\kappa \approx 0.35$, Official Filing $\kappa = 1.0$), $\xi_e \in [0, 1.5]$ is surprise factor, and $\gamma_{\max}$ is configurable single-event scale (default `0.18` $\approx 18\%$ max unlevered single-event log move).

3. **Event-Chain Incremental Pricing & Anti-Compounding Dampener:**
   - **Chain Delta Rule:** If event $e$ belongs to `chain_id` $c$, let $R_{i,c}^{\text{priced}}$ be the cumulative log impulse already priced by earlier stages of chain $c$:
     - For a **Follow-up / Confirmation**, only the *unpriced incremental surprise* $\Delta r_{i,e} = r_{i,e} - R_{i,c}^{\text{priced}}$ is applied!
     - For a **Reversal / Denial** targeting event $e'$, $\Delta r_{i,e} = -\rho_e \cdot \Delta x_{i,e'}^{\text{active}}(t_e)$ where $\rho_e \in [0,1]$ is reversal completeness (`1.0` = full cancellation).
   - **Overlapping Event Saturation:** Let $A_i(t_e)$ be the active rolling absolute impulse accumulated over trailing window $\tau_{\text{overlap}}$ (default `300s`). Effective damped impulse is:
     $$\Delta x_{i,e} = \frac{\Delta r_{i,e}}{1 + \eta \, |A_i(t_e)|}, \qquad X_i^{\text{clamped}}(t) = \text{clip}\!\left(X_i(t),\, -L_{\max},\, +L_{\max}\right)$$
     preventing unrealistic runaway compounding when several related headlines arrive in rapid succession.

4. **Permanent vs. Transient Impulse Envelope:**
   Each event decomposes into permanent fraction $\theta_e \in [0, 1]$ (default `0.80` for fundamental announcements, `0.25` for unconfirmed rumours) and transient fraction $(1 - \theta_e)$ decaying with duration $D_e = \text{expected\_duration\_sec}$:
   $$X_i(t) = \sum_{e: t_e \le t} \Delta x_{i,e} \left[ \theta_e + (1 - \theta_e)\exp\!\left(-\frac{\ln 2 \cdot (t - t_e)}{D_e}\right) \right]$$
   $$P_i^{\text{ref}}(t) = \text{round\_tick}\!\left(P_{i,0} \cdot \exp(X_i(t))\right)$$

### 6.3 Official Mark-to-Market (MTM) & Final Settlement Price Model

To prevent both (a) ignoring actual peer-to-peer price discovery and (b) thin-book manipulation (e.g., two colluding or erroneous accounts trading 1 share at an extreme price in the final second), the Official MTM / Final Settlement Price $P_i^{\text{mtm}}(t)$ uses a **Liquidity-Credibility Weighted Hybrid Estimator with Manipulation Collars**:

1. Compute trailing window ($W = \text{settlement\_vwap\_window\_sec}$, default `300s`) traded volume $V_i(t; W) = \sum_{k \in \mathcal{T}_i(t-W, t)} q_k$ and volume-weighted execution price:
   $$\text{VWAP}_i(t; W) = \frac{\sum_{k \in \mathcal{T}_i(t-W, t)} p_k \, q_k}{V_i(t; W)} \quad (\text{defined when } V_i > 0)$$
2. Clamp $\text{VWAP}_i$ within configurable manipulation collar $\pm c_{\max}$ (default $\pm 15\%$) around $P_i^{\text{ref}}(t)$:
   $$\widetilde{P}_i^{\text{mkt}}(t) = \text{clip}\!\left(\text{VWAP}_i(t; W),\, (1 - c_{\max}) P_i^{\text{ref}}(t),\, (1 + c_{\max}) P_i^{\text{ref}}(t)\right)$$
3. Compute liquidity credibility weight $\lambda_i(t) \in [0, 1]$ with configurable pivot volume $V_0$ (default `500` shares):
   $$\lambda_i(t) = \frac{V_i(t; W)}{V_i(t; W) + V_0}$$
4. Official Mark-to-Market & Settlement Valuation Price:
   $$P_i^{\text{mtm}}(t) = \text{round\_tick}\!\left(\lambda_i(t) \, \widetilde{P}_i^{\text{mkt}}(t) + \big(1 - \lambda_i(t)\big) P_i^{\text{ref}}(t)\right)$$
   At $t = T_{\text{end}}$ (end of 5-minute settlement phase), $P_i^{\text{settle}} \equiv P_i^{\text{mtm}}(T_{\text{end}})$ is frozen and persisted on `market_reference_prices.final_settlement_price`.

---

## 7. News-Generation Architecture

### 7.1 Extensible Category Registry (25 Built-In + Dynamic Custom Categories)

All 25 mandatory categories are seeded in a structured category registry (`Macro`, `Policy/Regulatory`, `Corporate`, `Operational/Market`), and new categories can be registered via database configuration without code changes:

1. Government policies (`GOVT_POLICY`)
2. Contracts and tenders (`CONTRACTS_TENDERS`)
3. Mergers and acquisitions (`MERGERS_ACQUISITIONS`)
4. Regulatory investigations (`REGULATORY_INVESTIGATION`)
5. Financial results (`FINANCIAL_RESULTS`)
6. Import/export tariffs (`TARIFFS_TRADE_DUTIES`)
7. Tax changes (`TAX_CHANGES`)
8. RBI monetary policies (`RBI_MONETARY_POLICY`)
9. Interest-rate movements (`INTEREST_RATES`)
10. International trade (`INTERNATIONAL_TRADE`)
11. Geopolitical developments (`GEOPOLITICS`)
12. Management changes (`MANAGEMENT_CHANGES`)
13. Corporate governance (`CORPORATE_GOVERNANCE`)
14. Fraud and accounting irregularities (`FRAUD_ACCOUNTING`)
15. Supply-chain disruptions (`SUPPLY_CHAIN`)
16. Commodity price changes (`COMMODITY_PRICES`)
17. Technology breakthroughs (`TECH_BREAKTHROUGH`)
18. Patent disputes (`PATENT_DISPUTES`)
19. Product launches (`PRODUCT_LAUNCH`)
20. Competition and market-share changes (`COMPETITION_MARKET_SHARE`)
21. Legal judgments (`LEGAL_JUDGMENTS`)
22. Environmental regulations (`ENVIRONMENTAL_REGULATION`)
23. Labour disputes (`LABOUR_DISPUTES`)
24. Credit-rating changes (`CREDIT_RATING`)
25. Foreign investment developments (`FOREIGN_INVESTMENT`)

### 7.2 Company Factor Exposure Profiles (5 Indian Reference Stocks)

| Symbol | Company | Sector | Key Positive Sensitivity Factors ($\beta > 0$) | Key Negative Sensitivity Factors ($\beta < 0$) |
|---|---|---|---|---|
| `RELIANCE` | Reliance Industries | Energy, Retail & Telecom | Refining GRMs, Telecom ARPU, Domestic Consumer Demand, Green Hydrogen Subsidies, Import Duty Protection | Windfall Fuel Taxes, Crude Input Spikes (Retail/Petchem), Telecom Spectrum Fees, Antitrust Retail Rules |
| `ICICIBANK` | ICICI Bank | Banking & Financial Services | Credit Growth, CASA Liquidity,FII Inflows, Moderate NIM Expansion, Digital Banking Adoption | RBI CRR/SLR Tightening, NPA Cycle Spike, Unsecured Lending Risk Weights, Sovereign Yield Shock |
| `TATAMOTORS` | Tata Motors | Automotive & EVs | EV Subsidies (FAME/PLI), Global Luxury Auto Demand, Battery Cost Decline, Fleet Electrification Tenders | Auto Import Tariffs (UK/EU/US), Steel/Lithium Spikes, Auto Loan Rate Hikes, Emission Penalty Tightening |
| `SUNPHARMA` | Sun Pharmaceutical | Pharmaceuticals & Healthcare | USFDA Approval/EIR Clearance, Specialty Drug Exclusivity, USD Strengthening (INR Depreciation), Healthcare Spend | USFDA Import Alert/Form 483, NPPA Price Caps, API Supply Disruption, Patent Invalidation |
| `INFY` | Infosys | IT Services & Technology | US/EU Enterprise IT & AI Spend, Large Deal Wins, USD Strengthening (INR Depreciation), Cloud Migration | US Recession/BFSI Cuts, H-1B Visa Restrictions/Fee Hikes, Client Cybersecurity/SLA Disputes, Wage Attrition |

*Notice Cross-Sectional Divergence:* A single macro event such as **"INR depreciates sharply against USD amid global risk-off flows"** computes positive fundamental impulses for export earners `INFY` and `SUNPHARMA`, while computing negative input-cost/funding impulses for `TATAMOTORS` and `ICICIBANK`!

### 7.3 Parameter-First Generation & Multi-Stage Chain Pipeline

1. **Stage 1 — Structured Parameter Generation:** Deterministic seeded generator picks archetype (`BREAKING`, `OFFICIAL`, `RUMOUR`, `FOLLOW_UP`, `CONFLICTING`, `REVERSAL`, or 3–5 stage `CHAIN_STAGE`), target company/macro factor vector, severity $\sigma_e$, credibility $\kappa_e$, surprise $\xi_e$, and duration $D_e$.
2. **Stage 2 — Exact Impact Vector Calculation:** Computes `event_impact_mappings` for all 5 stocks first.
3. **Stage 3 — Guaranteed-Consistent Content Rendering:** Renders institutional-wire-style headlines and full articles strictly parameterized by the signed numbers from Stage 1–2 (optional LLM phrasing adapter supported behind an interface, validated by polarity checks, with zero external dependency required). Every item carries `simulation_label = "MTT TOURNAMENT SIMULATION — FICTIONAL NEWS"`.
4. **Stage 4 — Admin Review, Scheduling & Release:** Administrators generate libraries (e.g. 60–100 candidate events per game), preview exact 5-stock reference price deltas, edit text/parameters, approve/reject, release immediately, or schedule at exact game offsets (e.g. `T+03:00`, `T+07:30`, `T+12:00` for multi-stage M&A chains).

---

## 8. API Endpoint Specification

Base prefix: `/api/v1`. All mutating financial endpoints require `Authorization: Bearer <jwt>` and `Idempotency-Key: <uuid>`.

### 8.1 Authentication & Session
- `POST /api/v1/auth/register` — Register player/participant account (or tournament invite token).
- `POST /api/v1/auth/login` — Authenticate user, issue JWT + refresh session.
- `GET  /api/v1/auth/me` — Current user identity, role, and active game seat.

### 8.2 Player Tournament, Lobby & Market Endpoints
- `GET  /api/v1/games` — List joinable / active tournament games.
- `POST /api/v1/games/{game_id}/join` — Join lobby (enforces single-account-per-game rule).
- `GET  /api/v1/games/{game_id}/lobby` — Lobby state, server clock, countdown, rules, initial allocation preview.
- `GET  /api/v1/games/{game_id}/state` — Full resync snapshot (clock, phase, 5-stock quotes, player portfolio, open orders, recent news, WS `last_seq`).
- `GET  /api/v1/games/{game_id}/stocks` — 5-stock watchlist (Ref Price, LTP, Bid, Ask, MTM, Vol, Volatility, Exposure summary).
- `GET  /api/v1/games/{game_id}/stocks/{symbol}` — Detailed stock view: company profile, L2 order book depth, recent trades, company-specific news, player's long/short position.
- `GET  /api/v1/games/{game_id}/stocks/{symbol}/candles?interval=5s|1m` — OHLCV + Reference Price + MTM history.
- `GET  /api/v1/games/{game_id}/news` — Released simulated news feed with impact tags and chain links.

### 8.3 Order, Shorting, Portfolio & Leaderboard Endpoints
- `POST   /api/v1/games/{game_id}/orders` — Place order (`BUY_LONG`, `SELL_LONG`, `SHORT_SELL`, `BUY_TO_COVER`; `MARKET` or `LIMIT`).
- `PUT    /api/v1/games/{game_id}/orders/{order_id}` — Atomic cancel-and-replace (`limit_price`, `quantity`).
- `DELETE /api/v1/games/{game_id}/orders/{order_id}` — Cancel open/partially-filled order.
- `GET    /api/v1/games/{game_id}/orders?status=...` — Player's open & historical orders.
- `GET    /api/v1/games/{game_id}/portfolio` — Cash buckets, long holdings, short positions, margin health, borrowing pool availability, live server-computed Net Worth & P&L.
- `GET    /api/v1/games/{game_id}/trades` — Player's executed trade & settlement history (with privacy-safe counterparty tournament codes).
- `GET    /api/v1/games/{game_id}/ledgers?type=cash|share` — Auditable player ledger entries.
- `GET    /api/v1/games/{game_id}/leaderboard` — Server-computed live or immutable final rankings.

### 8.4 Administrator Control Room Endpoints (` ADMIN ` role required)
- **Game Lifecycle & Config:**
  - `POST  /api/v1/admin/games` — Create game with configurable allocations, margins, borrowing pool, and pricing formula parameters.
  - `PATCH /api/v1/admin/games/{game_id}/config` — Update pre-game stock/margin/borrowing parameters.
  - `POST  /api/v1/admin/games/{game_id}/participants/import` — Bulk register/import participants & run atomic idempotent initial allocation (`₹5L cash + 100×5 stocks`).
  - `POST  /api/v1/admin/games/{game_id}/lifecycle/{action}` — `open-lobby | start | pause | resume | start-settlement | finalize`.
- **News Studio:**
  - `POST  /api/v1/admin/games/{game_id}/news/generate` — Deterministically generate single event, multi-stage chain, or full batch library (e.g. 50 events).
  - `GET   /api/v1/admin/games/{game_id}/news` — Full news library (`GENERATED`, `APPROVED`, `SCHEDULED`, `RELEASED`, `REJECTED`) with exact 5-stock impact preview.
  - `PATCH /api/v1/admin/games/{game_id}/news/{event_id}` — Edit headline, body, or impact parameters & recalculate mappings.
  - `POST  /api/v1/admin/games/{game_id}/news/{event_id}/approve` — Approve or reject event.
  - `POST  /api/v1/admin/games/{game_id}/news/{event_id}/release` — Release immediately or schedule for `game_second`.
- **Exchange Surveillance & Emergency Controls:**
  - `GET  /api/v1/admin/games/{game_id}/surveillance` — Full exchange monitor (all prices, L2 depth, borrow pool utilization, open shorts, margin calls, volatility, rankings).
  - `POST /api/v1/admin/games/{game_id}/emergency/stocks/{symbol}/toggle` — Halt/resume trading in a specific stock (audited).
  - `POST /api/v1/admin/games/{game_id}/emergency/cancel-orders` — Cancel open orders globally or for a halted stock (audited).
  - `POST /api/v1/admin/games/{game_id}/emergency/news-halt` — Halt/resume scheduled & manual news releases (audited).
  - `POST /api/v1/admin/games/{game_id}/emergency/settle` — Initiate controlled emergency settlement (audited).
  - `GET  /api/v1/admin/games/{game_id}/audit-logs` — Query immutable audit log trail.

---

## 9. WebSocket Event Specification

### 9.1 Connection, Authentication & State Resynchronization
- **Endpoint:** `WSS /ws/v1/games/{game_id}?token=<jwt>&last_seq=<n>`
- **Envelope Schema:**
  ```json
  {
    "seq": 10482,
    "channel": "public:tickers",
    "event": "MARKET_TICK",
    "game_id": "uuid",
    "server_ts": "2026-11-12T20:15:04.120Z",
    "game_elapsed_ms": 482100,
    "phase": "MAIN_TRADING",
    "payload": {}
  }
  ```
- **Gap Detection & Recovery:** Every broadcast on a game stream carries a monotonic `seq`. If the client detects a gap (`incoming.seq > local_seq + 1`) or reconnects after network drop, it calls `GET /api/v1/games/{game_id}/state` or sends `{"action": "RESYNC", "last_seq": local_seq}` to replay missed events / hydrate clean state.

### 9.2 Server-to-Client Events

| Channel | Event Name | Cadence | Payload Summary |
|---|---|---|---|
| `public:clock` | `CLOCK_SYNC` | Every `1000ms` + immediate on phase change | `phase`, `phase_remaining_ms`, `server_ts`, `is_paused`, `news_halted` |
| `public:clock` | `PHASE_CHANGED` | Immediate | `old_phase`, `new_phase`, `settlement_ends_at`, `rules_active` |
| `public:tickers` | `MARKET_TICK` | Coalesced `150ms` (only dirty stocks) | Per changed stock: `ref_price`, `ltp`, `best_bid`, `best_ask`, `mtm_price`, `volume`, `vwap`, `volatility_pct`, `borrow_available` |
| `public:book:{symbol}` | `ORDERBOOK_SNAPSHOT` | Coalesced `150ms` | Top 15 aggregated `bids` `[[price, qty, count]]` & `asks`, `spread` |
| `public:trades:{symbol}` | `TRADE_PRINT` | Immediate / batched `100ms` | `trade_seq`, `symbol`, `price`, `quantity`, `aggressor_side`, `executed_at` |
| `public:news` | `NEWS_RELEASED` | Immediate simultaneous broadcast | `event_id`, `chain_id`, `category`, `news_type`, `headline`, `body`, `affected_symbols`, `severity`, `simulation_label`, `released_at` |
| `public:leaderboard` | `LEADERBOARD_UPDATE` | Coalesced `2000ms` (immediate on `FINAL`) | Top rankings + participant's own server-calculated rank/net worth |
| `private:user:{id}` | `ORDER_UPDATED` | Immediate | Full order state (`OPEN`, `PARTIALLY_FILLED`, `FILLED`, `CANCELLED`, `REJECTED`) |
| `private:user:{id}` | `EXECUTION_REPORT` | Immediate | Fill details, updated cash buckets, long/short holdings, realized P&L |
| `private:user:{id}` | `MARGIN_ALERT` | Immediate | `WARNING` / `MARGIN_CALL` / `FORCED_LIQUIDATION` with position ratios & deadline |
| `private:user:{id}` | `SETTLEMENT_REPORT` | Immediate at Phase B end | Auto-liquidated short breakdown, final settlement prices, final net worth & rank |
| `admin:surveillance` | `ADMIN_METRIC_TICK` | Coalesced `500ms` | Exchange-wide open interest, short pool utilization, active margin calls, audit feed |

---

## 10. Development Milestones and Testing Strategy

### 10.1 Phased Implementation Plan (Section 16)

- **Phase 1 — Project Foundation:** Provision Python 3.12 + FastAPI + SQLAlchemy 2.0 + Alembic + PostgreSQL + Redis adapter + Next.js + TypeScript + Tailwind + Zustand; Docker & Docker Compose configs; JWT Auth + RBAC + single-seat guard; baseline migrations & health tests.
- **Phase 2 — Exchange Core:** Stock universe & ₹10,00,000 atomic idempotent allocation; Cash & Share double-entry ledgers; Continuous Double Auction matching engine (price-time priority, reservations, partial fills, cancel/replace, expiry, STP); Central Borrowing Pool, Short Selling, Buy-to-Cover, and Margin engine + unit/invariant test suite.
- **Phase 3 — Market Simulation:** Deterministic Fundamental Reference Price engine (log-returns, chain deltas, overlap dampening, transient/permanent decay); Liquidity-Weighted MTM & Settlement valuation; 5s/1m OHLCV candles, volatility, and conflated Redis/WS broadcaster + market unit tests.
- **Phase 4 — News Engine:** 5-company structured factor profiles; 25+ extensible categories; 7 news archetypes & multi-stage event chains; Admin generation, preview, edit, approval, scheduling, and simultaneous broadcast + news simulation tests.
- **Phase 5 — Frontend Interfaces:** High-density dark/orange competitive financial terminal: Game Lobby, Main Trading Terminal (watchlist, TradingView Lightweight Charts with Ref overlay & news pins, order ticket, L2 book, tape, live news, cash/holdings/shorts, timer, leaderboard preview), Stock Detail, Portfolio & Ledger view, Trade History, Leaderboard, and full Administrator Control Room.
- **Phase 6 — Lifecycle & Settlement:** Server-authoritative 45m $\to$ 5m automatic phase FSM; close-only order enforcement in Phase B; automatic administrative short liquidation at $T=50:00$ including unfunded liability accounting; deterministic tie-broken final leaderboard locking.
- **Phase 7 — Scale, Security & Tournament Validation:** 150, 300, and 1,000 concurrent simulated player load & invariant tests; anti-cheating & RBAC penetration tests; production Docker verification & documentation completion.

### 10.2 Global Accounting Invariants (Asserted After Every Test & Simulation Run)

1. **Zero-Sum Peer-to-Peer Cash Conservation:** Across all participants in a game (when fees $= 0$),
   $$\sum_{p=1}^{N} \left(C_{\text{avail},p} + C_{\text{ord},p} + C_{\text{margin},p} + C_{\text{proc},p}\right) + C_{\text{admin\_settlement\_pool}} = N \times ₹5,00,000.$$
2. **Physical + Borrowed Share Conservation:** For every stock $i$,
   $$\sum_{p=1}^{N} \left(\text{LongAvail}_{p,i} + \text{LongRes}_{p,i}\right) - \sum_{p=1}^{N} \text{ShortBorrowed}_{p,i} = N \times 100 - \text{AdminSettledShortShares}_i,$$
   and in the central borrowing pool:
   $$\text{PoolAvail}_i + \text{PoolRes}_i + \text{PoolBorrowed}_i = \text{PoolTotal}_i, \quad \text{with } \text{PoolBorrowed}_i = \sum_{p=1}^{N} \text{ShortBorrowed}_{p,i}.$$
3. **Ledger-to-Portfolio Exact Reconciliation:** Every participant's materialized cash buckets and stock balances equal the exact sum of their immutable `cash_ledger_entries` and `share_ledger_entries` rows to `0.0000` paise and `0` shares.
4. **Reservation Integrity:** Every participant's `order_reserved_cash`, `reserved_shares`, and pool `reserved_pool_shares` equal the exact sum of active reservations on `OPEN` and `PARTIALLY_FILLED` orders.

---

## 11. Unresolved Decisions & Ambiguities Requiring Confirmation

Per Section 17 (Rules 5–7) and Section 18 (*"Identify any unresolved decisions that would materially change the architecture or financial correctness. Do not silently fill gaps with assumptions."*), the following 6 items are surfaced for explicit confirmation (each designed to remain admin-configurable):

1. **Simultaneous Long & Short in the Same Stock ("Shorting Against the Box"):**
   - *Question:* If a player holds unreserved long shares in `RELIANCE`, can they open a `SHORT_SELL` in `RELIANCE` simultaneously, or must long holdings be `0` before shorting (requiring `SELL_LONG` first)?
   - *Recommended Configurable Default:* `allow_simultaneous_long_short = false` (must sell existing long shares before opening a short in that same stock; prevents artificial capital lockup confusion while remaining toggleable per game).
2. **Order Price Modes for Shorting & Market Order Unfilled Remainder Policy:**
   - *Question:* Should `SHORT_SELL` and `BUY_TO_COVER` support **both** `MARKET` and `LIMIT` orders, and should unfilled portions of `MARKET` orders be **Immediate-or-Cancel (IOC)** with a configurable slippage collar (e.g. `±10%` from best opposite quote / ref price for cash reservation)?
   - *Recommended Configurable Default:* Support both `MARKET` and `LIMIT` for `SHORT_SELL` and `BUY_TO_COVER`; treat all `MARKET` orders as `IOC` (unfilled remainder cancelled immediately, unused reserved cash/shares released immediately) with configurable `market_order_collar_pct = 10%`.
3. **Resting Open Orders at the 45-Minute Phase A $\to$ Phase B Transition:**
   - *Question:* At minute 45:00 when entering the 5-minute Short Settlement phase (where new speculative `BUY_LONG` and `SHORT_SELL` positions are prohibited), what happens to already-resting `BUY_LONG` and `SHORT_SELL` limit orders sitting on the book?
   - *Recommended Configurable Default:* Automatically cancel all resting `BUY_LONG` and `SHORT_SELL` orders at $T=45:00$ (releasing their reserved cash and borrowing pool inventory immediately), while keeping resting close-only orders (`SELL_LONG` and `BUY_TO_COVER`) active on the book.
4. **Mid-Game Forced Margin Liquidation Execution Path:**
   - *Question:* Because Section 5 forbids an artificial market maker while Section 6 requires forced liquidation when risk limits are breached, how should forced liquidation execute if the peer-to-peer ask book is temporarily empty or thin?
   - *Recommended Configurable Default:* Issue a `MARGIN_CALL` with configurable grace window (`60s`); if breached beyond grace or critical stop-out ratio (`12.5%`), cancel the player's open margin-consuming orders and submit priority `BUY_TO_COVER` order(s) into the P2P order book; if zero opposite liquidity exists on the book after sweep, keep the forced cover working at the collar / execute audited administrative default close-out only if configured.
5. **Default Risk & Pool Parameters (Admin-Configurable Pre-Game):**
   - *Recommended Defaults:* Borrowing pool per stock = `50 × registered_players` shares (or fixed `15,000` shares default, admin-editable); Initial Margin = `50%`; Maintenance Margin = `25%`; Short Position Limit per player per stock = `500` shares; Tick Size = `₹0.05`; Transaction Fee = `0 bps`.
6. **Official Final Settlement Price Parameters & Counterparty Privacy:**
   - *Recommended Defaults:* Use the Liquidity-Weighted Hybrid Settlement Price $P_i^{\text{settle}} = \lambda_i \cdot \text{VWAP}_i(300\text{s}) + (1 - \lambda_i) \cdot P_i^{\text{ref}}(T)$ with pivot volume $V_0 = 500$ shares and $\pm 15\%$ manipulation collar around $P_i^{\text{ref}}(T)$; display anonymized `tournament_code` (e.g., `MTT-0142`) as counterparty ID to players in Trade History while showing full participant identity to Administrators.
