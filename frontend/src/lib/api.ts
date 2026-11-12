import type {
  AdminNewsEvent,
  AuditEntry,
  AuthResponse,
  CandleBar,
  ClockInfo,
  GameStatus,
  GameSummary,
  LeaderboardEntry,
  OrderBookDepth,
  OrderIntent,
  OrderPriceType,
  OrderRecord,
  PortfolioValuation,
  ReleasedNewsItem,
  StockMarketItem,
  SurveillanceDashboard,
  TradeRecord,
  UserSummary,
} from "@/types/exchange";

export class ExchangeApiError extends Error {
  code: string;
  status: number;
  details?: Record<string, unknown>;

  constructor(message: string, code = "API_ERROR", status = 400, details?: Record<string, unknown>) {
    super(message);
    this.name = "ExchangeApiError";
    this.code = code;
    this.status = status;
    this.details = details;
  }
}

function getAuthToken(): string | null {
  if (typeof window === "undefined") return null;
  return window.localStorage.getItem("mtt_access_token");
}

async function request<T>(path: string, init: RequestInit = {}): Promise<T> {
  const token = getAuthToken();
  const headers: Record<string, string> = {
    "Content-Type": "application/json",
    ...(init.headers as Record<string, string> | undefined),
  };
  if (token) {
    headers.Authorization = `Bearer ${token}`;
  }

  // Strictly relative URLs so Arena browser preview (`https://{port}-{sandboxId}.e2b.app`) proxies cleanly
  const res = await fetch(path, {
    ...init,
    headers,
    cache: "no-store",
  });

  if (!res.ok) {
    let payload: Record<string, unknown> | null = null;
    try {
      payload = await res.json();
    } catch {
      payload = null;
    }
    const errObj = (payload?.error as Record<string, unknown> | undefined) || undefined;
    const msg =
      (errObj?.message as string | undefined) ||
      (typeof payload?.detail === "string" ? payload.detail : undefined) ||
      `Exchange request failed (${res.status})`;
    const code = (errObj?.code as string | undefined) || `HTTP_${res.status}`;
    throw new ExchangeApiError(msg, code, res.status, errObj?.details as Record<string, unknown> | undefined);
  }

  return (await res.json()) as T;
}

export function normalizeClock(raw: Record<string, unknown>, tradingSec = 2700, settleSec = 300): ClockInfo {
  const status = (raw?.status as GameStatus) || "LOBBY";
  const remMs = Number(raw?.phase_remaining_ms ?? 0);
  return {
    game_id: String(raw?.game_id ?? ""),
    status,
    server_time: String(raw?.server_ts ?? new Date().toISOString()),
    phase_started_at: null,
    phase_ends_at: null,
    remaining_phase_sec: Math.max(0, Math.ceil(remMs / 1000)),
    trading_duration_sec: tradingSec,
    settlement_duration_sec: settleSec,
    is_trading_open: status === "MAIN_TRADING" || status === "SHORT_SETTLEMENT",
    is_close_only_phase: status === "SHORT_SETTLEMENT",
    is_completed: status === "COMPLETED",
  };
}

export function normalizeGame(g: Record<string, unknown>, tournamentCode?: string | null): GameSummary {
  const tSec = Number(g.trading_duration_sec ?? 2700);
  const sSec = Number(g.settlement_duration_sec ?? 300);
  return {
    game_id: String(g.id ?? g.game_id ?? ""),
    code: String(g.code ?? ""),
    name: String(g.name ?? ""),
    status: (g.status as GameStatus) || "LOBBY",
    starting_cash: String(g.initial_cash ?? "500000.0000"),
    starting_shares_per_stock: Number(g.default_shares_per_stock ?? 100),
    trading_duration_sec: tSec,
    settlement_duration_sec: sSec,
    tick_size: "0.05",
    initial_margin_ratio: String(g.initial_margin_ratio ?? "0.5000"),
    maintenance_margin_ratio: String(g.maintenance_margin_ratio ?? "0.2500"),
    critical_margin_ratio: "0.1250",
    margin_call_grace_sec: 60,
    default_short_pool_shares: Number(g.default_short_pool_shares ?? 15000),
    short_position_limit_per_stock: Number(g.short_position_limit_per_stock ?? 500),
    allow_simultaneous_long_short: Boolean(g.allow_simultaneous_long_short ?? false),
    market_order_collar_pct: String(g.market_order_collar_pct ?? "0.1000"),
    participant_count: Number(g.participant_count ?? 0),
    joined: Boolean(g.joined ?? false),
    tournament_code: tournamentCode ?? null,
    clock: normalizeClock((g.clock as Record<string, unknown>) || { status: g.status }, tSec, sSec),
  };
}

