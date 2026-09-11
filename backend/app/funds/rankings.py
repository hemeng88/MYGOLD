"""涨幅榜 + 穿透看方向。

只看基金名字猜不出方向（「供给改革」「产业机遇」这种名字什么都不说明），
所以把榜单前几名的季报重仓拉出来汇总一遍，被反复重仓的股票才是真正的主线。

榜单基于 T-1 净值，一天变一次，所以走每日定时任务写库，页面只读库。
穿透要按基金逐个请求，几个周期加起来请求不少，因此先把各周期榜单的基金代码
去重成一个集合，每只只拉一次持仓，再按周期分别汇总。
"""

from __future__ import annotations

import logging
from typing import Dict, List, Optional

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from ..config import settings
from ..models import FundRankEntry, FundRankStock
from ..timeutil import now_local
from . import sources
from .sources import RANK_PERIODS

logger = logging.getLogger("mygold.funds")

DEFAULT_PERIOD = "jnzf"


def period_options() -> List[Dict]:
    return [{"key": key, "label": label} for key, (label, _index) in RANK_PERIODS.items()]


def period_label(period: str) -> Optional[str]:
    entry = RANK_PERIODS.get(period)
    return entry[0] if entry else None


def collect_rankings(db: Session, periods: Optional[List[str]] = None) -> Dict:
    wanted = [p for p in (periods or list(RANK_PERIODS)) if p in RANK_PERIODS]
    if not wanted:
        return {"ok": False, "periods": 0, "funds": 0, "message": "没有可用的周期"}

    boards: Dict[str, List[Dict]] = {}
    failed: List[str] = []
    for period in wanted:
        try:
            boards[period] = sources.fetch_rankings(period, limit=settings.fund_rank_top_n)
        except Exception:
            logger.exception("拉 %s 涨幅榜失败", period)
            failed.append(period_label(period) or period)

    # 各周期榜单高度重叠，持仓按代码去重只拉一次
    codes = sorted({row["code"] for rows in boards.values() for row in rows})
    holdings: Dict[str, List[Dict]] = {}
    for code in codes:
        try:
            holdings[code] = sources.fetch_holdings(code)["holdings"]
        except Exception:
            logger.exception("穿透 %s 持仓失败", code)
            holdings[code] = []

    now = now_local()
    total_funds = 0
    for period, rows in boards.items():
        db.execute(delete(FundRankEntry).where(FundRankEntry.period == period))
        db.execute(delete(FundRankStock).where(FundRankStock.period == period))
        for row in rows:
            db.add(
                FundRankEntry(
                    period=period,
                    rank=row["rank"],
                    code=row["code"],
                    name=row["name"],
                    return_pct=row["return_pct"],
                    nav=row.get("nav"),
                    nav_date=row.get("nav_date"),
                    updated_at=now,
                )
            )
            total_funds += 1
        agg: Dict[str, Dict] = {}
        for row in rows:
            for item in holdings.get(row["code"]) or []:
                slot = agg.setdefault(
                    item["stock_code"],
                    {
                        "stock_name": item.get("stock_name"),
                        "secid": item.get("secid"),
                        "fund_count": 0,
                        "weight_sum": 0.0,
                    },
                )
                slot["fund_count"] += 1
                slot["weight_sum"] += item["weight_pct"]
        for stock_code, slot in agg.items():
            db.add(
                FundRankStock(
                    period=period,
                    stock_code=stock_code,
                    stock_name=slot["stock_name"],
                    secid=slot["secid"],
                    fund_count=slot["fund_count"],
                    weight_sum=round(slot["weight_sum"], 2),
                    updated_at=now,
                )
            )
    db.commit()

    message = "涨幅榜 %d 个周期、%d 条记录，穿透 %d 只基金" % (len(boards), total_funds, len(codes))
    if failed:
        message += "，%s 没取到" % "、".join(failed)
    return {"ok": total_funds > 0, "periods": len(boards), "funds": total_funds, "message": message}


def list_rankings(db: Session, period: str = DEFAULT_PERIOD, stock_limit: int = 12) -> Dict:
    if period not in RANK_PERIODS:
        period = DEFAULT_PERIOD
    funds = list(
        db.scalars(
            select(FundRankEntry)
            .where(FundRankEntry.period == period)
            .order_by(FundRankEntry.rank.asc())
        ).all()
    )
    stocks = list(
        db.scalars(
            select(FundRankStock)
            .where(FundRankStock.period == period)
            .order_by(FundRankStock.fund_count.desc(), FundRankStock.weight_sum.desc())
            .limit(stock_limit)
        ).all()
    )
    return {
        "period": period,
        "period_label": period_label(period),
        "periods": period_options(),
        "as_of": max((row.updated_at for row in funds), default=None),
        "funds": [
            {
                "rank": row.rank,
                "code": row.code,
                "name": row.name,
                "return_pct": row.return_pct,
                "nav": row.nav,
                "nav_date": row.nav_date,
            }
            for row in funds
        ],
        "hot_stocks": [
            {
                "code": row.stock_code,
                "name": row.stock_name,
                "fund_count": row.fund_count,
                "weight_sum": row.weight_sum,
            }
            for row in stocks
        ],
        "message": None if funds else "还没有榜单数据，刷新一次",
    }
