"""第一期写死的 A 股池。要加自选只改这里。"""

from datetime import datetime
from typing import Dict, List, Optional, Tuple

from ..timeutil import now_local

# (新浪代码, 简称, 类型 index/etf/stock)
WATCHLIST: Tuple[tuple, ...] = (
    ("sh000001", "上证指数", "index"),
    ("sh000300", "沪深300", "index"),
    ("sz399006", "创业板指", "index"),
    ("sh510300", "沪深300ETF", "etf"),
    ("sh518880", "黄金ETF", "etf"),
    ("sh600519", "贵州茅台", "stock"),
    ("sh600036", "招商银行", "stock"),
    ("sh601318", "中国平安", "stock"),
    ("sz300750", "宁德时代", "stock"),
    ("sz002594", "比亚迪", "stock"),
    ("sh688981", "中芯国际", "stock"),
    ("sz000333", "美的集团", "stock"),
)


def all_codes() -> List[str]:
    return [row[0] for row in WATCHLIST]


def meta_of(code: str) -> Optional[Dict]:
    for ident, name, kind in WATCHLIST:
        if ident == code:
            return {"code": ident, "name": name, "kind": kind}
    return None


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