export function normalizeStock(
  st: Record<string, unknown>,
  exposureOverride?: Record<string, number>
): StockMarketItem {
  const pool = (st.borrowing_pool as Record<string, unknown> | undefined) || {};
  const hasTrades = Boolean(st.has_trades ?? st.last_traded_price != null);
  return {
    stock_id: String(st.stock_id ?? ""),
    symbol: String(st.symbol ?? ""),
    company_name: String(st.company_name ?? ""),
    sector: String(st.sector ?? ""),
    opening_price: String(st.opening_price ?? "1000.0000"),
    tick_size: String(st.tick_size ?? "0.0500"),
    shortable: Boolean(st.trading_enabled ?? true),
    short_position_limit: Number(st.short_limit_per_player ?? 500),
    exposure_profile: exposureOverride,
    last_traded_price: hasTrades ? String(st.last_traded_price) : null,
    fundamental_ref_price: String(st.fundamental_ref_price ?? "1000.0000"),
    official_mtm_price: String(st.official_mtm_price ?? "1000.0000"),
    best_bid: st.best_bid != null ? String(st.best_bid) : null,
    best_ask: st.best_ask != null ? String(st.best_ask) : null,
    change_pct_from_open: String(st.change_pct ?? "0.00"),
    borrow_pool: {
      total_pool_shares: Number(pool.total_pool_shares ?? 15000),
      borrowed_shares: Number(pool.borrowed_shares ?? 0),
      reserved_order_shares: Number(pool.reserved_pool_shares ?? 0),
      remaining_shares: Number(pool.available_pool_shares ?? 15000),
    },
  };
}

function severityLabel(sevVal: unknown): string {
  const n = Number(sevVal);
  if (!Number.isFinite(n)) return String(sevVal || "MEDIUM").toUpperCase();
  if (n >= 0.85) return "CRITICAL";
  if (n >= 0.65) return "HIGH";
  if (n >= 0.4) return "MEDIUM";
  return "LOW";
}

export function normalizeNewsItem(ev: Record<string, unknown>): ReleasedNewsItem {
  const syms = new Set<string>();
  if (typeof ev.primary_symbol === "string" && ev.primary_symbol) syms.add(ev.primary_symbol);
  if (Array.isArray(ev.secondary_symbols)) {
    for (const s of ev.secondary_symbols) if (typeof s === "string" && s) syms.add(s);
  }
  if (syms.size === 0) {
    for (const s of ["RELIANCE", "ICICIBANK", "TATAMOTORS", "SUNPHARMA", "INFY"]) syms.add(s);
  }
  return {
    event_id: String(ev.id ?? ev.event_id ?? ""),
    headline: String(ev.headline ?? ""),
    body: String(ev.body ?? ""),
    category_slug: String(ev.category ?? ""),
    archetype: String(ev.news_type ?? "BREAKING"),
    severity: severityLabel(ev.severity),
    chain_id: ev.chain_id ? String(ev.chain_id) : null,
    chain_stage: ev.chain_stage != null ? Number(ev.chain_stage) : null,
    chain_total_stages: ev.chain_total_stages != null ? Number(ev.chain_total_stages) : null,
    certainty_pct: String(ev.credibility ?? "0.90"),
    affected_symbols: Array.from(syms),
    released_at: ev.released_at ? String(ev.released_at) : null,
    status: String(ev.news_type === "REVERSAL" ? "REVERSED" : "RELEASED"),
    simulation_disclaimer: String(
      ev.simulation_label ??
        "SIMULATED TOURNAMENT WIRE — Fictional scenario for Mumbai Trading Tournament (Quantrelic Analytics)."
    ),
  };
}

