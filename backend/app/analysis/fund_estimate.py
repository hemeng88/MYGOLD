"""基金实时估值：公示仓位比例 × 持仓股当前涨跌幅。

季报只公示前十大重仓（指数基金会多给几只），所以永远只能覆盖一部分净值。
这里同时给两个数：
  * conservative_pct —— 没公示的那部分当成不动，是净值涨跌的下限口径
  * estimate_pct     —— 把公示部分的加权涨幅当成全仓表现，也就是市面上「估算涨跌」的算法
covered_pct 一起返回，覆盖度低的时候前端要提醒这个数只能当参考。
"""

from __future__ import annotations

from datetime import datetime
from typing import Dict, List, Optional

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..config import settings
from ..funds.favorites import get_favorite, list_favorites
from ..funds.sources import market_label, report_label
from ..models import FundFavorite, FundHolding, FundNav, FundStockQuote
from ..market_session import session_label
from ..timeutil import now_local


def _is_cash_fund(favorite: FundFavorite) -> bool:
    """货币基金：单位净值恒为 1.0000，收益以份额结转。

    净值接口对这类基金的 NAV 字段返回的是「万份收益」（例如 0.2486），
    直接当单位净值去乘份额会算出巨额假亏损，所以要单独认出来。
    """
    text = "%s %s" % (favorite.fund_type or "", favorite.name or "")
    return "货币" in text


def _stale_days(report_date: Optional[str], today: datetime) -> Optional[int]:
    if not report_date:
        return None
    try:
        parsed = datetime.strptime(report_date, "%Y-%m-%d")
    except ValueError:
        return None
    return (today.date() - parsed.date()).days


def _confidence(covered_pct: float, stale: bool) -> str:
    if stale:
        return "low"
    if covered_pct >= 80:
        return "high"
    if covered_pct >= 50:
        return "medium"
    return "low"


def _position(
    shares: Optional[float],
    cost_price: Optional[float],
    nav: Optional[float],
    estimate_nav: Optional[float],
) -> Dict:
    """把估算净值换算成具体的盈亏金额。没填份额就全是 None。"""
    out = {
        "shares": shares,
        "cost_price": cost_price,
        "cost": None,
        "nav_value": None,
        "estimate_value": None,
        "today_pnl": None,
        "total_pnl": None,
        "total_pnl_pct": None,
    }
    if not shares or shares <= 0:
        return out
    if cost_price is not None and cost_price > 0:
        out["cost"] = round(shares * cost_price, 2)
    if nav:
        out["nav_value"] = round(shares * nav, 2)
    if estimate_nav:
        out["estimate_value"] = round(shares * estimate_nav, 2)
    # 今日估算盈亏：估算净值和最近一次公布净值的差
    if estimate_nav and nav:
        out["today_pnl"] = round(shares * (estimate_nav - nav), 2)
    # 累计盈亏优先按估算净值算，估不出来就退回已公布净值
    basis = estimate_nav or nav
    if basis and out["cost"]:
        out["total_pnl"] = round(shares * basis - out["cost"], 2)
        out["total_pnl_pct"] = round(out["total_pnl"] / out["cost"] * 100, 3)
    return out


def _holding_row(holding: FundHolding, quote: Optional[FundStockQuote]) -> Dict:
    change_pct = quote.change_pct if quote else None
    return {
        "secid": holding.secid,
        "code": holding.stock_code,
        "name": holding.stock_name or (quote.name if quote else None) or holding.stock_code,
        "market": market_label(holding.market),
        "weight_pct": round(holding.weight_pct, 2),
        "rank": holding.rank,
        "price": quote.price if quote else None,
        "change_pct": change_pct,
        # 这只股票给基金净值贡献了多少个百分点
        "contrib_pct": round(holding.weight_pct / 100.0 * change_pct, 4) if change_pct is not None else None,
        "quoted": change_pct is not None,
    }


