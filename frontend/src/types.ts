export interface LatestQuote {
  price: number;
  yesterday_price: number | null;
  change_amt: number | null;
  change_rate: string | null;
  source_time: string | null;
  collected_at: string | null;
  source: string;
  trade_date: string;
}

export interface DaySummary {
  date: string;
  open: number | null;
  high: number | null;
  low: number | null;
  close: number | null;
  prev_close: number | null;
  change_amt: number | null;
  change_rate: number | null;
  point_count: number;
  first_ts: number | null;
  last_ts: number | null;
  updated_at: string | null;
}

export interface CurvePoint {
  t: number;
  p: number;
  time: string;
}

export interface CurveResponse {
  date: string;
  summary: DaySummary | null;
  points: CurvePoint[];
}

export interface CollectResult {
  ok: boolean;
  message: string;
  tick: LatestQuote | null;
  curve_points_upserted: number;
  event_recorded?: boolean;
}

export interface FeeRule {
  sell_fee_rate: number;
  breakeven_rate: number;
  breakeven_rate_pct: number;
  formula: string;
  note: string;
  watch_window_seconds: number;
  persist_checks: number;
  tick_interval_seconds: number;
  example_buy_price?: number | null;
  example_breakeven_sell?: number | null;
  example_needed_rise?: number | null;
}

export interface MarketEvent {
  id: number;
  trade_date: string;
  triggered_at: string;
  direction: string;
  start_price: number;
  end_price: number;
  change_amt: number;
  change_rate: number;
  threshold_rate: number;
  window_seconds: number;
  window_started_at: string | null;
  ts: number | null;
  headline: string;
  source: string | null;
  url: string | null;
  summary: string | null;
  tags: string[];
}

export interface AdviceLevel {
  price: number;
  note: string;
  gap_pct: number | null;
  kind: string | null;
}

export interface AdviceFactor {
  name: string;
  label: string;
  detail: string;
  score: number;
  win_rate: number;
  mean_next: number;
  days: number;
}

export interface Advice {
  ready: boolean;
  message: string | null;
  as_of: string | null;
  price: number | null;
  trade_date: string | null;
  stance: "accumulate" | "hold" | "reduce" | "wait" | null;
  headline: string | null;
  score: number | null;
  factors: AdviceFactor[];
  mood_label: string | null;
  polarity: number | null;
  volume_rank_pct: number | null;
  z_score: number | null;
  ma20: number | null;
  ma60: number | null;
  atr: number | null;
  swing_high: number | null;
  swing_low: number | null;
  breakeven: number | null;
  avg_cost: number | null;
  total_grams: number | null;
  net_if_sell_now: number | null;
  buy_levels: AdviceLevel[];
  sell_levels: AdviceLevel[];
  drivers: { tag: string; share_pct: number }[];
  notes: string[];
}

export interface AttributionType {
  tag: string;
  weight_pct: number;
  impact_points: number;
  days: number;
  avg_abs_move: number;
  avg_move: number;
  lift: number | null;
  baseline_share_pct: number | null;
  sample_headline: string;
}

export interface AttributionMove {
  trade_date: string;
  change_pct: number;
  close: number;
  tags: string[];
  headline: string;
}

export interface VolatilityProjection {
  label: string;
  trading_days: number;
  sigma_pct: number | null;
  low: number | null;
  high: number | null;
}

export interface VolatilitySnapshot {
  daily_sd_20: number | null;
  daily_sd_60: number | null;
  mean_abs_move: number | null;
  atr14: number | null;
  atr14_pct: number | null;
  ma20: number | null;
  ma60: number | null;
  window_high: number | null;
  window_low: number | null;
  projections: VolatilityProjection[];
}

export interface Attribution {
  ready: boolean;
  message: string | null;
  window_days: number;
  start_date: string | null;
  end_date: string | null;
  proxy_symbol: string | null;
  threshold_pct: number | null;
  bar_count: number;
  flash_count: number;
  significant_days: number;
  start_close: number | null;
  end_close: number | null;
  total_change_pct: number | null;
  baseline_abs_move: number | null;
  attributed_points: number | null;
  unattributed_days: number;
  types: AttributionType[];
  monthly: { month: string; tags: Record<string, number> }[];
  top_moves: AttributionMove[];
  volatility: VolatilitySnapshot | null;
}

export interface GoldLot {
  id: number;
  grams: number;
  buy_price: number;
  bought_at: string;
  note: string | null;
  cost: number;
  created_at: string;
}

export interface HoldingSummary {
  lots: GoldLot[];
  total_grams: number;
  avg_cost: number | null;
  total_cost: number;
  current_price: number | null;
  market_value: number | null;
  unrealized_pnl: number | null;
  net_if_sell_now: number | null;
  breakeven_sell: number | null;
  needed_rise: number | null;
  sell_fee_rate: number;
}