function normalizeOrder(o: Record<string, unknown>): OrderRecord {
  return {
    order_id: String(o.id ?? o.order_id ?? ""),
    client_order_id: o.client_order_id ? String(o.client_order_id) : null,
    stock_id: String(o.stock_id ?? ""),
    symbol: String(o.symbol ?? ""),
    intent: (o.intent as OrderIntent) || "BUY_LONG",
    side: (o.side as "BUY" | "SELL") || "BUY",
    price_type: (o.price_type as OrderPriceType) || "LIMIT",
    time_in_force: String(o.time_in_force ?? "GTC"),
    limit_price: o.limit_price != null ? String(o.limit_price) : null,
    collar_price: o.collar_price != null ? String(o.collar_price) : null,
    quantity: Number(o.quantity ?? 0),
    filled_quantity: Number(o.filled_quantity ?? 0),
    remaining_quantity: Number(o.remaining_quantity ?? 0),
    avg_fill_price: o.avg_fill_price != null ? String(o.avg_fill_price) : null,
    status: String(o.status ?? "OPEN"),
    reject_reason: null,
    cancel_reason: o.cancel_reason ? String(o.cancel_reason) : null,
    is_forced_liquidation: Boolean(o.is_forced_liquidation ?? false),
    submitted_at: String(o.created_at ?? new Date().toISOString()),
    updated_at: String(o.updated_at ?? new Date().toISOString()),
  };
}