def summarize_fund(
    favorite: FundFavorite,
    holdings: List[FundHolding],
    quotes: Dict[str, FundStockQuote],
    nav: Optional[FundNav],
    today: Optional[datetime] = None,
) -> Dict:
    moment = today or now_local()
    raw_nav = nav.nav if nav else None
    cash_fund = _is_cash_fund(favorite)
    # 货币基金按 1.0000 计净值，接口给的那个数是万份收益，只用来展示
    nav_value = 1.0 if cash_fund else raw_nav
    base = {
        "code": favorite.code,
        "name": favorite.name,
        "fund_type": favorite.fund_type,
        "nav": nav_value,
        "nav_date": nav.nav_date if nav else None,
        "nav_chg_pct": nav.nav_chg_pct if nav else None,
        "is_cash_fund": cash_fund,
        "yield_10k": raw_nav if cash_fund else None,
        # 估不出净值时也先给一份按已公布净值算的盈亏，下面拿到估算净值再覆盖
        **_position(favorite.shares, favorite.cost_price, nav_value, None),
        "holdings_count": len(holdings),
        "quoted_count": 0,
        "disclosed_pct": None,
        "covered_pct": None,
        "estimate_pct": None,
        "conservative_pct": None,
        "estimate_nav": None,
        "report_date": None,
        "report_label": None,
        "report_age_days": None,
        "stale": False,
        "confidence": "low",
        "lead_name": None,
        "lead_contrib_pct": None,
        "drag_name": None,
        "drag_contrib_pct": None,
        "as_of": None,
        "ready": False,
        "message": None,
    }
    if not holdings:
        base["message"] = (
            "货币基金按 1.0000 净值算，收益以份额结转，不做穿透估算"
            if cash_fund
            else "还没有公示持仓，刷新一次或换只基金试试"
        )
        return base

    ordered = sorted(holdings, key=lambda row: (row.rank or 999, -(row.weight_pct or 0)))
    rows = [_holding_row(row, quotes.get(row.secid)) for row in ordered]
    report_date = next((row.report_date for row in ordered if row.report_date), None)
    age = _stale_days(report_date, moment)
    stale = age is not None and age > settings.fund_report_stale_days

    disclosed = sum(row["weight_pct"] for row in rows)
    priced = [row for row in rows if row["quoted"]]
    covered = sum(row["weight_pct"] for row in priced)
    contrib = sum(row["contrib_pct"] for row in priced)

    stamps = [quotes[row.secid].collected_at for row in ordered if row.secid in quotes]
    base.update(
        {
            "holdings_count": len(rows),
            "quoted_count": len(priced),
            "disclosed_pct": round(disclosed, 2),
            "covered_pct": round(covered, 2),
            "report_date": report_date,
            "report_label": report_label(report_date),
            "report_age_days": age,
            "stale": stale,
            "as_of": max(stamps) if stamps else None,
            "holdings": rows,
        }
    )

    if not priced or covered <= 0:
        base["message"] = "持仓股还没有报价，刷新一次"
        return base
    if covered < settings.fund_min_coverage_pct:
        # 债券基金之类只公示一点点股票，按覆盖度放大出来的数会离谱到没法看
        base["conservative_pct"] = round(contrib, 3)
        base["message"] = "只公示了 %.1f%% 的股票仓位，穿透估不出净值涨跌" % covered
        return base

    conservative = round(contrib, 3)
    estimate = round(contrib / (covered / 100.0), 3)
    estimate_nav = round(nav_value * (1 + estimate / 100.0), 4) if nav_value else None
    lead = max(priced, key=lambda row: row["contrib_pct"])
    drag = min(priced, key=lambda row: row["contrib_pct"])
    base.update(
        {
            "ready": True,
            "conservative_pct": conservative,
            "estimate_pct": estimate,
            "estimate_nav": estimate_nav,
            # 有了估算净值再算一遍盈亏，这时才有今日估算这一项
            **_position(favorite.shares, favorite.cost_price, nav_value, estimate_nav),
            "confidence": _confidence(covered, stale),
            "lead_name": lead["name"] if lead["contrib_pct"] > 0 else None,
            "lead_contrib_pct": lead["contrib_pct"] if lead["contrib_pct"] > 0 else None,
            "drag_name": drag["name"] if drag["contrib_pct"] < 0 else None,
            "drag_contrib_pct": drag["contrib_pct"] if drag["contrib_pct"] < 0 else None,
        }
    )
    notes = []
    if stale:
        notes.append("持仓还是 %s 的老报告，估算只能当个参考" % (base["report_label"] or report_date))
    elif covered < 50:
        notes.append("只覆盖了 %.0f%% 的净值，剩下的仓位看不到" % covered)
    if len(priced) < len(rows):
        notes.append("%d 只持仓股没取到报价" % (len(rows) - len(priced)))
    base["message"] = "；".join(notes) or None
    return base


