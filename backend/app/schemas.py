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
