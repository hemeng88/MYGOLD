"""涨幅榜 + 穿透看方向。

只看基金名字猜不出方向（「供给改革」「产业机遇」这种名字什么都不说明），
所以把榜单前几名的季报重仓拉出来汇总一遍，被反复重仓的股票才是真正的主线。

榜单基于 T-1 净值，一天变一次，所以走每日定时任务写库，页面只读库。
穿透要按基金逐个请求，几个周期加起来请求不少，因此先把各周期榜单的基金代码
去重成一个集合，每只只拉一次持仓，再按周期分别汇总。
"""

from __future__ import annotations

import logging
import re
from typing import Dict, List, Optional

from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from ..config import settings
from ..models import FundRankEntry, FundRankStock, FundStockQuote, FundThemeHolder, FundHolding
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
    report_dates: List[str] = []
    for code in codes:
        try:
            parsed = sources.fetch_holdings(code)
            holdings[code] = parsed["holdings"]
            if parsed.get("report_date"):
                report_dates.append(parsed["report_date"])
        except Exception:
            logger.exception("穿透 %s 持仓失败", code)
            holdings[code] = []

    # 反查接口按报告期过滤，填错会直接返回 0 条，所以用榜单基金里最新的那个报告期
    report_date = max(report_dates) if report_dates else None

    now = now_local()
    total_funds = 0
    theme: Dict[str, List] = {}
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

        # 挑出这条主线的代表股，交给下面的全市场反查
        theme[period] = sorted(
            agg.items(), key=lambda kv: (-kv[1]["fund_count"], -kv[1]["weight_sum"])
        )[: settings.fund_theme_stock_n]
    db.commit()

    holder_result = _collect_theme_holders(db, theme, report_date, now)

    message = "涨幅榜 %d 个周期、%d 条记录，穿透 %d 只基金" % (len(boards), total_funds, len(codes))
    message += "；%s" % holder_result
    if failed:
        message += "，%s 没取到" % "、".join(failed)
    return {"ok": total_funds > 0, "periods": len(boards), "funds": total_funds, "message": message}


_CLASS_SUFFIX = re.compile(r"(?:[（(](?:LOF|QDII|FOF)[）)])*\s*[ABCDEHIOR]$")


def _merge_key(name: Optional[str], code: str) -> str:
    """按「去掉尾部份额字母的名字」归并同门份额（A/C 类）。

    实测这个反查接口每个组合只报一条（药明康德 800 条里归并不出任何一组同门份额，
    中欧医疗健康只出现 003095 A 类），所以这里基本不会触发。
    留着是防止接口哪天改成按份额逐条返回，那时「前五」会被同门份额挤占。
    """
    base = _CLASS_SUFFIX.sub("", (name or code).strip())
    return base or code


