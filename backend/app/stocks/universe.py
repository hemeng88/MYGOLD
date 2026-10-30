"""主板样本的口径和外部行情。

新开普通账户一般只能买沪深主板。全市场三千多只算三月均价会把行情源打爆，
所以样本取沪深300里的主板非 ST：流动性够、你大概率买得了。
"""

from __future__ import annotations

import logging
from typing import Dict, Iterable, List, Optional, Sequence, Tuple

import httpx

from ..config import settings
from ..funds.sources import SINA_HEADERS, _num, _stock_secid, fetch_stock_quotes

logger = logging.getLogger("mygold.stocks")

KLINE_BARS = 66
# 近一年约 244 个交易日，多拉一点留给停牌和节假日
KLINE_FETCH = 260

# 周期 → 交易日根数；ytd 按自然年切，不按根数
PERIOD_BARS = {"1m": 22, "3m": 66, "6m": 122, "1y": 244}
PERIODS = [
    ("1m", "近1月"),
    ("3m", "近3月"),
    ("6m", "近6月"),
    ("ytd", "今年来"),
    ("1y", "近1年"),
]
PERIOD_LABELS = dict(PERIODS)
DEFAULT_PERIOD = "3m"

INDEXES = [
    ("sh000001", "上证指数"),
    ("sz399001", "深证成指"),
    ("sh000300", "沪深300"),
]
# 日线停在十天前的，多半是合并、退市或代码作废，不当成可买样本
STALE_DAYS = 10

SINA_NODE_COUNT_URL = (
    "https://vip.stock.finance.sina.com.cn/quotes_service/api/json_v2.php/"
    "Market_Center.getHQNodeStockCount"
)
SINA_NODE_DATA_URL = (
    "https://vip.stock.finance.sina.com.cn/quotes_service/api/json_v2.php/"
    "Market_Center.getHQNodeData"
)


def board_of(code: str) -> str:
    text = str(code or "").strip()
    if text.startswith(("300", "301")):
        return "创业板"
    if text.startswith(("688", "689")):
        return "科创板"
    if text.startswith(("8", "4", "92", "83", "87", "82")):
        return "北交所"
    return "主板"


def is_st(name: str) -> bool:
    text = (name or "").upper()
    return "ST" in text or text.startswith("*") or "退" in (name or "")


def sina_symbol(code: str) -> Optional[str]:
    secid = _stock_secid(code)
    if not secid:
        return None
    market, _, stock_code = secid.partition(".")
    if market == "1":
        return "sh" + stock_code
    if market == "0":
        return "sz" + stock_code
    return None


def secid_of(code: str) -> Optional[str]:
    return _stock_secid(code)


def classify(code: str, name: str) -> Tuple[str, bool, Optional[str]]:
    """返回 (板块, 新户是否可买, 拦截原因)。"""
    board = board_of(code)
    if board != "主板":
        return board, False, board
    if is_st(name):
        return board, False, "ST"
    return board, True, None


def window_avg(closes: Sequence[float], bars: int = KLINE_BARS) -> Optional[float]:
    values = [float(item) for item in closes if item is not None]
    if len(values) < 20:
        return None
    picked = values[-bars:]
    return sum(picked) / len(picked)


def vs_avg_pct(price: Optional[float], avg: Optional[float]) -> Optional[float]:
    if price is None or avg is None or avg <= 0:
        return None
    return round((price / avg - 1) * 100, 2)


def lot_cost(price: Optional[float]) -> Optional[float]:
    if price is None or price <= 0:
        return None
    return round(price * 100, 2)


def _get_json(url: str, params: Optional[dict] = None, timeout: Optional[float] = None):
    with httpx.Client(timeout=timeout or settings.request_timeout_seconds, follow_redirects=True) as client:
        response = client.get(url, params=params, headers=SINA_HEADERS)
        response.raise_for_status()
        return response.json()


def fetch_node_count(node: str) -> int:
    raw = _get_json(SINA_NODE_COUNT_URL, {"node": node})
    return int(raw)


def fetch_board_counts() -> Dict[str, int]:
    sh_a = fetch_node_count("sh_a")
    sz_a = fetch_node_count("sz_a")
    cyb = fetch_node_count("cyb")
    kcb = fetch_node_count("kcb")
    hs_a = fetch_node_count("hs_a")
    return {
        "hs_a": hs_a,
        "sh_a": sh_a,
        "sz_a": sz_a,
        "cyb": cyb,
        "kcb": kcb,
        "main_est": (sh_a - kcb) + (sz_a - cyb),
    }


def fetch_hs300() -> List[Dict]:
    out: List[Dict] = []
    for page in range(1, 5):
        rows = _get_json(
            SINA_NODE_DATA_URL,
            {"page": page, "num": 80, "sort": "symbol", "asc": 1, "node": "hs300"},
        ) or []
        out.extend(rows)
    seen = set()
    unique: List[Dict] = []
    for row in out:
        code = str(row.get("code") or "").strip()
        if len(code) != 6 or not code.isdigit() or code in seen:
            continue
        seen.add(code)
        unique.append(
            {
                "code": code,
                "name": str(row.get("name") or "").strip() or code,
                "symbol": str(row.get("symbol") or sina_symbol(code) or ""),
                "trade": _num(row.get("trade")),
            }
        )
    return unique


