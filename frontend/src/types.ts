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
}
