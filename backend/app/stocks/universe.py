"""观察池：只留一手买得起的标的。指数留下看大盘，不占用买入预算。"""

from datetime import datetime
from typing import Dict, Iterable, List, Optional, Tuple

from ..config import settings
from ..timeutil import now_local

# (新浪代码, 简称, 类型 index/etf/stock)
WATCHLIST: Tuple[tuple, ...] = (
    ("sh000001", "上证指数", "index"),
    ("sh000300", "沪深300", "index"),
    ("sz399006", "创业板指", "index"),
    ("sh510300", "沪深300ETF", "etf"),
    ("sh518880", "黄金ETF", "etf"),
    ("sh600036", "招商银行", "stock"),
    ("sh601318", "中国平安", "stock"),
    ("sz000333", "美的集团", "stock"),
    ("sh601398", "工商银行", "stock"),
    ("sz000651", "格力电器", "stock"),
    ("sh600690", "海尔智家", "stock"),
    ("sh600900", "长江电力", "stock"),
    ("sz000002", "万科A", "stock"),
)


def all_codes() -> List[str]:
    return [row[0] for row in WATCHLIST]


def meta_of(code: str) -> Optional[Dict]:
    for ident, name, kind in WATCHLIST:
        if ident == code:
            return {"code": ident, "name": name, "kind": kind}
    return None


def lot_size(code: str) -> int:
    if code.startswith("sh688") or code.startswith("sz688"):
        return 200
    return 100


def lot_cost(price: Optional[float], code: str) -> Optional[float]:
    if price is None or price <= 0:
        return None
    return lot_size(code) * price


def within_budget(price: Optional[float], code: str, kind: str, budget: Optional[float] = None) -> bool:
    if kind == "index":
        return True
    cap = settings.stock_budget_yuan if budget is None else budget
    cost = lot_cost(price, code)
    if cost is None:
        return True
    return cost <= cap


def active_watchlist(quotes: Optional[Iterable] = None, budget: Optional[float] = None) -> List[tuple]:
    """一手超过预算的个股/ETF 直接不采、不展示。"""
    prices = {}
    if quotes is not None:
        for row in quotes:
            prices[row.code] = row.price
    return [row for row in WATCHLIST if within_budget(prices.get(row[0]), row[0], row[2], budget)]


def session_label(moment: Optional[datetime] = None) -> str:
    now = moment or now_local()
    if now.weekday() >= 5:
        return "周末休市"
    clock = now.hour * 60 + now.minute
    if 9 * 60 + 15 <= clock < 9 * 60 + 30:
        return "集合竞价"
    if 9 * 60 + 30 <= clock < 11 * 60 + 30:
        return "开盘中"
    if 11 * 60 + 30 <= clock < 13 * 60:
        return "午休"
    if 13 * 60 <= clock < 15 * 60:
        return "开盘中"
    if clock < 9 * 60 + 15:
        return "未开盘"
    return "已收盘"


def should_poll_quotes(moment: Optional[datetime] = None) -> bool:
    """开盘附近才刷实时价：9:15–11:35、12:55–15:10。"""
    now = moment or now_local()
    if now.weekday() >= 5:
        return False
    clock = now.hour * 60 + now.minute
    return (9 * 60 + 15 <= clock <= 11 * 60 + 35) or (12 * 60 + 55 <= clock <= 15 * 60 + 10)
