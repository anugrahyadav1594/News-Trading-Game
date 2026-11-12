# NEWS TRADING — MTT

**Mumbai Trading Tournament (Round 1) — Real-Time Multiplayer Simulated Stock Exchange**  
*Organized by Quantrelic Analytics*

> **MANDATORY TOURNAMENT SIMULATION DISCLAIMER:**  
> `NEWS TRADING — MTT` is a standalone, fictional tournament simulation engineered exclusively for educational and competitive evaluation in the Mumbai Trading Tournament. All equity prices (rebased at `₹1,000.00`), order books, portfolios, and generated breaking news items are **100% simulated**—they never reflect live NSE/BSE prices, genuine corporate disclosures, or investment advice.

---

## 1. Platform Overview

`NEWS TRADING — MTT` is an institutional-grade, peer-to-peer Continuous Double Auction (CDA) exchange and news-driven market simulation built from scratch as an independent full-stack system:

- **Three Distinct Planes:**
  1. **Player Trading Terminal (`/terminal`):** Desktop-optimized dark futuristic financial terminal with MTT orange accents (`#FF6B00`), featuring Game Lobby, Live 3-Column Trading Floor, Deep Stock Profile & Factor Sensitivity Matrix, 4-Bucket Zero-Double-Counting Portfolio Auditor, Order & Execution History, and Live/Final Championship Leaderboard.
  2. **Tournament Director Control Room (`/admin`):** Game provisioning & pre-game parameter configuration, parameter-first 25+ category news & multi-stage narrative chain generator, editorial approval/scheduling/immediate breaking release & official retraction console, live exchange surveillance & accounting invariant verifier, emergency circuit breakers, and SHA-256 hash-chained immutable audit viewer.
  3. **Authoritative Exchange & Simulation Engine (`backend/`):** Modular Python FastAPI + PostgreSQL 16 ACID engine enforcing per-stock advisory locks, price-time priority matching at resting order prices, central stock-borrowing pools, margin calls & P2P forced liquidations, and server-authoritative phase transitions.

---

## 2. Simulated Market Universe & Starting Allocation

Every game provisions **5 simulated Indian large-cap equities**, each opening at **`₹1,000.00`** with integer-only share trading (`₹0.05` tick size):

| Symbol | Company | Sector | Initial Player Shares | Opening Value |
|---|---|---|---:|---:|
| `RELIANCE` | Reliance Industries | Energy, Refining, Telecom & Retail | `100` | `₹1,00,000.00` |
| `ICICIBANK` | ICICI Bank | Banking & Financial Services | `100` | `₹1,00,000.00` |
| `TATAMOTORS` | Tata Motors | Automobiles, Commercial Vehicles & EVs | `100` | `₹1,00,000.00` |
| `SUNPHARMA` | Sun Pharmaceutical Industries | Pharmaceuticals & Specialty Healthcare | `100` | `₹1,00,000.00` |
| `INFY` | Infosys | IT Services & Enterprise Digital | `100` | `₹1,00,000.00` |

- **Initial Stock Value:** `500 shares × ₹1,000.00 = ₹5,00,000.00`
- **Initial Cash Balance:** `₹5,00,000.00`
- **Starting Net Worth:** **`₹10,00,000.00`** (allocated atomically and idempotently in PostgreSQL with `InitialAllocation`, `CashLedgerEntry`, and `ShareLedgerEntry` records).

---

## 3. Core Financial & Mathematical Mechanics

Full architectural specifications, ER diagrams (28 normalized tables), and mathematical proofs are documented in [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md).

1. **Continuous Double Auction (Pure Peer-to-Peer):**
   - Strictly matches participant buy and sell orders via **Price-Time Priority** (`best price`, then monotonic `sequence_num`) executing at the **resting order's limit price**. Zero artificial market makers.
   - Supports **6 explicit intents/order combinations:** `BUY_LONG`, `SELL_LONG`, `SHORT_SELL`, and `BUY_TO_COVER` across both `LIMIT` (`GTC`, `IOC`, `GTD`) and `MARKET` (`IOC` bounded by configurable `±10%` reference collar).
2. **4-Bucket Zero-Double-Counting Short Accounting:**
   - Segregates `available_cash`, `order_reserved_cash`, `short_proceeds_locked`, and `short_margin_locked` (`50%` initial margin, `25%` maintenance margin, `12.5%` critical threshold, `60s` margin-call grace).
   - Short sale proceeds are locked in `short_proceeds_locked` (never added to spendable `available_cash` until covered), guaranteeing exact net-worth conservation on entry and exit.
