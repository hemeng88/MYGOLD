from datetime import datetime

from sqlalchemy import DateTime, Float, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from .database import Base


class PriceTick(Base):
    __tablename__ = "price_ticks"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    collected_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, index=True)
    source_time: Mapped[datetime] = mapped_column(DateTime, nullable=True)
    trade_date: Mapped[str] = mapped_column(String(10), nullable=False, index=True)
    price: Mapped[float] = mapped_column(Float, nullable=False)
    yesterday_price: Mapped[float] = mapped_column(Float, nullable=True)
    change_amt: Mapped[float] = mapped_column(Float, nullable=True)
    change_rate: Mapped[str] = mapped_column(String(32), nullable=True)
    source: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    raw_json: Mapped[str] = mapped_column(Text, nullable=True)


class CurvePoint(Base):
    __tablename__ = "curve_points"
    __table_args__ = (UniqueConstraint("trade_date", "ts", name="uq_curve_date_ts"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    trade_date: Mapped[str] = mapped_column(String(10), nullable=False, index=True)
    ts: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    price: Mapped[float] = mapped_column(Float, nullable=False)
    source: Mapped[str] = mapped_column(String(32), nullable=False)


class DailySummary(Base):
    __tablename__ = "daily_summaries"

    trade_date: Mapped[str] = mapped_column(String(10), primary_key=True)
    open_price: Mapped[float] = mapped_column(Float, nullable=True)
    high_price: Mapped[float] = mapped_column(Float, nullable=True)
    low_price: Mapped[float] = mapped_column(Float, nullable=True)
    close_price: Mapped[float] = mapped_column(Float, nullable=True)
    prev_close: Mapped[float] = mapped_column(Float, nullable=True)
    change_amt: Mapped[float] = mapped_column(Float, nullable=True)
    change_rate: Mapped[float] = mapped_column(Float, nullable=True)
    point_count: Mapped[int] = mapped_column(Integer, default=0)
    first_ts: Mapped[int] = mapped_column(Integer, nullable=True)
    last_ts: Mapped[int] = mapped_column(Integer, nullable=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)


class MarketEvent(Base):
    __tablename__ = "market_events"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    trade_date: Mapped[str] = mapped_column(String(10), nullable=False, index=True)
    triggered_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, index=True)
    direction: Mapped[str] = mapped_column(String(8), nullable=False, index=True)
    start_price: Mapped[float] = mapped_column(Float, nullable=False)
    end_price: Mapped[float] = mapped_column(Float, nullable=False)
    change_amt: Mapped[float] = mapped_column(Float, nullable=False)
    change_rate: Mapped[float] = mapped_column(Float, nullable=False)
    threshold_rate: Mapped[float] = mapped_column(Float, nullable=False)
    window_seconds: Mapped[int] = mapped_column(Integer, nullable=False)
    window_started_at: Mapped[datetime] = mapped_column(DateTime, nullable=True)
    ts: Mapped[int] = mapped_column(Integer, nullable=True)
    headline: Mapped[str] = mapped_column(String(300), nullable=False)
    source: Mapped[str] = mapped_column(String(64), nullable=True)
    url: Mapped[str] = mapped_column(String(500), nullable=True)
    summary: Mapped[str] = mapped_column(Text, nullable=True)
    tags: Mapped[str] = mapped_column(String(200), nullable=True)


class DailyBar(Base):
    """代理标的的历史日线，用来做长周期归因（当前用沪金连续 AU0）。"""

    __tablename__ = "daily_bars"
    __table_args__ = (UniqueConstraint("symbol", "trade_date", name="uq_bar_symbol_date"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    symbol: Mapped[str] = mapped_column(String(16), nullable=False, index=True)
    trade_date: Mapped[str] = mapped_column(String(10), nullable=False, index=True)
    open_price: Mapped[float] = mapped_column(Float, nullable=True)
    high_price: Mapped[float] = mapped_column(Float, nullable=True)
    low_price: Mapped[float] = mapped_column(Float, nullable=True)
    close_price: Mapped[float] = mapped_column(Float, nullable=False)
    source: Mapped[str] = mapped_column(String(32), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)


class NewsFlash(Base):
    """带标签的财经快讯归档，只保留能对上事件类型的条目。"""

    __tablename__ = "news_flashes"
    __table_args__ = (UniqueConstraint("source", "external_id", name="uq_flash_source_id"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    source: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    external_id: Mapped[str] = mapped_column(String(64), nullable=False)
    published_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, index=True)
    # 归属交易日：18:00 之后的快讯计入下一个交易日
    session_date: Mapped[str] = mapped_column(String(10), nullable=False, index=True)
    channel: Mapped[str] = mapped_column(String(32), nullable=True)
    title: Mapped[str] = mapped_column(String(300), nullable=False)
    tags: Mapped[str] = mapped_column(String(200), nullable=False)
    weight: Mapped[float] = mapped_column(Float, default=1.0)
    url: Mapped[str] = mapped_column(String(500), nullable=True)


class GoldLot(Base):
    __tablename__ = "gold_lots"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    grams: Mapped[float] = mapped_column(Float, nullable=False)
    buy_price: Mapped[float] = mapped_column(Float, nullable=False)
    bought_at: Mapped[str] = mapped_column(String(10), nullable=False, index=True)
    note: Mapped[str] = mapped_column(String(200), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
