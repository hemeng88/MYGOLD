"""A 股交易时段判断。

原来放在 stocks/universe.py 里，那个包随观察池功能一起删掉了，
但基金估值要用 session_label 显示时段、基金持仓股报价要用 should_poll_quotes
控制只在盘中拉数据，所以单独提出来。
"""

from datetime import datetime
from typing import Optional

from .timeutil import now_local


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
