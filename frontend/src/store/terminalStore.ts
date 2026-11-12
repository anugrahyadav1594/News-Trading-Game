import { create } from "zustand";
import { exchangeApi, normalizeClock, normalizeNewsItem, normalizeStock } from "@/lib/api";
import type {
  CandleBar,
  ClockInfo,
  GameSummary,
  LeaderboardEntry,
  OrderBookDepth,
  OrderIntent,
  OrderRecord,
  PortfolioValuation,
  ReleasedNewsItem,
  StockMarketItem,
  TradeRecord,
} from "@/types/exchange";

export type PlayerTab =
  | "LOBBY"
  | "TERMINAL"
  | "STOCK_DETAIL"
  | "PORTFOLIO"
  | "HISTORY"
  | "LEADERBOARD";

export interface ToastNotice {
  id: string;
  tone: "success" | "warning" | "error" | "info";
  title: string;
  detail?: string;
}

interface TicketDraft {
  intent: OrderIntent;
  limitPrice: string;
  quantity: string;
}

interface TerminalState {
  games: GameSummary[];
  activeGameId: string | null;
  activeGame: GameSummary | null;
  clock: ClockInfo | null;
  activeTab: PlayerTab;

  stocks: StockMarketItem[];
  selectedSymbol: string;
  orderBook: OrderBookDepth | null;
  candleInterval: 5 | 60;
  candles: CandleBar[];
  newsFeed: ReleasedNewsItem[];
  portfolio: PortfolioValuation | null;
  orders: OrderRecord[];
  trades: TradeRecord[];
  leaderboard: LeaderboardEntry[];

  wsStatus: "DISCONNECTED" | "CONNECTING" | "LIVE";
  toasts: ToastNotice[];
  ticketDraft: TicketDraft;

  setActiveTab: (tab: PlayerTab) => void;
  pushToast: (notice: Omit<ToastNotice, "id">) => void;
  dismissToast: (id: string) => void;
  setTicketFromBook: (price: string, intent?: OrderIntent, qty?: number) => void;
  setSelectedSymbol: (symbol: string) => Promise<void>;
  setCandleInterval: (interval: 5 | 60) => Promise<void>;

  loadGamesAndSelectDefault: () => Promise<void>;
  selectGame: (gameId: string, autoJoinPlayer?: boolean) => Promise<void>;
  joinActiveGame: () => Promise<void>;
  refreshAllData: () => Promise<void>;
  refreshPrivateData: () => Promise<void>;
  refreshSymbolData: (symbol?: string) => Promise<void>;

  connectStream: (gameId: string) => void;
  disconnectStream: () => void;
}

let wsInstance: WebSocket | null = null;
let wsReconnectTimer: ReturnType<typeof setTimeout> | null = null;
let fallbackSyncInterval: ReturnType<typeof setInterval> | null = null;
let currentStreamGameId: string | null = null;

