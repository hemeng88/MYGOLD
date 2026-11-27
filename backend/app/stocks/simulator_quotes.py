"""新浪公开快照。用于模拟的时间、方向和可见数量均取自同一条报价。"""
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
import logging

import httpx

from ..config import settings
from ..funds.sources import SINA_HEADERS, _HQ_LINE

logger = logging.getLogger(__name__)
BENCHMARK = "sh000300"


def cents(number):
    return int((Decimal(str(number)) * 100).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


@dataclass(frozen=True)
class Quote:
    name: str
    at: datetime
    last: int
    bid: int
    bid_size: int
    ask: int
    ask_size: int
    volume: int
    status: str


def _parse(symbol, payload):
    fields = payload.split(",")
    if len(fields) < 32 or not fields[0]:
        return None
    try:
        at = datetime.strptime(fields[30] + " " + fields[31], "%Y-%m-%d %H:%M:%S")
        last = cents(fields[3])
        volume = int(Decimal(fields[8]))
        if symbol == BENCHMARK:
            return Quote(fields[0], at, last, 0, 0, 0, 0, volume, "00") if last > 0 and volume > 0 else None
        if len(fields) < 33 or last <= 0:
            return None
        return Quote(fields[0], at, last, cents(fields[11]), int(Decimal(fields[10])),
                     cents(fields[21]), int(Decimal(fields[20])), volume, fields[32])
    except (ValueError, InvalidOperation, OverflowError):
        return None


def fetch(symbols):
    result = {}
    wanted = sorted(set(symbols))
    with httpx.Client(timeout=5, headers=SINA_HEADERS) as client:
        for index in range(0, len(wanted), 60):
            batch = wanted[index:index + 60]
            try:
                response = client.get(settings.fund_stock_sina_url + ",".join(batch))
                response.raise_for_status()
            except httpx.HTTPError:
                logger.warning("模拟盘新浪行情请求失败，涉及 %d 个标的", len(batch))
                continue
            for symbol, payload in _HQ_LINE.findall(response.content.decode("gbk", errors="replace")):
                quote = _parse(symbol, payload) if symbol in batch else None
                if quote:
                    result[symbol] = quote
    return result
