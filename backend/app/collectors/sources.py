import json
import re
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


SINA_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
    ),
    "Referer": "https://finance.sina.com.cn/futures/quotes/XAU.shtml",
}


def _sina_fields(text: str) -> Dict[str, List[str]]:
    found: Dict[str, List[str]] = {}
    for match in re.finditer(r'hq_str_([a-z0-9_]+)="([^"]*)"', text, re.I):
        found[match.group(1).lower()] = match.group(2).split(",")
    return found


def _parse_usdcny(parts: List[str]) -> Optional[Dict[str, Any]]:
    last = _parse_number(parts[1] if len(parts) > 1 else None)
    prev = _parse_number(parts[3] if len(parts) > 3 else None)
    if last is None or last < 5 or last > 12:
        return None
    change = round(last - prev, 4) if prev else None
    rate = round(change / prev * 100, 3) if change is not None and prev else None
    label = parts[9] if len(parts) > 9 else "人民币"
    return {
        "usdcny": last,
        "usdcny_prev": prev,
        "usdcny_change_amt": change,
        "usdcny_change_rate": rate,
        "usdcny_source": label,
    }


def fetch_london_gold() -> Optional[Dict[str, Any]]:
    """伦敦金（美元/盎司）和美元兑人民币。失败不影响积存金主价。"""
    try:
        with httpx.Client(timeout=settings.request_timeout_seconds, follow_redirects=True) as client:
            response = client.get(settings.london_gold_url, headers=SINA_HEADERS)
            response.raise_for_status()
        fields = _sina_fields(response.content.decode("gbk", errors="ignore"))
        out: Dict[str, Any] = {}
        xau = fields.get("hf_xau")
        if xau:
            last = _parse_number(xau[0] if xau else None)
            prev = _parse_number(xau[1] if len(xau) > 1 else None)
            if last is not None:
                change = round(last - prev, 2) if prev else None
                rate = round(change / prev * 100, 3) if change is not None and prev else None
                out.update(
                    {
                        "london_usd": last,
                        "london_prev": prev,
                        "london_change_amt": change,
                        "london_change_rate": rate,
                        "london_source": "sina_xau",
                    }
                )
        fx = _parse_usdcny(fields.get("fx_susdcny") or []) or _parse_usdcny(fields.get("fx_susdcnh") or [])
        if fx:
            out.update(fx)
        return out or None
    except Exception:
        return None


def gold_parity(zheshang_cny_g: Optional[float], london_usd: Optional[float], usdcny: Optional[float]) -> Dict[str, Any]:
    """1 金衡盎司 = 31.1034768 克。伦敦折人民币/克，浙商折美元/盎司。"""
    ounce = settings.troy_ounce_grams
    london_cny_g = None
    zheshang_usd_oz = None
    if london_usd and usdcny:
        london_cny_g = london_usd / ounce * usdcny
    if zheshang_cny_g and usdcny:
        zheshang_usd_oz = zheshang_cny_g * ounce / usdcny
    premium = None
    premium_pct = None
    if zheshang_cny_g and london_cny_g:
        premium = zheshang_cny_g - london_cny_g
        premium_pct = premium / london_cny_g * 100
    return {
        "troy_ounce_grams": ounce,
        "london_cny_gram": round(london_cny_g, 2) if london_cny_g is not None else None,
        "zheshang_usd_oz": round(zheshang_usd_oz, 2) if zheshang_usd_oz is not None else None,
        "premium_cny": round(premium, 2) if premium is not None else None,
        "premium_pct": round(premium_pct, 3) if premium_pct is not None else None,
    }
