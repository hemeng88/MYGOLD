from datetime import datetime
from typing import List, Optional

from pydantic import BaseModel


class LatestQuote(BaseModel):
    price: float
    yesterday_price: Optional[float] = None
    change_amt: Optional[float] = None
    change_rate: Optional[str] = None
    source_time: Optional[datetime] = None
    collected_at: Optional[datetime] = None
    source: str
    trade_date: str


class CurvePointOut(BaseModel):
    t: int
    p: float
    time: str


class DaySummary(BaseModel):
    date: str
    open: Optional[float] = None
    high: Optional[float] = None
    low: Optional[float] = None
    close: Optional[float] = None
    prev_close: Optional[float] = None
    change_amt: Optional[float] = None
    change_rate: Optional[float] = None
    point_count: int = 0
    first_ts: Optional[int] = None
    last_ts: Optional[int] = None
    updated_at: Optional[datetime] = None


class CurveResponse(BaseModel):
    date: str
    summary: Optional[DaySummary] = None
    points: List[CurvePointOut]


class CollectResult(BaseModel):
    ok: bool
    message: str
    tick: Optional[LatestQuote] = None
    curve_points_upserted: int = 0
    event_recorded: bool = False


class FeeRule(BaseModel):
    sell_fee_rate: float
    breakeven_rate: float
    breakeven_rate_pct: float
    formula: str
    note: str
    watch_window_seconds: int
    persist_checks: int
    tick_interval_seconds: int
    example_buy_price: Optional[float] = None
    example_breakeven_sell: Optional[float] = None
    example_needed_rise: Optional[float] = None


class MarketEventOut(BaseModel):
    id: int
    trade_date: str
    triggered_at: datetime
    direction: str
    start_price: float
    end_price: float
    change_amt: float
    change_rate: float
    threshold_rate: float
    window_seconds: int
    window_started_at: Optional[datetime] = None
    ts: Optional[int] = None
    headline: str
    source: Optional[str] = None
    url: Optional[str] = None
    summary: Optional[str] = None


class GoldLotIn(BaseModel):
    grams: float
    buy_price: float
    bought_at: str
    note: Optional[str] = None


class GoldLotOut(BaseModel):
    id: int
    grams: float
    buy_price: float
    bought_at: str
    note: Optional[str] = None
    cost: float
    created_at: datetime


class HoldingSummary(BaseModel):
    lots: List[GoldLotOut]
    total_grams: float
    avg_cost: Optional[float] = None
    total_cost: float
    current_price: Optional[float] = None
    market_value: Optional[float] = None
    unrealized_pnl: Optional[float] = None
    net_if_sell_now: Optional[float] = None
    breakeven_sell: Optional[float] = None
    needed_rise: Optional[float] = None
    sell_fee_rate: float
