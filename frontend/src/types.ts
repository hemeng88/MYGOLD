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
