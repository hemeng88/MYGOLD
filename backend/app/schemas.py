from datetime import datetime
from typing import Dict, List, Optional

from pydantic import BaseModel, Field


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
    tags: List[str] = Field(default_factory=list)


class AttributionType(BaseModel):
    tag: str
    weight_pct: float
    impact_points: float
    days: int
    avg_abs_move: float
    avg_move: float
    lift: Optional[float] = None
    baseline_share_pct: Optional[float] = None
    sample_headline: str = ""


class AttributionMonth(BaseModel):
    month: str
    tags: Dict[str, float] = Field(default_factory=dict)


class AttributionMove(BaseModel):
    trade_date: str
    change_pct: float
    close: float
    tags: List[str] = Field(default_factory=list)
    headline: str = ""


class VolatilityProjection(BaseModel):
    label: str
    trading_days: int
    sigma_pct: Optional[float] = None
    low: Optional[float] = None
    high: Optional[float] = None


class VolatilitySnapshot(BaseModel):
    daily_sd_20: Optional[float] = None
    daily_sd_60: Optional[float] = None
    mean_abs_move: Optional[float] = None
    atr14: Optional[float] = None
    atr14_pct: Optional[float] = None
    ma20: Optional[float] = None
    ma60: Optional[float] = None
    window_high: Optional[float] = None
    window_low: Optional[float] = None
    projections: List[VolatilityProjection] = Field(default_factory=list)


class AttributionResponse(BaseModel):
    ready: bool
    message: Optional[str] = None
    window_days: int
    start_date: Optional[str] = None
    end_date: Optional[str] = None
    proxy_symbol: Optional[str] = None
    threshold_pct: Optional[float] = None
    bar_count: int = 0
    flash_count: int = 0
    significant_days: int = 0
    start_close: Optional[float] = None
    end_close: Optional[float] = None
    total_change_pct: Optional[float] = None
    baseline_abs_move: Optional[float] = None
    attributed_points: Optional[float] = None
    unattributed_days: int = 0
    unattributed_points: Optional[float] = None
    types: List[AttributionType] = Field(default_factory=list)
    monthly: List[AttributionMonth] = Field(default_factory=list)
    top_moves: List[AttributionMove] = Field(default_factory=list)
    volatility: Optional[VolatilitySnapshot] = None


class AdviceLevel(BaseModel):
    price: float
    note: str
    gap_pct: Optional[float] = None
    kind: Optional[str] = None


class AdviceDriver(BaseModel):
    tag: str
    share_pct: float


class AdviceResponse(BaseModel):
    ready: bool
    message: Optional[str] = None
    as_of: Optional[datetime] = None
    price: Optional[float] = None
    trade_date: Optional[str] = None
    stance: Optional[str] = None
    headline: Optional[str] = None
    z_score: Optional[float] = None
    ma20: Optional[float] = None
    ma60: Optional[float] = None
    atr: Optional[float] = None
    swing_high: Optional[float] = None
    swing_low: Optional[float] = None
    breakeven: Optional[float] = None
    avg_cost: Optional[float] = None
    total_grams: Optional[float] = None
    net_if_sell_now: Optional[float] = None
    buy_levels: List[AdviceLevel] = Field(default_factory=list)
    sell_levels: List[AdviceLevel] = Field(default_factory=list)
    drivers: List[AdviceDriver] = Field(default_factory=list)
    notes: List[str] = Field(default_factory=list)


class RefreshResult(BaseModel):
    ok: bool
    bars_written: int = 0
    calendar_added: int = 0
    narrative_added: int = 0
    message: str


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
