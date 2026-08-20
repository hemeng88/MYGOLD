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
