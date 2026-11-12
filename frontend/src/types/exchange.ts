export type UserRole = "PLAYER" | "ADMIN";

export type GameStatus =
  | "DRAFT"
  | "CONFIGURED"
  | "LOBBY"
  | "MAIN_TRADING"
  | "PAUSED"
  | "SHORT_SETTLEMENT"
  | "SETTLING"
  | "COMPLETED"
  | "ARCHIVED";

export type OrderIntent = "BUY_LONG" | "SELL_LONG" | "SHORT_SELL" | "BUY_TO_COVER";
export type OrderPriceType = "MARKET" | "LIMIT";

export interface UserSummary {
  user_id: string;
  email: string;
  username: string;
  display_name: string;
  role: UserRole;
  institution: string | null;
}

export interface AuthResponse {
  access_token: string;
  token_type: string;
  user: UserSummary;
}

export interface ClockInfo {
  game_id: string;
  status: GameStatus;
  server_time: string;
  phase_started_at: string | null;
  phase_ends_at: string | null;
  remaining_phase_sec: number;
  trading_duration_sec: number;
  settlement_duration_sec: number;
  is_trading_open: boolean;
  is_close_only_phase: boolean;
  is_completed: boolean;
}

export interface GameSummary {
  game_id: string;
  code: string;
  name: string;
  status: GameStatus;
  starting_cash: string;
  starting_shares_per_stock: number;
  trading_duration_sec: number;
  settlement_duration_sec: number;
  tick_size: string;
  initial_margin_ratio: string;
  maintenance_margin_ratio: string;
  critical_margin_ratio: string;
  margin_call_grace_sec: number;
  default_short_pool_shares: number;
  short_position_limit_per_stock: number;
  allow_simultaneous_long_short: boolean;
  market_order_collar_pct: string;
  participant_count?: number;
  joined?: boolean;
  tournament_code?: string | null;
  clock: ClockInfo;
}

export interface StockMarketItem {
  stock_id: string;
  symbol: string;
  company_name: string;
  sector: string;
  opening_price: string;
  tick_size: string;
  shortable: boolean;
  short_position_limit: number;
  exposure_profile?: Record<string, number>;
  last_traded_price: string | null;
  fundamental_ref_price: string;
  official_mtm_price: string;
  best_bid: string | null;
  best_ask: string | null;
  change_pct_from_open?: string;
  borrow_pool?: {
    total_pool_shares: number;
    borrowed_shares: number;
    reserved_Order_shares?: number;
    reserved_order_shares?: number;
    remaining_shares: number;
  };
}

export interface BookLevel {
  price: string;
  quantity: number;
  order_count: number;
}

export interface OrderBookDepth {
  stock_id: string;
  symbol: string;
  bids: BookLevel[];
  asks: BookLevel[];
  best_bid: string | null;
  best_ask: string | null;
  spread: string | null;
}

export interface CandleBar {
  time: number;
  bucket_start: string;
  open: number;
  high: number;
  low: number;
  close: number;
  volume: number;
}

export interface LongHoldingItem {
  stock_id: string;
  symbol: string;
  available_quantity: number;
  reserved_sell_quantity: number;
  total_quantity: number;
  avg_entry_price: string;
  mtm_price: string;
  market_value: string;
  unrealized_pnl: string;
}

export interface ShortPositionItem {
  stock_id: string;
  symbol: string;
  borrowed_quantity: number;
  reserved_cover_quantity: number;
  avg_short_price: string;
  mtm_price: string;
  short_liability: string;
  sale_proceeds_locked: string;
  margin_collateral_locked: string;
  required_maintenance_margin: string;
  unrealized_pnl: string;
  margin_ratio: string | null;
  margin_status: "HEALTHY" | "WARNING" | "MARGIN_CALL" | "LIQUIDATING";
  margin_call_deadline_at: string | null;
}

