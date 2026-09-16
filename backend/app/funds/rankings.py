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

from sqlalchemy import delete, func, select
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

        # 反过来按基金聚合：谁的仓位最集中在这条主线上。
        #
        # 不用「主线成分股集合 + 落在集合里就计入」那种算法：集合一放大就会覆盖
        # 榜单基金持有的几乎所有股票，命中权重恒等于披露仓位，榜就退化成
        # 「谁满仓程度最高」。这里改成给每只股票一个共识度权重：
        #     共识度 = 该周期有多少只榜单基金重仓它 / 榜单基金总数
        #     主线得分 = Σ(该基金在这只股票上的权重 × 这只股票的共识度)
        # 全榜数据都参与，没有人为截断；抱团股贡献大，个性选股贡献小。
        board_total = len(rows) or 1
        consensus = {code: slot["fund_count"] / board_total for code, slot in agg.items()}
        holders = []
        # A 类和 C 类是同一个组合的两种份额，持仓一模一样。不合并的话「前五」里
        # 会有一半是同门份额，白占名次。用持仓指纹判断，代码小的那只留下当代表。
        by_portfolio: Dict[tuple, Dict] = {}
        for code in codes:
            items = holdings.get(code) or []
            if not items:
                continue
            score = sum(item["weight_pct"] * consensus.get(item["stock_code"], 0.0) for item in items)
            if score <= 0:
                continue
            disclosed = sum(item["weight_pct"] for item in items)
            shared = [item for item in items if consensus.get(item["stock_code"], 0.0) > 1 / board_total]
            signature = tuple(sorted((item["stock_code"], round(item["weight_pct"], 2)) for item in items))
            twin = by_portfolio.get(signature)
            if twin is not None:
                twin["alt"].append(code)
                continue
            row = {
                "fund_code": code,
                "theme_score": round(score, 2),
                # 持仓里有多少只是和别的榜单基金抱团的
                "shared_count": len(shared),
                "holding_count": len(items),
                "disclosed_pct": round(disclosed, 2),
                # 得分占自身披露仓位的比例，衡量这个组合有多「随大流」
                "consensus_pct": round(score / disclosed * 100, 1) if disclosed else 0.0,
                "alt": [],
            }
            by_portfolio[signature] = row
            holders.append(row)
        holders.sort(key=lambda row: (-row["theme_score"], -row["consensus_pct"]))
        for index, row in enumerate(holders[: settings.fund_rank_holder_top_n], start=1):
            db.add(
                FundRankHolder(
                    period=period,
                    rank=index,
                    fund_code=row["fund_code"],
                    fund_name=names.get(row["fund_code"]),
                    theme_score=row["theme_score"],
                    consensus_pct=row["consensus_pct"],
                    shared_count=row["shared_count"],
                    holding_count=row["holding_count"],
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
    db: Session,
    period: str = DEFAULT_PERIOD,
    stock_limit: int = 12,
    holder_limit: int = 5,
    fund_limit: int = 10,
) -> Dict:
    if period not in RANK_PERIODS:
        period = DEFAULT_PERIOD
    # 采集深度比展示深度大：计算用全部榜单基金，页面只列前几名
    board_size = (
        db.scalar(select(func.count()).select_from(FundRankEntry).where(FundRankEntry.period == period)) or 0
    )
    funds = list(
        db.scalars(
            select(FundRankEntry)
            .where(FundRankEntry.period == period)
            .order_by(FundRankEntry.rank.asc())
            .limit(fund_limit)
        ).all()
    )
    # 抱团股数量：被两只以上榜单基金共同重仓的，用来说明这条主线有多集中
    theme_stock_count = (
        db.scalar(
            select(func.count())
            .select_from(FundRankStock)
            .where(FundRankStock.period == period, FundRankStock.fund_count >= 2)
        )
        or 0
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
        "board_size": board_size,
        # 主线成分股数量，以及判定门槛：至少几只榜单基金共同重仓
        "theme_stock_count": theme_stock_count,
        "theme_min_funds": settings.fund_rank_theme_min_funds,
        # 参与比较的是所有周期榜单基金的并集，去重后就是采集时拉过持仓的那些
        "holder_universe": len(set(db.scalars(select(FundRankEntry.code).distinct()).all())),
        "top_holders": [
            {
                "rank": row.rank,
                "code": row.fund_code,
                "name": row.fund_name,
                "theme_score": row.theme_score,
                "consensus_pct": row.consensus_pct,
                "shared_count": row.shared_count,
                "holding_count": row.holding_count,
                "disclosed_pct": row.disclosed_pct,
                "alt_codes": [c for c in (row.alt_codes or "").split(",") if c],
            }
            for row in holders
        ],
        "message": None if funds else "还没有榜单数据，刷新一次",
    }