def exposure(db: Session, user_id: int) -> Dict:
    """把基金持仓穿透成「你实际持有多少钱的某只股票」。

    份额 × 净值 = 这只基金值多少钱，再按季报公示的占净值比例摊到每只股票上，
    同一只股票被多只基金持有时合并 —— 这才是重点：分散买几只基金，
    穿透后往往发现钱集中压在同一批股票上。

    分摊基数用**已公布净值**而不是估算净值，这样每只股票的今日盈亏
    （金额 × 该股涨跌幅）加起来正好等于各基金「保守估算」口径的今日盈亏，
    数字可以自己验算。用估算净值会把估算误差再乘一遍。
    """
    favorites = [row for row in list_favorites(db, user_id) if row.shares and row.shares > 0]
    codes = [row.code for row in favorites]
    holdings, quotes, navs = _load(db, codes)
    moment = now_local()

    total_value = 0.0
    disclosed_value = 0.0
    merged: Dict[str, Dict] = {}
    stale_funds: List[str] = []
    no_nav: List[str] = []

    for favorite in favorites:
        nav_row = navs.get(favorite.code)
        cash_fund = _is_cash_fund(favorite)
        nav_value = 1.0 if cash_fund else (nav_row.nav if nav_row else None)
        if not nav_value:
            no_nav.append(favorite.name)
            continue
        fund_value = favorite.shares * nav_value
        total_value += fund_value
        rows = holdings.get(favorite.code) or []
        report_date = next((row.report_date for row in rows if row.report_date), None)
        age = _stale_days(report_date, moment)
        if age is not None and age > settings.fund_report_stale_days:
            stale_funds.append(favorite.name)
        for row in rows:
            stock_value = fund_value * row.weight_pct / 100.0
            disclosed_value += stock_value
            quote = quotes.get(row.secid)
            slot = merged.setdefault(
                row.secid,
                {
                    "code": row.stock_code,
                    "name": row.stock_name or (quote.name if quote else None) or row.stock_code,
                    "market": market_label(row.market),
                    "value": 0.0,
                    "change_pct": quote.change_pct if quote else None,
                    "funds": [],
                },
            )
            slot["value"] += stock_value
            slot["funds"].append(
                {
                    "code": favorite.code,
                    "name": favorite.name,
                    "weight_pct": round(row.weight_pct, 2),
                    "value": round(stock_value, 2),
                }
            )

    items = []
    for slot in merged.values():
        change_pct = slot["change_pct"]
        items.append(
            {
                "code": slot["code"],
                "name": slot["name"],
                "market": slot["market"],
                "value": round(slot["value"], 2),
                "pct_of_total": round(slot["value"] / total_value * 100, 2) if total_value else None,
                "change_pct": change_pct,
                # 今天这只股票给你带来多少钱
                "today_pnl": round(slot["value"] * change_pct / 100.0, 2)
                if change_pct is not None
                else None,
                "fund_count": len(slot["funds"]),
                "funds": sorted(slot["funds"], key=lambda row: -row["value"]),
            }
        )
    items.sort(key=lambda row: -row["value"])

    notes = []
    if no_nav:
        notes.append("%d 只取不到净值，没算进去" % len(no_nav))
    if stale_funds:
        notes.append("%d 只的季报已过期，穿透结果只能当参考" % len(stale_funds))
    return {
        "session": session_label(moment),
        "as_of": max((row.collected_at for row in quotes.values()), default=None),
        "fund_count": len(favorites),
        "total_value": round(total_value, 2) if total_value else None,
        "disclosed_value": round(disclosed_value, 2) if disclosed_value else None,
        # 能穿透到个股的占总市值多少，剩下的是未公示仓位加债券现金
        "coverage_pct": round(disclosed_value / total_value * 100, 2) if total_value else None,
        "today_pnl": round(sum(row["today_pnl"] or 0 for row in items), 2) if items else None,
        "stock_count": len(items),
        "items": items,
        "ready": bool(items),
        "message": "；".join(notes) or (None if items else "没有填了份额、又能拿到公示持仓的基金"),
    }


def _load(db: Session, codes: List[str]):
    holdings: Dict[str, List[FundHolding]] = {code: [] for code in codes}
    if codes:
        for row in db.scalars(select(FundHolding).where(FundHolding.fund_code.in_(codes))).all():
            holdings.setdefault(row.fund_code, []).append(row)
    secids = {row.secid for rows in holdings.values() for row in rows}
    quotes: Dict[str, FundStockQuote] = {}
    if secids:
        quotes = {
            row.secid: row
            for row in db.scalars(
                select(FundStockQuote).where(FundStockQuote.secid.in_(list(secids)))
            ).all()
        }
    navs: Dict[str, FundNav] = {}
    if codes:
        navs = {
            row.code: row for row in db.scalars(select(FundNav).where(FundNav.code.in_(codes))).all()
        }
    return holdings, quotes, navs


def list_funds(db: Session, user_id: int) -> Dict:
    favorites = list_favorites(db, user_id)
    codes = [row.code for row in favorites]
    holdings, quotes, navs = _load(db, codes)
    moment = now_local()
    items = []
    for favorite in favorites:
        summary = summarize_fund(
            favorite, holdings.get(favorite.code) or [], quotes, navs.get(favorite.code), moment
        )
        # 列表页不带逐只持仓，详情页才给
        summary.pop("holdings", None)
        items.append(summary)
    return {"session": session_label(moment), "items": items}


def fund_detail(db: Session, user_id: int, code: str) -> Dict:
    favorite = get_favorite(db, user_id, code)
    if not favorite:
        return {"ready": False, "message": "这只基金还没收藏", "session": session_label()}
    holdings, quotes, navs = _load(db, [code])
    summary = summarize_fund(favorite, holdings.get(code) or [], quotes, navs.get(code), now_local())
    rows = summary.pop("holdings", [])
    return {
        "ready": summary["ready"],
        "message": summary["message"],
        "session": session_label(),
        "fund": summary,
        "holdings": rows,
    }