export interface PortfolioValuation {
  game_participant_id: string;
  available_cash: string;
  order_reserved_cash: string;
  short_proceeds_locked: string;
  short_margin_locked: string;
  unfunded_settlement_debt: string;
  realized_pnl: string;
  unrealized_long_pnl: string;
  unrealized_short_pnl: string;
  long_market_value: string;
  short_buyback_liability: string;
  net_worth: string;
  starting_net_worth: string;
  total_return_pct: string;
  long_holdings: LongHoldingItem[];
  short_positions: ShortPositionItem[];
}

export interface OrderRecord {
  order_id: string;
  client_order_id: string | null;
  stock_id: string;
  symbol: string;
  intent: OrderIntent;
  side: "BUY" | "SELL";
  price_type: OrderPriceType;
  time_in_force: string;
  limit_price: string | null;
  collar_price: string | null;
  quantity: number;
  filled_quantity: number;
  remaining_quantity: number;
  avg_fill_price: string | null;
  status: string;
  reject_reason: string | null;
  cancel_reason: string | null;
  is_forced_liquidation: boolean;
  submitted_at: string;
  updated_at: string;
}

export interface TradeRecord {
  trade_id: string;
  symbol: string;
  role: "BUYER" | "SELLER";
  price: string;
  quantity: number;
  notional: string;
  counterparty_code: string;
  is_forced_liquidation: boolean;
  executed_at: string;
}

export interface ReleasedNewsItem {
  event_id: string;
  headline: string;
  body: string;
  category_slug: string;
  archetype: string;
  severity: string;
  is_Chain?: boolean;
  chain_id: string | null;
  chain_stage: number | null;
  chain_total_stages: number | null;
  certainty_pct: string;
  affected_symbols: string[];
  released_at: string | null;
  status: string;
  simulation_disclaimer: string;
}

export interface LeaderboardEntry {
  rank: number;
  game_participant_id: string;
  tournament_code: string;
  username: string;
  display_name: string;
  institution: string | null;
  net_worth: string;
  return_pct: string;
  realized_pnl: string;
  available_cash: string;
  order_reserved_cash: string;
  long_market_value: string;
  short_liability: string;
  unfunded_debt: string;
  is_final: boolean;
}

export interface AdminNewsImpactItem {
  symbol: string;
  direction: number;
  magnitude_pct: string;
  transient_Ratio?: string;
  transient_ratio?: string;
  half_life_sec: number;
}

export interface AdminNewsEvent {
  event_id: string;
  category_slug: string;
  archetype: string;
  severity: string;
  headline: string;
  body: string;
  status: string;
  chain_id: string | null;
  chain_stage: number | null;
  chain_total_stages: number | null;
  scheduled_offset_sec: number | null;
  scheduled_release_at: string | null;
  released_at: string | null;
  impacts: AdminNewsImpactItem[];
}

export interface SurveillanceDashboard {
  game_id: string;
  status: GameStatus;
  clock: ClockInfo;
  invariants: {
    passed: boolean;
    participant_count: number;
    violations: string[];
  };
  stocks: Array<{
    symbol: string;
    ltp: string | null;
    ref_price: string;
    mtm_price: string;
    best_bid: string | null;
    best_ask: string | null;
    pool_total: number;
    pool_borrowed: number;
    pool_remaining: number;
    open_orders: number;
  }>;
  participants: Array<{
    game_participant_id: string;
    tournament_code: string;
    username: string;
    display_name: string;
    net_worth: string;
    available_cash: string;
    short_margin_locked: string;
    short_liability: string;
    unfunded_debt: string;
    margin_call_positions: number;
    realized_pnl: string;
  }>;
  recent_trades: Array<{
    trade_id: string;
    symbol: string;
    price: string;
    quantity: number;
    buyer_username: string;
    seller_username: string;
    is_forced: boolean;
    executed_at: string;
  }>;
}

export interface AuditEntry {
  seq_id: number;
  audit_id: string;
  actor_user_id: string | null;
  actor_role: string;
  event_type: string;
  entity_type: string;
  entity_id: string;
  reason: string | null;
  payload: Record<string, unknown>;
  correlation_id: string | null;
  entry_hash: string;
  prev_hash: string | null;
  created_at: string;
}