def _collect_theme_holders(
    db: Session, theme: Dict[str, List], report_date: Optional[str], now
) -> str:
    """全市场反查：谁把最多净值压在这条主线的代表股上。

    和之前两版的区别是比较范围。之前只能在「因为押中主线而上榜」的那些基金里比，
    是循环论证；反查按股票问「全市场哪些基金持有它」，主线仍由涨幅榜识别，
    候选基金则来自全市场。得分直接是占净值比例之和，能验算也能横向比。
    """
    db.execute(delete(FundThemeHolder))
    if not report_date:
        db.commit()
        return "反查跳过：拿不到报告期"

    # 各周期主线股高度重叠，按股票去重只反查一次
    wanted = sorted({code for rows in theme.values() for code, _slot in rows})
    holders_by_stock: Dict[str, List[Dict]] = {}
    failed = 0
    for stock_code in wanted:
        try:
            holders_by_stock[stock_code] = sources.fetch_stock_fund_holders(stock_code, report_date)
        except Exception:
            logger.exception("反查 %s 的持有基金失败", stock_code)
            holders_by_stock[stock_code] = []
            failed += 1

    written = 0
    for period, rows in theme.items():
        consensus = {code: slot["fund_count"] for code, slot in rows}
        merged: Dict[str, Dict] = {}
        for stock_code, _slot in rows:
            for item in holders_by_stock.get(stock_code) or []:
                key = _merge_key(item["fund_name"], item["fund_code"])
                slot = merged.setdefault(
                    key,
                    {
                        "fund_code": item["fund_code"],
                        "fund_name": item["fund_name"],
                        "fund_type": item.get("fund_type"),
                        "theme_pct": 0.0,
                        "hit": set(),
                        "alt": set(),
                        # 命中股票被多少只榜单基金重仓，用来看押的是不是最抱团的那几只
                        "consensus_hits": 0,
                    },
                )
                if item["fund_code"] != slot["fund_code"]:
                    # 同门份额：留代码小的当代表，其余记进 alt
                    if item["fund_code"] < slot["fund_code"]:
                        slot["alt"].add(slot["fund_code"])
                        slot["fund_code"] = item["fund_code"]
                        slot["fund_name"] = item["fund_name"]
                    else:
                        slot["alt"].add(item["fund_code"])
                        continue
                if stock_code in slot["hit"]:
                    continue
                slot["hit"].add(stock_code)
                slot["theme_pct"] += item["netvalue_ratio"]
                slot["consensus_hits"] += consensus.get(stock_code, 0)
        ranked = sorted(merged.values(), key=lambda row: (-row["theme_pct"], -len(row["hit"])))
        for index, row in enumerate(ranked[: settings.fund_theme_holder_top_n], start=1):
            db.add(
                FundThemeHolder(
                    period=period,
                    rank=index,
                    fund_code=row["fund_code"],
                    fund_name=row["fund_name"],
                    fund_type=row["fund_type"],
                    theme_pct=round(row["theme_pct"], 2),
                    hit_count=len(row["hit"]),
                    theme_stock_count=len(rows),
                    consensus_hits=row["consensus_hits"],
                    alt_codes=",".join(sorted(row["alt"])) or None,
                    report_date=report_date,
                    updated_at=now,
                )
            )
            written += 1
    db.commit()
    note = "反查 %d 只主线股（%s），写入 %d 条持有榜" % (len(wanted), report_date, written)
    if failed:
        note += "，%d 只没查到" % failed
    return note


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
            select(FundThemeHolder)
            .where(FundThemeHolder.period == period)
            .order_by(FundThemeHolder.rank.asc())
            .limit(holder_limit)
        ).all()
    )

    # 重仓基金来自全市场反查，不一定是当前账号收藏的基金，不能复用
    # list_funds() 的用户持仓结果；这里直接按季报重仓 × 当前报价计算日内估值。
    holder_codes = {row.fund_code for row in holders}
    estimate_by_code: Dict[str, Optional[float]] = {}
    if holder_codes:
        holding_rows = list(
            db.scalars(select(FundHolding).where(FundHolding.fund_code.in_(holder_codes))).all()
        )
        secids = {row.secid for row in holding_rows}
        quotes = {
            row.secid: row
            for row in db.scalars(select(FundStockQuote).where(FundStockQuote.secid.in_(secids))).all()
        } if secids else {}
        for code in holder_codes:
            fund_rows = [row for row in holding_rows if row.fund_code == code]
            covered = sum(
                row.weight_pct
                for row in fund_rows
                if row.secid in quotes and quotes[row.secid].change_pct is not None
            )
            contribution = sum(
                row.weight_pct / 100.0 * quotes[row.secid].change_pct
                for row in fund_rows
                if row.secid in quotes and quotes[row.secid].change_pct is not None
            )
            estimate_by_code[code] = (
                round(contribution / (covered / 100.0), 3)
                if covered >= settings.fund_min_coverage_pct
                else None
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
        # 持有榜的比较范围是全市场，这里给出这条主线用了几只代表股
        "theme_stock_n": holders[0].theme_stock_count if holders else 0,
        "holder_report_date": holders[0].report_date if holders else None,
        "top_holders": [
            {
                "rank": row.rank,
                "code": row.fund_code,
                "name": row.fund_name,
                "fund_type": row.fund_type,
                "theme_pct": row.theme_pct,
                "hit_count": row.hit_count,
                "theme_stock_count": row.theme_stock_count,
                "consensus_hits": row.consensus_hits,
                "alt_codes": [c for c in (row.alt_codes or "").split(",") if c],
                "estimate_pct": estimate_by_code.get(row.fund_code),
            }
            for row in holders
        ],
        "message": None if funds else "还没有榜单数据，刷新一次",
    }