export const exchangeApi = {
  // Auth
  login: async (email: string, password: string): Promise<AuthResponse> => {
    const raw = await request<{
      access_token: string;
      token_type: string;
      user: Record<string, unknown>;
    }>("/api/v1/auth/login", {
      method: "POST",
      body: JSON.stringify({ identifier: email, password }),
    });
    return {
      access_token: raw.access_token,
      token_type: raw.token_type,
      user: {
        user_id: String(raw.user.user_id),
        email: String(raw.user.email),
        username: String(raw.user.username),
        display_name: String(raw.user.display_name || raw.user.username),
        role: (raw.user.role as "PLAYER" | "ADMIN") || "PLAYER",
        institution: raw.user.institution ? String(raw.user.institution) : null,
      },
    };
  },

  register: async (params: {
    email: string;
    username: string;
    password: string;
    display_name: string;
    institution?: string;
  }): Promise<AuthResponse> => {
    const raw = await request<{
      access_token: string;
      token_type: string;
      user: Record<string, unknown>;
    }>("/api/v1/auth/register", {
      method: "POST",
      body: JSON.stringify(params),
    });
    return {
      access_token: raw.access_token,
      token_type: raw.token_type,
      user: {
        user_id: String(raw.user.user_id),
        email: String(raw.user.email),
        username: String(raw.user.username),
        display_name: String(raw.user.display_name || raw.user.username),
        role: (raw.user.role as "PLAYER" | "ADMIN") || "PLAYER",
        institution: raw.user.institution ? String(raw.user.institution) : null,
      },
    };
  },

  me: async (): Promise<UserSummary> => {
    const u = await request<Record<string, unknown>>("/api/v1/auth/me");
    return {
      user_id: String(u.user_id),
      email: String(u.email),
      username: String(u.username),
      display_name: String(u.display_name || u.username),
      role: (u.role as "PLAYER" | "ADMIN") || "PLAYER",
      institution: u.institution ? String(u.institution) : null,
    };
  },

  // Games & Market
  listGames: async (): Promise<{ games: GameSummary[] }> => {
    const arr = await request<Array<Record<string, unknown>>>("/api/v1/games");
    return { games: arr.map((g) => normalizeGame(g)) };
  },

  getGame: async (gameId: string): Promise<GameSummary> => {
    const lobby = await request<{
      game: Record<string, unknown>;
      seat: { tournament_code?: string | null; joined?: boolean };
    }>(`/api/v1/games/${gameId}/lobby`);
    const gm = normalizeGame(lobby.game, lobby.seat?.tournament_code);
    gm.joined = Boolean(lobby.seat?.joined ?? gm.joined);
    return gm;
  },

  joinGame: async (gameId: string) => {
    const res = await request<Record<string, unknown>>(`/api/v1/games/${gameId}/join`, {
      method: "POST",
    });
    const pf = await exchangeApi.getPortfolio(gameId);
    return {
      game_participant_id: String(res.game_participant_id),
      tournament_code: "SEATED",
      status: "JOINED",
      portfolio: pf,
    };
  },

  getStocks: async (gameId: string) => {
    const lobby = await request<{
      game: Record<string, unknown>;
      stocks: Array<Record<string, unknown>>;
    }>(`/api/v1/games/${gameId}/lobby`);
    const gm = normalizeGame(lobby.game);
    return {
      game_id: gm.game_id,
      clock: gm.clock,
      stocks: lobby.stocks.map((s) => normalizeStock(s)),
    };
  },

  getStockDetailAndBook: async (
    gameId: string,
    symbol: string
  ): Promise<{
    book: OrderBookDepth;
    factorExposures: Record<string, number>;
  }> => {
    const det = await request<{
      quote: Record<string, unknown>;
      profile: { factor_exposures?: Record<string, number> };
      order_book: {
        bids: Array<{ price: string; quantity: number; order_count: number }>;
        asks: Array<{ price: string; quantity: number; order_count: number }>;
        best_bid: string | null;
        best_ask: string | null;
        spread: string | null;
      };
    }>(`/api/v1/games/${gameId}/stocks/${symbol}`);

    return {
      book: {
        stock_id: String(det.quote.stock_id ?? ""),
        symbol,
        bids: det.order_book.bids || [],
        asks: det.order_book.asks || [],
        best_bid: det.order_book.best_bid,
        best_ask: det.order_book.best_ask,
        spread: det.order_book.spread,
      },
      factorExposures: det.profile?.factor_exposures || {},
    };
  },

  getOrderBook: async (gameId: string, symbol: string): Promise<OrderBookDepth> => {
    const { book } = await exchangeApi.getStockDetailAndBook(gameId, symbol);
    return book;
  },

  getCandles: async (gameId: string, symbol: string, intervalSec: 5 | 60 = 5) => {
    const arr = await request<CandleBar[]>(
      `/api/v1/games/${gameId}/stocks/${symbol}/candles?interval_sec=${intervalSec}&limit=240`
    );
    return { symbol, interval_sec: intervalSec, candles: arr };
  },

  getNewsFeed: async (gameId: string) => {
    const arr = await request<Array<Record<string, unknown>>>(`/api/v1/games/${gameId}/news`);
    return {
      simulation_notice: "SIMULATED TOURNAMENT NEWS",
      items: arr.map(normalizeNewsItem),
    };
  },

  getPortfolio: async (gameId: string): Promise<PortfolioValuation> => {
    const raw = await request<Record<string, unknown>>(`/api/v1/games/${gameId}/portfolio`);
    const longs = Array.isArray(raw.long_holdings) ? raw.long_holdings : [];
    const shorts = Array.isArray(raw.short_positions) ? raw.short_positions : [];

    return {
      game_participant_id: String(raw.game_participant_id ?? ""),
      available_cash: String(raw.available_cash ?? "0"),
      order_reserved_cash: String(raw.order_reserved_cash ?? "0"),
      short_proceeds_locked: String(raw.short_proceeds_locked ?? "0"),
      short_margin_locked: String(raw.short_margin_locked ?? "0"),
      unfunded_settlement_debt: String(raw.unfunded_settlement_debt ?? "0"),
      realized_pnl: String(raw.realized_pnl ?? "0"),
      unrealized_long_pnl: String(raw.unrealized_long_pnl ?? "0"),
      unrealized_short_pnl: String(raw.unrealized_short_pnl ?? "0"),
      long_market_value: String(raw.long_market_value ?? "0"),
      short_buyback_liability: String(raw.short_liability ?? "0"),
      net_worth: String(raw.net_worth ?? "1000000"),
      starting_net_worth: String(raw.initial_net_worth ?? "1000000"),
      total_return_pct: String(raw.return_pct ?? "0"),
      long_holdings: longs.map((h: Record<string, unknown>) => ({
        stock_id: String(h.symbol ?? ""),
        symbol: String(h.symbol ?? ""),
        available_quantity: Number(h.available_shares ?? 0),
        reserved_sell_quantity: Number(h.reserved_shares ?? 0),
        total_quantity: Number(h.total_shares ?? 0),
        avg_entry_price: String(h.avg_entry_price ?? "1000"),
        mtm_price: String(h.mark_price ?? "1000"),
        market_value: String(h.market_value ?? "0"),
        unrealized_pnl: String(h.unrealized_pnl ?? "0"),
      })),
      short_positions: shorts.map((sp: Record<string, unknown>) => ({
        stock_id: String(sp.symbol ?? ""),
        symbol: String(sp.symbol ?? ""),
        borrowed_quantity: Number(sp.borrowed_shares ?? 0),
        reserved_cover_quantity: Number(sp.pending_cover_shares ?? 0),
        avg_short_price: String(sp.opening_price ?? "0"),
        mtm_price: String(sp.current_market_price ?? "1000"),
        short_liability: String(sp.current_liability ?? "0"),
        sale_proceeds_locked: String(sp.sale_proceeds ?? "0"),
        margin_collateral_locked: String(sp.margin_collateral ?? "0"),
        required_maintenance_margin: String(sp.required_maintenance_collateral ?? "0"),
        unrealized_pnl: String(sp.unrealized_pnl ?? "0"),
        margin_ratio: sp.margin_ratio != null ? String(sp.margin_ratio) : null,
        margin_status:
          (sp.margin_status as "HEALTHY" | "WARNING" | "MARGIN_CALL" | "LIQUIDATING") || "HEALTHY",
        margin_call_deadline_at: null,
      })),
    };
  },

  getLeaderboard: async (gameId: string) => {
    const res = await request<{
      game_id: string;
      status: string;
      is_final_official: boolean;
      entries: Array<Record<string, unknown>>;
    }>(`/api/v1/games/${gameId}/leaderboard`);

    return {
      game_id: res.game_id,
      status: res.status,
      entries: res.entries.map(
        (e): LeaderboardEntry => ({
          rank: Number(e.rank ?? 1),
          game_participant_id: String(e.game_participant_id ?? ""),
          tournament_code: String(e.tournament_code ?? ""),
          username: String(e.tournament_code ?? ""),
          display_name: String(e.display_name ?? ""),
          institution: null,
          net_worth: String(e.final_net_worth ?? "1000000"),
          return_pct: String(e.return_pct ?? "0"),
          realized_pnl: String(e.realized_pnl ?? "0"),
          available_cash: "0",
          order_reserved_cash: "0",
          long_market_value: "0",
          short_liability: "0",
          unfunded_debt: "0",
          is_final: Boolean(res.is_final_official),
        })
      ),
    };
  },

  // Orders & Executions
  placeOrder: async (
    gameId: string,
    payload: {
      symbol: string;
      intent: OrderIntent;
      price_type: OrderPriceType;
      quantity: number;
      limit_price?: string | null;
      time_in_force?: "GTC" | "IOC" | "GTD";
      expires_in_sec?: number | null;
      client_order_id?: string;
    }
  ) => {
    const raw = await request<Record<string, unknown>>(`/api/v1/games/${gameId}/orders`, {
      method: "POST",
      body: JSON.stringify(payload),
    });
    const ord = normalizeOrder(raw);
    return {
      order: ord,
      fills_count: ord.filled_quantity > 0 ? 1 : 0,
      fills: [],
    };
  },

  listOrders: async (gameId: string, statusFilter?: string) => {
    const arr = await request<Array<Record<string, unknown>>>(
      `/api/v1/games/${gameId}/orders${statusFilter ? `?status=${statusFilter}` : ""}`
    );
    return { orders: arr.map(normalizeOrder) };
  },

  modifyOrder: async (
    gameId: string,
    orderId: string,
    payload: { new_quantity?: number; new_limit_price?: string }
  ) => {
    const raw = await request<Record<string, unknown>>(
      `/api/v1/games/${gameId}/orders/${orderId}`,
      {
        method: "PUT",
        body: JSON.stringify({
          quantity: payload.new_quantity,
          limit_price: payload.new_limit_price,
        }),
      }
    );
    return {
      cancelled_order_id: orderId,
      replacement_order: normalizeOrder(raw),
      fills_count: 0,
    };
  },

  cancelOrder: async (gameId: string, orderId: string) => {
    const raw = await request<Record<string, unknown>>(
      `/api/v1/games/${gameId}/orders/${orderId}`,
      { method: "DELETE" }
    );
    return { order: normalizeOrder(raw) };
  },

  listMyTrades: async (gameId: string) => {
    const arr = await request<Array<Record<string, unknown>>>(`/api/v1/games/${gameId}/trades`);
    return {
      trades: arr.map(
        (t): TradeRecord => ({
          trade_id: String(t.id ?? t.trade_id ?? ""),
          symbol: String(t.symbol ?? ""),
          role: String(t.side) === "BUY" ? "BUYER" : "SELLER",
          price: String(t.price ?? "0"),
          quantity: Number(t.quantity ?? 0),
          notional: String(t.gross_amount ?? "0"),
          counterparty_code: String(t.counterparty_code ?? "MTT-PEER"),
          is_forced_liquidation: String(t.execution_kind ?? "").includes("LIQUIDATION"),
          executed_at: String(t.executed_at ?? new Date().toISOString()),
        })
      ),
    };
  },

  // Admin Control Room Endpoints
  adminCreateGame: async (payload: Record<string, unknown>): Promise<GameSummary> => {
    const g = await request<Record<string, unknown>>("/api/v1/admin/games", {
      method: "POST",
      body: JSON.stringify(payload),
    });
    return normalizeGame(g);
  },

  adminUpdateConfig: async (gameId: string, payload: Record<string, unknown>) => {
    const g = await request<Record<string, unknown>>(`/api/v1/admin/games/${gameId}/config`, {
      method: "PATCH",
      body: JSON.stringify(payload),
    });
    return normalizeGame(g);
  },

  adminLifecycleAction: async (
    gameId: string,
    action: "start" | "pause" | "resume" | "start-settlement" | "finalize",
    reason?: string
  ) => {
    const g = await request<Record<string, unknown>>(
      `/api/v1/admin/games/${gameId}/lifecycle/${action}`,
      {
        method: "POST",
        body: JSON.stringify({ reason: reason || `Tournament director executed ${action}` }),
      }
    );
    return normalizeGame(g);
  },

  adminCancelAllOrders: async (gameId: string, reason: string, symbol?: string) => {
    const res = await request<{ cancelled_count: number }>(
      `/api/v1/admin/games/${gameId}/emergency/cancel-orders`,
      {
        method: "POST",
        body: JSON.stringify({ reason, symbol: symbol || null }),
      }
    );
    return { cancelled_orders: res.cancelled_count };
  },

  adminListCategories: async () => {
    const arr = await request<Array<Record<string, unknown>>>("/api/v1/admin/news/categories");
    return {
      categories: arr.map((c) => ({
        category_id: String(c.code),
        slug: String(c.code),
        name: String(c.display_name),
        description: String(c.domain_group || ""),
        default_polarity_bias: 1,
        is_builtin: Boolean(c.is_builtin),
      })),
    };
  },

  adminCreateCategory: async (payload: {
    slug: string;
    name: string;
    description: string;
    default_polarity_bias: number;
    factor_weights: Record<string, number>;
  }) => {
    const c = await request<Record<string, unknown>>("/api/v1/admin/news/categories", {
      method: "POST",
      body: JSON.stringify({
        code: payload.slug,
        display_name: payload.name,
        domain_group: "Director Custom",
        default_factors: Object.keys(payload.factor_weights),
      }),
    });
    return { category_id: String(c.code), slug: String(c.code), name: String(c.display_name) };
  },

  adminGenerateNewsBatch: async (
    gameId: string,
    payload: { count: number; include_chains: boolean; seed?: number | null; auto_approve: boolean }
  ) => {
    const res = await request<{ generated_count: number }>(
      `/api/v1/admin/games/${gameId}/news/generate`,
      {
        method: "POST",
        body: JSON.stringify(payload),
      }
    );
    return { generated_count: res.generated_count };
  },

  adminCreateManualNews: async (gameId: string, payload: Record<string, unknown>) => {
    const ev = await request<Record<string, unknown>>(
      `/api/v1/admin/games/${gameId}/news/custom`,
      {
        method: "POST",
        body: JSON.stringify(payload),
      }
    );
    return { event_id: String(ev.id), status: String(ev.approval_status) };
  },

  adminListNewsEvents: async (gameId: string): Promise<{ events: AdminNewsEvent[] }> => {
    const arr = await request<Array<Record<string, unknown>>>(`/api/v1/admin/games/${gameId}/news`);
    return {
      events: arr.map((ev) => {
        const imps = Array.isArray(ev.impacts) ? ev.impacts : [];
        return {
          event_id: String(ev.id),
          category_slug: String(ev.category),
          archetype: String(ev.news_type),
          severity: severityLabel(ev.severity),
          headline: String(ev.headline),
          body: String(ev.body),
          status: String(ev.approval_status),
          chain_id: ev.chain_id ? String(ev.chain_id) : null,
          chain_stage: ev.chain_stage != null ? Number(ev.chain_stage) : null,
          chain_total_stages: ev.chain_total_stages != null ? Number(ev.chain_total_stages) : null,
          scheduled_offset_sec: ev.scheduled_game_sec != null ? Number(ev.scheduled_game_sec) : null,
          scheduled_release_at: null,
          released_at: ev.released_at ? String(ev.released_at) : null,
          impacts: imps.map((m: Record<string, unknown>) => {
            const pctDelta = Number(m.estimated_pct_delta ?? 0);
            return {
              symbol: String(m.symbol),
              direction: pctDelta >= 0 ? 1 : -1,
              magnitude_pct: String(Math.abs(pctDelta) / 100),
              half_life_sec: 120,
            };
          }),
        };
      }),
    };
  },

  adminApproveNews: async (gameId: string, eventId: string) => {
    const ev = await request<Record<string, unknown>>(
      `/api/v1/admin/games/${gameId}/news/${eventId}/approve`,
      {
        method: "POST",
        body: JSON.stringify({ approve: true }),
      }
    );
    return { event_id: String(ev.id), status: String(ev.approval_status) };
  },

  adminReleaseOrScheduleNews: async (
    gameId: string,
    eventId: string,
    payload: { mode: "IMMEDIATE" | "SCHEDULED"; scheduled_offset_sec?: number }
  ) => {
    const ev = await request<Record<string, unknown>>(
      `/api/v1/admin/games/${gameId}/news/${eventId}/release`,
      {
        method: "POST",
        body: JSON.stringify({
          mode: payload.mode,
          scheduled_game_sec: payload.scheduled_offset_sec ?? null,
        }),
      }
    );
    return {
      event_id: String(ev.id),
      status: String(ev.approval_status),
      released_at: ev.released_at ? String(ev.released_at) : null,
    };
  },

  adminReverseNews: async (gameId: string, eventId: string, reason: string) => {
    const ev = await request<Record<string, unknown>>(
      `/api/v1/admin/games/${gameId}/news/${eventId}/reverse`,
      {
        method: "POST",
        body: JSON.stringify({
          reversal_ratio: "1.0",
          release_immediately: true,
          body: reason,
        }),
      }
    );
    return { reversed_event_id: String(ev.id), status: String(ev.approval_status) };
  },

  adminSurveillance: async (gameId: string): Promise<SurveillanceDashboard> => {
    const raw = await request<Record<string, unknown>>(`/api/v1/admin/games/${gameId}/surveillance`);
    const gm = normalizeGame(raw.game as Record<string, unknown>);
    const stocksArr = Array.isArray(raw.stocks) ? raw.stocks : [];
    const openOrdersArr = Array.isArray(raw.open_orders) ? raw.open_orders : [];
    const activeShortsArr = Array.isArray(raw.active_short_positions)
      ? raw.active_short_positions
      : [];
    const rankingsArr = Array.isArray(raw.rankings) ? raw.rankings : [];
    const integ = (raw.accounting_integrity as Record<string, unknown>) || {};

    return {
      game_id: gm.game_id,
      status: gm.status,
      clock: gm.clock,
      invariants: {
        passed: Boolean(integ.passed ?? true),
        participant_count: Number(integ.participant_count ?? 0),
        violations: Array.isArray(integ.violations) ? (integ.violations as string[]) : [],
      },
      stocks: stocksArr.map((s: Record<string, unknown>) => {
        const norm = normalizeStock(s);
        const symOrders = openOrdersArr.filter(
          (o: Record<string, unknown>) => o.symbol === norm.symbol
        ).length;
        return {
          symbol: norm.symbol,
          ltp: norm.last_traded_price,
          ref_price: norm.fundamental_ref_price,
          mtm_price: norm.official_mtm_price,
          best_bid: norm.best_bid,
          best_ask: norm.best_ask,
          pool_total: norm.borrow_pool?.total_pool_shares ?? 0,
          pool_borrowed: norm.borrow_pool?.borrowed_shares ?? 0,
          pool_remaining: norm.borrow_pool?.remaining_shares ?? 0,
          open_orders: symOrders,
        };
      }),
      participants: rankingsArr.map((rk: Record<string, unknown>) => {
        const tcode = String(rk.tournament_code ?? "");
        const pShorts = activeShortsArr.filter(
          (sp: Record<string, unknown>) => sp.tournament_code === tcode
        );
        const shortLiab = pShorts.reduce(
          (acc, sp: Record<string, unknown>) => acc + Number(sp.current_liability ?? 0),
          0
        );
        const mCalls = pShorts.filter(
          (sp: Record<string, unknown>) =>
            sp.margin_status === "MARGIN_CALL" || sp.margin_status === "LIQUIDATING"
        ).length;
        return {
          game_participant_id: tcode,
          tournament_code: tcode,
          username: tcode,
          display_name: String(rk.display_name ?? tcode),
          net_worth: String(rk.final_net_worth ?? "1000000"),
          available_cash: "—",
          short_margin_locked: "—",
          short_liability: String(shortLiab),
          unfunded_debt: Number(rk.final_net_worth ?? 0) < 0 ? String(Math.abs(Number(rk.final_net_worth))) : "0",
          margin_call_positions: mCalls,
          realized_pnl: String(rk.realized_pnl ?? "0"),
        };
      }),
      recent_trades: openOrdersArr.slice(0, 25).map((o: Record<string, unknown>) => ({
        trade_id: String(o.id),
        symbol: String(o.symbol),
        price: String(o.limit_price ?? "0"),
        quantity: Number(o.remaining_quantity ?? 0),
        buyer_username: o.side === "BUY" ? String(o.display_name) : "RESTING BOOK",
        seller_username: o.side === "SELL" ? String(o.display_name) : "RESTING BOOK",
        is_forced: false,
        executed_at: String(o.created_at ?? new Date().toISOString()),
      })),
    };
  },

  adminAuditLogs: async (gameId: string, limit = 150): Promise<{ audit_logs: AuditEntry[] }> => {
    const arr = await request<Array<Record<string, unknown>>>(
      `/api/v1/admin/games/${gameId}/audit-logs?limit=${limit}`
    );
    return {
      audit_logs: arr.map((a) => ({
        seq_id: Number(a.id ?? 0),
        audit_id: String(a.id ?? ""),
        actor_user_id: a.actor_user_id ? String(a.actor_user_id) : null,
        actor_role: String(a.actor_role ?? "SYSTEM"),
        event_type: String(a.action_type ?? ""),
        entity_type: String(a.target_type ?? ""),
        entity_id: String(a.target_id ?? ""),
        reason: a.reason ? String(a.reason) : null,
        payload: (a.after_state as Record<string, unknown>) || {},
        correlation_id: null,
        entry_hash: String(a.record_hash ?? ""),
        prev_hash: a.prev_record_hash ? String(a.prev_record_hash) : null,
        created_at: String(a.created_at ?? new Date().toISOString()),
      })),
    };
  },
};
