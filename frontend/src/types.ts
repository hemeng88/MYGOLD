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


export interface LoginResult {
  token: string;
  username: string;
}

export interface Me {
  username: string;
}