def _closes_sina(symbol: str) -> List[Tuple[str, float]]:
    rows = _get_json(
        settings.fund_kline_sina_url,
        {"symbol": symbol, "scale": 240, "ma": "no", "datalen": KLINE_FETCH},
    ) or []
    out: List[Tuple[str, float]] = []
    for row in rows:
        day = str(row.get("day") or "")[:10]
        close = _num(row.get("close"))
        if day and close and close > 0:
            out.append((day, close))
    return out


def _closes_tencent(symbol: str) -> List[Tuple[str, float]]:
    with httpx.Client(timeout=settings.request_timeout_seconds, follow_redirects=True) as client:
        response = client.get(
            settings.fund_kline_tencent_url,
            params={"param": "%s,day,,,%d,qfq" % (symbol, KLINE_FETCH)},
            headers={"User-Agent": SINA_HEADERS["User-Agent"], "Referer": "https://gu.qq.com/"},
        )
        response.raise_for_status()
    block = ((response.json() or {}).get("data") or {}).get(symbol) or {}
    bars = block.get("qfqday") or block.get("day") or []
    out: List[Tuple[str, float]] = []
    for bar in bars:
        if not bar:
            continue
        day = str(bar[0])[:10]
        close = _num(bar[2] if len(bar) > 2 else None)
        if day and close and close > 0:
            out.append((day, close))
    return out


def fetch_daily_closes(symbol: str) -> List[Tuple[str, float]]:
    """前复权日线收盘价，新浪优先，腾讯兜底。"""
    for loader in (_closes_sina, _closes_tencent):
        try:
            bars = loader(symbol)
        except Exception:
            logger.warning("%s 取 %s 日线失败", loader.__name__, symbol)
            continue
        if len(bars) >= 20:
            return bars
    return []


def fetch_index_closes(symbol: str) -> List[Tuple[str, float]]:
    """指数日线腾讯优先：新浪盘中没有当天那根，和个股接上的现价对不齐。"""
    for loader in (_closes_tencent, _closes_sina):
        try:
            bars = loader(symbol)
        except Exception:
            logger.warning("%s 取指数 %s 日线失败", loader.__name__, symbol)
            continue
        if len(bars) >= 20:
            return bars
    return []


def period_window(bars: Sequence[Tuple[str, float]], period: str) -> List[Tuple[str, float]]:
    rows = list(bars)
    if not rows:
        return []
    if period == "ytd":
        start = rows[-1][0][:4] + "-01-01"
        return [item for item in rows if item[0] >= start]
    return rows[-PERIOD_BARS.get(period, KLINE_BARS):]


def _min_bars(period: str) -> int:
    # 凑不够八成根数就不出数，免得上市不满半年的票拿短窗口冒充「近1年」；
    # 今年来在一月初可能只有几根，单独放宽
    if period == "ytd":
        return 3
    return int(PERIOD_BARS.get(period, KLINE_BARS) * 0.8)


def period_stats(bars: Sequence[Tuple[str, float]], period: str) -> Optional[Dict]:
    window = period_window(bars, period)
    if len(window) < _min_bars(period):
        return None
    closes = [item[1] for item in window]
    return {
        "avg": round(sum(closes) / len(closes), 3),
        "high": max(closes),
        "low": min(closes),
        "first": closes[0],
        "bars": len(window),
        "start": window[0][0],
        "end": window[-1][0],
    }


def all_period_stats(bars: Sequence[Tuple[str, float]]) -> Dict[str, Dict]:
    out: Dict[str, Dict] = {}
    for key, _label in PERIODS:
        stats = period_stats(bars, key)
        if stats is not None:
            out[key] = stats
    return out


def summarize_klines(bars: Sequence[Tuple[str, float]], trade_date: Optional[str] = None) -> Optional[Dict]:
    if len(bars) < 20:
        return None
    window = list(bars[-KLINE_BARS:])
    avg = window_avg([item[1] for item in window])
    if avg is None:
        return None
    last = window[-1][1]
    end = window[-1][0]
    if trade_date and end < trade_date and _days_between(end, trade_date) > STALE_DAYS:
        return None
    return {
        "last": last,
        "avg3m": round(avg, 3),
        "bars": len(window),
        "vs_avg_pct": vs_avg_pct(last, avg),
        "window_start": window[0][0],
        "window_end": end,
        "lot_cost": lot_cost(last),
        "periods": all_period_stats(bars),
        "closes": [[day, close] for day, close in bars],
    }


def _days_between(start: str, end: str) -> int:
    try:
        from datetime import date

        a = date.fromisoformat(start)
        b = date.fromisoformat(end)
        return abs((b - a).days)
    except ValueError:
        return 0


def quote_map(secids: Iterable[str]) -> Dict[str, Dict]:
    return {item["secid"]: item for item in fetch_stock_quotes(secids)}
