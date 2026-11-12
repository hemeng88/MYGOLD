"""收盘播报使用的实时金价。

这里只恢复一项：浙商积存金人民币/克的当前价。黄金页面、曲线、持仓和事件分析均不恢复。
主源沿用原项目验证过的京东金业接口，GoldMonitor 只做兜底。
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any, Optional

import httpx

from .config import settings
from .timeutil import from_unix_millis, now_local

JD_HEADERS = {
    "Content-Type": "application/json",
    "Accept": "application/json, text/plain, */*",
    "Referer": "https://m.jdjygold.com/finance-gold/gold-standard/home/?productSku=1961543816",
    "User-Agent": (
        "Mozilla/5.0 (iPhone; CPU iPhone OS 18_5 like Mac OS X) "
        "AppleWebKit/605.1.15 (KHTML, like Gecko) Version/18.5 Mobile/15E148 Safari/604.1"
    ),
}


@dataclass(frozen=True)
class GoldQuote:
    price: float
    source: str
    source_time: datetime


def _number(value: Any) -> Optional[float]:
    try:
        if value is None or value == "":
            return None
        return float(str(value).replace(",", "").replace("%", "").strip())
    except (TypeError, ValueError):
        return None


async def _fetch_jd(client: httpx.AsyncClient) -> GoldQuote:
    response = await client.post(
        settings.gold_jd_latest_url,
        params={"productSku": settings.gold_jd_product_sku},
        json={"reqData": {"productSku": settings.gold_jd_product_sku}},
        headers=JD_HEADERS,
    )
    response.raise_for_status()
    data = (((response.json() or {}).get("resultData") or {}).get("datas")) or {}
    price = _number(data.get("price"))
    if price is None or price <= 0:
        raise ValueError("京东金业接口未返回有效金价")
    raw_time = data.get("time")
    source_time = from_unix_millis(int(raw_time)) if raw_time else now_local()
    return GoldQuote(price=price, source="京东金业", source_time=source_time)


async def _fetch_goldmonitor(client: httpx.AsyncClient) -> GoldQuote:
    response = await client.get(settings.gold_monitor_latest_url)
    response.raise_for_status()
    data = (response.json() or {}).get("data") or {}
    price = _number(data.get("price"))
    if price is None or price <= 0:
        raise ValueError("GoldMonitor 未返回有效金价")
    return GoldQuote(price=price, source="GoldMonitor", source_time=now_local())


async def fetch_gold_quote() -> GoldQuote:
    """返回浙商积存金实时价；主源失败后自动走兜底，两家都失败则抛异常。"""
    timeout = httpx.Timeout(settings.request_timeout_seconds)
    async with httpx.AsyncClient(timeout=timeout, follow_redirects=True) as client:
        try:
            return await _fetch_jd(client)
        except Exception:
            return await _fetch_goldmonitor(client)
