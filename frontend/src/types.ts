export interface LatestQuote {
  price: number;
  yesterday_price: number | null;
  change_amt: number | null;
  change_rate: string | null;
  source_time: string | null;
  collected_at: string | null;
  source: string;
  trade_date: string;
  london_usd?: number | null;
  london_prev?: number | null;
  london_change_amt?: number | null;
  london_change_rate?: number | null;
  london_source?: string | null;
  usdcny?: number | null;
  usdcny_prev?: number | null;
  usdcny_change_amt?: number | null;
  usdcny_change_rate?: number | null;
  usdcny_source?: string | null;
  troy_ounce_grams?: number | null;
  london_cny_gram?: number | null;
  zheshang_usd_oz?: number | null;
  premium_cny?: number | null;
  premium_pct?: number | null;
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
  win_rate?: number | null;
  mean_next?: number | null;
  days: number;
  kind?: string;
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
  session?: AdviceSession | null;
}

export interface AdviceSession {
  band: string | null;
  band_label: string | null;
  clock: string | null;
  open_count: number;
  open_names: string[];
  hour_vol_rank_pct: number | null;
  profile_days: number;
  hot_names?: string[];
  hot_open?: string[];
}

export interface SessionRange {
  start: string;
  end: string;
  start_min: number;
  end_min: number;
}

export interface SessionExchange {
  id: string;
  name: string;
  region: string;
  timezone: string;
  source: string;
  open: boolean;
  weekend: boolean;
  ranges: SessionRange[];
  start?: string | null;
  impact_abs_pct?: number | null;
  hot?: boolean;
  hot_rank?: number | null;
}

export interface SessionHour {
  hour: number;
  label: string;
  samples: number;
  mean_pct: number | null;
  abs_pct: number | null;
  win_rate: number | null;
}

export interface SessionSnapshot {
  as_of: string;
  timezone: string;
  clock: string;
  clock_min: number;
  band: string;
  band_label: string;
  open_count: number;
  open_names: string[];
  exchanges: SessionExchange[];
  bands: { id: string; label: string; color: string }[];
  hour_profile: SessionHour[];
  hour_abs_pct: number | null;
  hour_mean_pct: number | null;
  hour_win_rate: number | null;
  hour_samples: number;
  hour_vol_rank_pct: number | null;
  profile_days: number;
  note: string;
}
export interface FundHoldingItem {
  secid: string;
  code: string;
  name: string | null;
  market: string | null;
  weight_pct: number;
  rank: number | null;
  price: number | null;
  change_pct: number | null;
  contrib_pct: number | null;
  quoted: boolean;
}

export interface FundItem {
  code: string;
  name: string;
  fund_type: string | null;
  nav: number | null;
  nav_date: string | null;
  nav_chg_pct: number | null;
  is_cash_fund: boolean;
  yield_10k: number | null;
  shares: number | null;
  cost_price: number | null;
  cost: number | null;
  nav_value: number | null;
  estimate_value: number | null;
  today_pnl: number | null;
  total_pnl: number | null;
  total_pnl_pct: number | null;
  holdings_count: number;
  quoted_count: number;
  disclosed_pct: number | null;
  covered_pct: number | null;
  estimate_pct: number | null;
  conservative_pct: number | null;
  estimate_nav: number | null;
  report_date: string | null;
  report_label: string | null;
  report_age_days: number | null;
  stale: boolean;
  confidence: "high" | "medium" | "low";
  lead_name: string | null;
  lead_contrib_pct: number | null;
  drag_name: string | null;
  drag_contrib_pct: number | null;
  as_of: string | null;
  ready: boolean;
  message: string | null;
}

export interface FundList {
  session: string;
  items: FundItem[];
}

export interface FundDetail {
  ready: boolean;
  message: string | null;
  session: string | null;
  fund: FundItem | null;
  holdings: FundHoldingItem[];
}

export interface FundFavorite {
  code: string;
  name: string;
  fund_type: string | null;
  shares: number | null;
  cost_price: number | null;
  added_at: string;
}

export interface FundSearchItem {
  code: string;
  name: string;
  fund_type: string | null;
  nav: number | null;
  nav_date: string | null;
  favorited: boolean;
}

export interface FundRefreshResult {
  ok: boolean;
  holdings: number;
  navs: number;
  quotes: number;
  message: string;
}


export interface FundRankPeriod {
  key: string;
  label: string;
}

export interface FundRankFund {
  rank: number;
  code: string;
  name: string;
  return_pct: number;
  nav: number | null;
  nav_date: string | null;
}

export interface FundRankStockItem {
  code: string;
  name: string | null;
  fund_count: number;
  weight_sum: number;
}

export interface FundRank {
  period: string;
  period_label: string | null;
  periods: FundRankPeriod[];
  as_of: string | null;
  funds: FundRankFund[];
  hot_stocks: FundRankStockItem[];
  message: string | null;
}

export interface FundRankRefreshResult {
  ok: boolean;
  periods: number;
  funds: number;
  message: string;
}
