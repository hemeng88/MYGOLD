import json
from typing import Any, Dict, List, Optional, Tuple

import httpx

from ..config import settings
from ..timeutil import from_unix_millis, now_local, trade_date_of, to_unix_seconds


JD_HEADERS = {
    "Content-Type": "application/json",
    "Accept": "application/json, text/plain, */*",
    "Referer": "https://m.jdjygold.com/finance-gold/gold-standard/home/?productSku=1961543816",
    "User-Agent": (
        "Mozilla/5.0 (iPhone; CPU iPhone OS 18_5 like Mac OS X) "
        "AppleWebKit/605.1.15 (KHTML, like Gecko) Version/18.5 Mobile/15E148 Safari/604.1"
    ),
}


class Quote:
    def __init__(
        self,
        price,
        source,
        yesterday_price=None,
        change_amt=None,
        change_rate=None,
        source_time=None,
        raw=None,
    ):
        self.price = float(price)
        self.source = source
        self.yesterday_price = float(yesterday_price) if yesterday_price is not None else None
        self.change_amt = float(change_amt) if change_amt is not None else None
        self.change_rate = str(change_rate) if change_rate is not None else None
        self.source_time = source_time
        self.collected_at = now_local()
        self.raw = raw or {}

    @property
    def trade_date(self) -> str:
        dt = self.source_time or self.collected_at
        return trade_date_of(dt)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "price": self.price,
            "yesterday_price": self.yesterday_price,
            "change_amt": self.change_amt,
            "change_rate": self.change_rate,
            "source_time": self.source_time,
            "collected_at": self.collected_at,
            "source": self.source,
            "trade_date": self.trade_date,
        }


def _parse_number(value: Any) -> Optional[float]:
    if value is None or value == "":
        return None
    if isinstance(value, str):
        value = value.replace("%", "").replace("+", "").strip()
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


async def fetch_jd_latest(client: httpx.AsyncClient) -> Quote:
    url = settings.jd_latest_url
    payload = {"reqData": {"productSku": settings.jd_product_sku}}
    response = await client.post(
        url,
        params={"productSku": settings.jd_product_sku},
        json=payload,
        headers=JD_HEADERS,
    )
    response.raise_for_status()
    body = response.json()
    datas = ((body.get("resultData") or {}).get("datas")) or {}
    if not datas.get("price"):
        raise ValueError("浙商接口未返回价格: %s" % json.dumps(body, ensure_ascii=False)[:400])

    source_time = None
    raw_time = datas.get("time")
    if raw_time is not None:
        source_time = from_unix_millis(int(raw_time))

    change_amt = _parse_number(datas.get("upAndDownAmt"))
    yesterday = _parse_number(datas.get("yesterdayPrice"))
    return Quote(
        price=datas["price"],
        source="jd",
        yesterday_price=yesterday,
        change_amt=change_amt,
        change_rate=datas.get("upAndDownRate"),
        source_time=source_time,
        raw=body,
    )


async def fetch_goldmonitor_latest(client: httpx.AsyncClient) -> Quote:
    response = await client.get(settings.goldmonitor_latest_url)
    response.raise_for_status()
    body = response.json()
    data = body.get("data") or {}
    if data.get("price") is None:
        raise ValueError("GoldMonitor 未返回价格")
    return Quote(
        price=data["price"],
        source="goldmonitor",
        yesterday_price=_parse_number(data.get("prev_close")),
        change_amt=_parse_number(data.get("change")),
        change_rate=("%s%%" % data["change_pct"]) if data.get("change_pct") is not None else None,
        source_time=now_local(),
        raw=body,
    )


async def fetch_latest_quote(client: httpx.AsyncClient) -> Quote:
    try:
        return await fetch_jd_latest(client)
    except Exception:
        return await fetch_goldmonitor_latest(client)


async def fetch_today_chart(client: httpx.AsyncClient) -> List[Tuple[int, float]]:
    response = await client.get(settings.goldmonitor_chart_url)
    response.raise_for_status()
    body = response.json()
    points = body.get("data") or []
    result = []
    for item in points:
        ts = item.get("t")
        price = item.get("p")
        if ts is None or price is None:
            continue
        result.append((int(ts), float(price)))
    return result


async def fetch_latest_as_point(quote: Quote) -> Tuple[int, float]:
    dt = quote.source_time or quote.collected_at
    return to_unix_seconds(dt), quote.price
