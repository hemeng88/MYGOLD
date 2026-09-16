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
from ..models import FundRankEntry, FundRankHolder, FundRankStock
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
    names = {row["code"]: row["name"] for rows in boards.values() for row in rows}
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
        db.execute(delete(FundRankHolder).where(FundRankHolder.period == period))
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

        # 反过来按基金聚合：谁把最多仓位压在这个周期的前十大重仓股上。
        # 比较范围是所有周期榜首基金的并集（去重后就是上面拉过持仓的那些），
        # 不是全市场 —— 全市场要另一套「个股被哪些基金持有」的数据。
        hot = sorted(
            agg.items(),
            key=lambda kv: (-kv[1]["fund_count"], -kv[1]["weight_sum"]),
        )[: settings.fund_rank_hot_top_n]
        hot_codes = {code for code, _ in hot}
        holders = []
        # A 类和 C 类是同一个组合的两种份额，持仓一模一样。不合并的话「前五」里
        # 会有一半是同门份额，白占名次。用持仓指纹判断，代码小的那只留下当代表。
        by_portfolio: Dict[tuple, Dict] = {}
        for code in codes:
            items = holdings.get(code) or []
            if not items:
                continue
            hit = [item for item in items if item["stock_code"] in hot_codes]
            if not hit:
                continue
            signature = tuple(sorted((item["stock_code"], round(item["weight_pct"], 2)) for item in items))
            twin = by_portfolio.get(signature)
            if twin is not None:
                twin["alt"].append(code)
                continue
            row = {
                "fund_code": code,
                "hit_weight": round(sum(item["weight_pct"] for item in hit), 2),
                "hit_count": len(hit),
                "disclosed_pct": round(sum(item["weight_pct"] for item in items), 2),
                "alt": [],
            }
            by_portfolio[signature] = row
            holders.append(row)
        holders.sort(key=lambda row: (-row["hit_weight"], -row["hit_count"]))
        for index, row in enumerate(holders[: settings.fund_rank_holder_top_n], start=1):
            db.add(
                FundRankHolder(
                    period=period,
                    rank=index,
                    fund_code=row["fund_code"],
                    fund_name=names.get(row["fund_code"]),
                    hit_weight=row["hit_weight"],
                    hit_count=row["hit_count"],
                    disclosed_pct=row["disclosed_pct"],
                    alt_codes=",".join(row["alt"]) or None,
                    updated_at=now,
                )
            )
    db.commit()

    message = "涨幅榜 %d 个周期、%d 条记录，穿透 %d 只基金" % (len(boards), total_funds, len(codes))
    if failed:
        message += "，%s 没取到" % "、".join(failed)
    return {"ok": total_funds > 0, "periods": len(boards), "funds": total_funds, "message": message}


def list_rankings(
    db: Session, period: str = DEFAULT_PERIOD, stock_limit: int = 12, holder_limit: int = 5
) -> Dict:
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
    holders = list(
        db.scalars(
            select(FundRankHolder)
            .where(FundRankHolder.period == period)
            .order_by(FundRankHolder.rank.asc())
            .limit(holder_limit)
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
        "hot_top_n": settings.fund_rank_hot_top_n,
        # 参与比较的是所有周期榜首基金的并集，去重后就是采集时拉过持仓的那些
        "holder_universe": len(set(db.scalars(select(FundRankEntry.code).distinct()).all())),
        "top_holders": [
            {
                "rank": row.rank,
                "code": row.fund_code,
                "name": row.fund_name,
                "hit_weight": row.hit_weight,
                "hit_count": row.hit_count,
                "disclosed_pct": row.disclosed_pct,
                "alt_codes": [c for c in (row.alt_codes or "").split(",") if c],
            }
            for row in holders
        ],
        "message": None if funds else "还没有榜单数据，刷新一次",
    }