3. **Server-Authoritative Two-Phase Clock & Forced Short Settlement:**
   - **Phase A — Main Trading (`45:00` default):** Full trading, short selling, and manual/scheduled breaking news.
   - **Phase B — Short Position Settlement (`05:00` default):** Triggered automatically at `45:00`. Resting `BUY_LONG` and `SHORT_SELL` orders are cancelled and reservations released; only close-only `BUY_TO_COVER` and `SELL_LONG` orders are permitted; new news releases are halted.
   - **End-of-Game Administrative Liquidation (`00:00`):** Any remaining open short positions are automatically settled at the Official Final Settlement Price, returning borrowed shares to the central pool, deducting obligations from locked collateral + cash, and recording any unpaid shortfall in `unfunded_settlement_debt` (never silently waiving negative net worth).
4. **Official Mark-to-Market & Final Ranking Formula:**
   - Liquidity-weighted Official MTM / Settlement Price blends 300s trailing P2P VWAP with the deterministic multi-factor Fundamental Reference Price $P^{\text{ref}}_i(t)$ within a $\pm 15\%$ manipulation collar:
     $$P^{\text{mtm}}_i(t) = \operatorname{round\_tick}\!\left(\lambda_i \widetilde{P}^{\text{mkt}}_i(t) + (1 - \lambda_i) P^{\text{ref}}_i(t)\right), \quad \lambda_i = \frac{V_i}{V_i + 500}$$
   - **Final Net Worth:**
     $$\text{Net Worth} = C_{\text{avail}} + C_{\text{ord\_res}} + C_{\text{short\_proc}} + C_{\text{short\_margin}} + \sum_{i=1}^5 Q^{\text{long}}_i P^{\text{settle}}_i - \sum_{i=1}^5 Q^{\text{short}}_i P^{\text{settle}}_i - D_{\text{unfunded}}$$
   - **Tie-Breakers:** Higher `Realized Trading P&L`, then earlier timestamp of achieving final net worth.

---

## 4. Seeded Demo Accounts (Local & Preview Convenience)

When `AUTO_SEED_DEMO=true`, startup idempotently provisions active game **`MTT-ROUND1`** (live `MAIN_TRADING` with resting P2P books, initial fills, 34 structured news events, and 2 released headlines) and **`MTT-LOBBY`** (`LOBBY` status):

| Role | Email | Password | Notes |
|---|---|---|---|
| **Tournament Director (`ADMIN`)** | `admin@quantrelic-mtt.in` | `MttAdmin@2026!` | Full access to `/admin` Control Room, News Desk, Surveillance & Audit Logs |
| **Competitor #1 (`PLAYER`)** | `aarav@mtt.in` | `MttPlayer@2026!` | Aarav Mehta • IIT Bombay |
| **Competitor #2 (`PLAYER`)** | `diya@mtt.in` | `MttPlayer@2026!` | Diya Kulkarni • IIM Ahmedabad |
| **Competitor #3 (`PLAYER`)** | `rohan@mtt.in` | `MttPlayer@2026!` | Rohan Deshmukh • VJTI Mumbai |
| **Competitor #4 (`PLAYER`)** | `ananya@mtt.in` | `MttPlayer@2026!` | Ananya Iyer • ISI Kolkata |
| **Competitor #5 (`PLAYER`)** | `kabir@mtt.in` | `MttPlayer@2026!` | Kabir Shah • JBIMS Mumbai |
| **Competitor #6 (`PLAYER`)** | `meera@mtt.in` | `MttPlayer@2026!` | Meera Nair • BITS Pilani |

---

## 5. Running & Deploying

### Option A: Docker Compose (Recommended for Multi-Container Deployment)
```bash
cp .env.example .env
# Development stack (Postgres 16, Redis 7, Backend API/WS, Frontend)
docker compose up --build

# Production stack (adds Nginx TLS/WS reverse proxy & automated PostgreSQL backup daemon)
docker compose -f docker-compose.yml -f docker-compose.prod.yml up -d --build
```

### Option B: Direct Local Execution
```bash
# 1. Backend (runs Alembic migrations automatically on startup)
cd backend
.venv/bin/uvicorn app.main:app --host 0.0.0.0 --port 8000

# 2. Frontend (custom server.mjs proxies /api/*, /health/*, and /ws/* toBACKEND_INTERNAL_URL)
cd frontend
npm install
npm run build
npm run start
```

---

## 6. Running Automated Tests

```bash
# Backend: 12 async integration, security, PostgreSQL immutability trigger,
# and 150 / 300 / 1,000-player concurrent tournament scale simulations
cd backend && .venv/bin/pytest -v

# Frontend: TypeScript strict check, Vitest unit suite, and Next.js production build
cd frontend && npm run typecheck && npm run test && npm run build
```