export const useTerminalStore = create<TerminalState>((set, get) => ({
  games: [],
  activeGameId: null,
  activeGame: null,
  clock: null,
  activeTab: "TERMINAL",

  stocks: [],
  selectedSymbol: "RELIANCE",
  orderBook: null,
  candleInterval: 5,
  candles: [],
  newsFeed: [],
  portfolio: null,
  orders: [],
  trades: [],
  leaderboard: [],

  wsStatus: "DISCONNECTED",
  toasts: [],
  ticketDraft: {
    intent: "BUY_LONG",
    limitPrice: "1000.00",
    quantity: "10",
  },

  setActiveTab: (tab) => set({ activeTab: tab }),

  pushToast: (notice) => {
    const id = `${Date.now()}-${Math.random().toString(36).slice(2, 7)}`;
    set((s) => ({ toasts: [{ ...notice, id }, ...s.toasts].slice(0, 5) }));
    setTimeout(() => {
      set((s) => ({ toasts: s.toasts.filter((t) => t.id !== id) }));
    }, 5500);
  },

  dismissToast: (id) => set((s) => ({ toasts: s.toasts.filter((t) => t.id !== id) })),

  setTicketFromBook: (price, intent, qty) =>
    set((s) => ({
      ticketDraft: {
        intent: intent || s.ticketDraft.intent,
        limitPrice: Number(price).toFixed(2),
        quantity: qty ? String(qty) : s.ticketDraft.quantity,
      },
    })),

  setSelectedSymbol: async (symbol) => {
    const stock = get().stocks.find((st) => st.symbol === symbol);
    const defaultPx =
      stock?.last_traded_price || stock?.official_mtm_price || stock?.opening_price || "1000.00";
    set((s) => ({
      selectedSymbol: symbol,
      ticketDraft: { ...s.ticketDraft, limitPrice: Number(defaultPx).toFixed(2) },
    }));
    await get().refreshSymbolData(symbol);
  },

  setCandleInterval: async (interval) => {
    set({ candleInterval: interval });
    const { activeGameId, selectedSymbol } = get();
    if (!activeGameId) return;
    try {
      const cRes = await exchangeApi.getCandles(activeGameId, selectedSymbol, interval);
      set({ candles: cRes.candles });
    } catch {
      // ignore
    }
  },

  loadGamesAndSelectDefault: async () => {
    const res = await exchangeApi.listGames();
    set({ games: res.games });
    if (res.games.length === 0) return;

    const currentId = get().activeGameId;
    const preferred =
      res.games.find((g) => g.game_id === currentId) ||
      res.games.find((g) => g.code === "MTT-ROUND1") ||
      res.games.find((g) => g.status === "MAIN_TRADING") ||
      res.games[0];

    await get().selectGame(preferred.game_id, true);
  },

  selectGame: async (gameId, autoJoinPlayer = true) => {
    get().disconnectStream();
    const gameDetail = await exchangeApi.getGame(gameId);

    let defaultTab: PlayerTab = get().activeTab;
    if (gameDetail.status === "LOBBY" || gameDetail.status === "CONFIGURED") {
      defaultTab = "LOBBY";
    } else if (gameDetail.status === "COMPLETED") {
      defaultTab = "LEADERBOARD";
    } else if (defaultTab === "LOBBY") {
      defaultTab = "TERMINAL";
    }

    set({
      activeGameId: gameId,
      activeGame: gameDetail,
      clock: gameDetail.clock,
      activeTab: defaultTab,
    });

    const rawToken = typeof window !== "undefined" ? window.localStorage.getItem("mtt_access_token") : null;
    if (autoJoinPlayer && rawToken && !gameDetail.joined) {
      try {
        await exchangeApi.joinGame(gameId);
        const updatedGame = await exchangeApi.getGame(gameId);
        set({ activeGame: updatedGame, clock: updatedGame.clock });
      } catch {
        // Admin accounts cannot join as players
      }
    }

    await get().refreshAllData();
    get().connectStream(gameId);
  },

  joinActiveGame: async () => {
    const { activeGameId } = get();
    if (!activeGameId) return;
    const res = await exchangeApi.joinGame(activeGameId);
    const updatedGame = await exchangeApi.getGame(activeGameId);
    set({
      activeGame: updatedGame,
      clock: updatedGame.clock,
      portfolio: res.portfolio,
    });
    get().pushToast({
      tone: "success",
      title: `Seat Assigned (${updatedGame.tournament_code || "MTT"})`,
      detail: "Allocated 100 shares × 5 stocks + ₹5,00,000 cash = ₹10,00,000 starting net worth.",
    });
    await get().refreshAllData();
  },

  refreshSymbolData: async (symbolOverride) => {
    const { activeGameId, candleInterval } = get();
    const sym = symbolOverride || get().selectedSymbol;
    if (!activeGameId || !sym) return;
    try {
      const [detRes, candleRes] = await Promise.all([
        exchangeApi.getStockDetailAndBook(activeGameId, sym),
        exchangeApi.getCandles(activeGameId, sym, candleInterval),
      ]);
      if (get().selectedSymbol === sym) {
        set((s) => ({
          orderBook: detRes.book,
          candles: candleRes.candles,
          stocks: s.stocks.map((st) =>
            st.symbol === sym ? { ...st, exposure_profile: detRes.factorExposures } : st
          ),
        }));
      }
    } catch {
      // ignore
    }
  },

  refreshPrivateData: async () => {
    const { activeGameId, activeGame } = get();
    if (!activeGameId || !activeGame?.joined) return;
    try {
      const [pf, ordRes, trdRes] = await Promise.all([
        exchangeApi.getPortfolio(activeGameId),
        exchangeApi.listOrders(activeGameId),
        exchangeApi.listMyTrades(activeGameId),
      ]);
      set({ portfolio: pf, orders: ordRes.orders, trades: trdRes.trades });
    } catch {
      // ignore
    }
  },

  refreshAllData: async () => {
    const { activeGameId, selectedSymbol } = get();
    if (!activeGameId) return;
    try {
      const [gameDetail, stocksRes, newsRes, lbRes] = await Promise.all([
        exchangeApi.getGame(activeGameId),
        exchangeApi.getStocks(activeGameId),
        exchangeApi.getNewsFeed(activeGameId),
        exchangeApi.getLeaderboard(activeGameId),
      ]);

      const symExists = stocksRes.stocks.some((s) => s.symbol === selectedSymbol);
      const nextSym = symExists ? selectedSymbol : stocksRes.stocks[0]?.symbol || "RELIANCE";

      set({
        activeGame: gameDetail,
        clock: stocksRes.clock || gameDetail.clock,
        stocks: stocksRes.stocks,
        selectedSymbol: nextSym,
        newsFeed: newsRes.items,
        leaderboard: lbRes.entries,
      });

      await Promise.all([get().refreshSymbolData(nextSym), get().refreshPrivateData()]);
    } catch {
      // ignore
    }
  },

  connectStream: (gameId) => {
    if (typeof window === "undefined") return;
    get().disconnectStream();
    currentStreamGameId = gameId;

    const openSocket = () => {
      if (currentStreamGameId !== gameId) return;
      const token = window.localStorage.getItem("mtt_access_token") || "";
      const proto = window.location.protocol === "https:" ? "wss:" : "ws:";
      // Strictly same-origin relative host for Arena live preview compatibility
      const wsUrl = `${proto}//${window.location.host}/ws/v1/games/${gameId}${
        token ? `?token=${encodeURIComponent(token)}` : ""
      }`;

      set({ wsStatus: "CONNECTING" });
      const ws = new WebSocket(wsUrl);
      wsInstance = ws;

      ws.onopen = () => {
        set({ wsStatus: "LIVE" });
      };

      ws.onmessage = (ev) => {
        try {
          const msg = JSON.parse(ev.data);
          const eventName: string = msg.event || msg.type || "";
          const payload = (msg.payload || msg.data || {}) as Record<string, unknown>;

          if (eventName === "CLOCK_SYNC") {
            const gm = get().activeGame;
            const nextClock = normalizeClock(
              payload,
              gm?.trading_duration_sec ?? 2700,
              gm?.settlement_duration_sec ?? 300
            );
            const prevStatus = get().clock?.status;
            set((s) => ({
              clock: nextClock,
              activeGame: s.activeGame
                ? { ...s.activeGame, status: nextClock.status, clock: nextClock }
                : s.activeGame,
            }));
            if (prevStatus && prevStatus !== nextClock.status) {
              get().refreshAllData();
            }
          } else if (eventName === "MARKET_TICK" && Array.isArray(payload.stocks)) {
            set((s) => {
              const incomingMap = new Map<string, StockMarketItem>();
              for (const rawSt of payload.stocks as Array<Record<string, unknown>>) {
                const norm = normalizeStock(rawSt);
                incomingMap.set(norm.symbol, norm);
              }
              return {
                stocks: s.stocks.map((existing) => {
                  const updated = incomingMap.get(existing.symbol);
                  return updated
                    ? { ...updated, exposure_profile: existing.exposure_profile }
                    : existing;
                }),
              };
            });
            get().refreshPrivateData();
            exchangeApi
              .getCandles(gameId, get().selectedSymbol, get().candleInterval)
              .then((r) => set({ candles: r.candles }))
              .catch(() => {});
          } else if (eventName === "ORDERBOOK_SNAPSHOT" || eventName === "ORDERBOOK_L2") {
            if (payload.symbol === get().selectedSymbol) {
              set({
                orderBook: {
                  stock_id: String(payload.stock_id ?? ""),
                  symbol: String(payload.symbol),
                  bids: (payload.bids as OrderBookDepth["bids"]) || [],
                  asks: (payload.asks as OrderBookDepth["asks"]) || [],
                  best_bid: payload.best_bid != null ? String(payload.best_bid) : null,
                  best_ask: payload.best_ask != null ? String(payload.best_ask) : null,
                  spread: payload.spread != null ? String(payload.spread) : null,
                },
              });
            }
          } else if (eventName === "NEWS_RELEASED") {
            const normNews = normalizeNewsItem(payload);
            get().pushToast({
              tone: normNews.status === "REVERSED" ? "info" : "warning",
              title: `SIMULATED WIRE: ${normNews.severity} • ${normNews.archetype}`,
              detail: normNews.headline,
            });
            exchangeApi
              .getNewsFeed(gameId)
              .then((r) => set({ newsFeed: r.items }))
              .catch(() => {});
          } else if (eventName === "PHASE_CHANGED" || eventName === "GAME_PHASE_CHANGED") {
            const newSt = String(payload.new_phase || payload.status || msg.phase || "");
            get().pushToast({
              tone: "warning",
              title: `TOURNAMENT PHASE: ${newSt}`,
              detail:
                newSt === "SHORT_SETTLEMENT"
                  ? "5-Minute Short Settlement Only! Only BUY_TO_COVER and SELL_LONG orders are permitted."
                  : newSt === "COMPLETED"
                  ? "Tournament Completed! Remaining shorts settled and official rankings locked."
                  : `Game entered ${newSt}`,
            });
            get().refreshAllData();
          } else if (eventName === "LEADERBOARD_UPDATED" || eventName === "LEADERBOARD_SNAPSHOT") {
            exchangeApi
              .getLeaderboard(gameId)
              .then((r) => set({ leaderboard: r.entries }))
              .catch(() => {});
          } else if (eventName === "ORDER_UPDATED" || eventName === "PORTFOLIO_SYNC") {
            get().refreshPrivateData();
            get().refreshSymbolData();
          } else if (eventName === "MARGIN_ALERT") {
            get().pushToast({
              tone: "error",
              title: `MARGIN ALERT (${payload.symbol || "SHORT"}): ${payload.type}`,
              detail:
                payload.type === "FORCED_LIQUIDATION"
                  ? `Forced Buy-to-Cover executed (${payload.filled_cover_qty} shares) due to margin breach.`
                  : "Short position entered MARGIN CALL! Cover shares before grace window expires.",
            });
            get().refreshPrivateData();
          }
        } catch {
          // ignore malformed frame
        }
      };

      ws.onclose = () => {
        if (currentStreamGameId !== gameId) return;
        set({ wsStatus: "DISCONNECTED" });
        wsReconnectTimer = setTimeout(openSocket, 2200);
      };

      ws.onerror = () => {
        ws.close();
      };
    };

    openSocket();

    fallbackSyncInterval = setInterval(() => {
      const state = get();
      if (state.wsStatus !== "LIVE") {
        state.refreshAllData();
      } else {
        state.refreshPrivateData();
      }
    }, 4500);
  },

  disconnectStream: () => {
    currentStreamGameId = null;
    if (wsReconnectTimer) {
      clearTimeout(wsReconnectTimer);
      wsReconnectTimer = null;
    }
    if (fallbackSyncInterval) {
      clearInterval(fallbackSyncInterval);
      fallbackSyncInterval = null;
    }
    if (wsInstance) {
      wsInstance.onclose = null;
      wsInstance.close();
      wsInstance = null;
    }
    set({ wsStatus: "DISCONNECTED" });
  },
}));
