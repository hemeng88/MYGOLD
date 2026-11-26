"""全 A 股快照扫描。公开行情适配器，规则候选不等同于已验证的交易策略。"""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
import math
import threading
import time

from ..funds.sources import _num, fetch_market_trade_date
from ..market_session import session_label, should_poll_quotes
from ..timeutil import now_local
from . import universe
from . import deepseek

RULES = [
    "范围：沪深 A 股及北交所；剔除 ST、退市标记、停牌或缺失关键报价的证券。",
    "观察条件：成交额不少于 1 亿元，涨幅 0.5%～5%，换手率 1%～15%。",
    "现价不低于当日成交均价，且高于当日开盘价；按涨幅降序展示前 20 只。",
    "价格参考：成交均价至现价为回踩观察区，当日高点为突破参考，当日低点为失效参考。",
    "规则尚未回测；价格不含手续费、滑点或次日跳空，失效价不能保证止损成交。",
]
_lock = threading.Lock()
_executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="ashare-scan")
_last_attempt = 0.0
_state = {"running": False, "fetched_at": None, "trade_date": None, "scanned": 0,
          "expected": 0, "complete": False, "items": [], "errors": [], "progress": 0,
          "boards": {}, "matched": 0}


def _number(value):
    number = _num(value)
    return number if number is not None and math.isfinite(number) else None


def candidate(row):
    """纯函数：源字段 amount 为元，volume 为股，均价量纲为元/股。"""
    code, name = str(row.get("code") or ""), str(row.get("name") or "")
    symbol = str(row.get("symbol") or "")
    if len(code) != 6 or not code.isdigit() or not name or universe.is_st(name):
        return None
    if not symbol.startswith(("sh6", "sz0", "sz3", "bj")):
        return None
    fields = {key: _number(row.get(key)) for key in
              ("trade", "open", "high", "low", "amount", "volume", "changepercent", "turnoverratio")}
    if any(value is None for value in fields.values()):
        return None
    price, opening, high, low = (fields[k] for k in ("trade", "open", "high", "low"))
    amount, volume = fields["amount"], fields["volume"]
    change, turnover = fields["changepercent"], fields["turnoverratio"]
    if min(price, opening, high, low, volume) <= 0 or not low <= opening <= high or not low <= price <= high:
        return None
    if amount < 100_000_000 or not 0.5 <= change <= 5 or not 1 <= turnover <= 15:
        return None
    average = amount / volume
    if not low <= average <= price or price <= opening:
        return None
    return {"code": code, "name": name, "board": universe.board_of(code), "price": price,
            "change_pct": change, "amount": amount, "turnover_pct": turnover,
            "watch_low": round(average, 2), "watch_high": price,
            "breakout_price": high, "invalidation_price": low,
            "quote_time": str(row.get("ticktime") or "") or None,
            "reason": "成交额充足、温和上涨，现价高于开盘价且不低于当日成交均价",
            "status": "观察候选"}


def scan_market(get_json=None, count_loader=None, progress=None):
    get_json = get_json or universe._get_json
    count_loader = count_loader or universe.fetch_node_count
    by_symbol, errors, expected = {}, [], 0
    started = time.monotonic()
    # 已实测 hs_a 同时返回 sh / sz / bj，统一分页避免重复和遗漏。
    for node, label in (("hs_a", "全 A 股"),):
        try:
            count = count_loader(node)
            if count <= 0 or count > 10000:
                raise ValueError("市场名单数量无效")
            expected += count
            node_seen = set()
            for page in range(1, math.ceil(count / 80) + 1):
                if time.monotonic() - started > 180:
                    raise TimeoutError("扫描超过三分钟，本轮停止")
                rows = get_json(universe.SINA_NODE_DATA_URL, {
                    "node": node, "page": page, "num": 80, "sort": "symbol", "asc": 1,
                })
                if not isinstance(rows, list) or not rows:
                    raise ValueError("名单分页为空或格式错误")
                for row in rows:
                    symbol = str(row.get("symbol") or "")
                    if symbol:
                        by_symbol[symbol] = row
                        node_seen.add(symbol)
                if progress:
                    progress(len(by_symbol))
            if len(node_seen) < count:
                raise ValueError("分页仅取得 %d / %d 只" % (len(node_seen), count))
        except Exception as exc:
            errors.append("%s：%s" % (label, exc))
    boards = {}
    for row in by_symbol.values():
        board = universe.board_of(str(row.get("code") or ""))
        boards[board] = boards.get(board, 0) + 1
    items = [result for row in by_symbol.values() if (result := candidate(row)) is not None]
    items.sort(key=lambda item: (-item["change_pct"], item["code"]))
    # 日期来自交易日接口，并非单只证券的报价时间戳，前端明确区分。
    try:
        trade_date = fetch_market_trade_date()
    except Exception:
        trade_date = None
    return {"fetched_at": now_local().isoformat(), "trade_date": trade_date,
            "scanned": len(by_symbol), "expected": expected, "progress": len(by_symbol),
            "complete": not errors, "errors": errors, "boards": boards,
            "matched": len(items), "items": items[:20]}


def _run():
    def progress(value):
        with _lock:
            _state["progress"] = value
    try:
        result = scan_market(progress=progress)
        with _lock:
            _state.update(result)
    except Exception as exc:
        with _lock:
            _state.update(errors=["扫描失败：%s" % exc], complete=False)
    finally:
        with _lock:
            _state["running"] = False
            snapshot = deepcopy(_state)
        deepseek.request_analysis(snapshot)


def get_signals(refresh=False, analyze=False):
    global _last_attempt
    with _lock:
        elapsed = time.monotonic() - _last_attempt
        due = not _last_attempt or (elapsed >= 300 and should_poll_quotes())
        # 共享任务：多账号、多标签页不会重复拉取全市场。
        if not _state["running"] and (due or (refresh and elapsed >= 60)):
            _last_attempt = time.monotonic()
            _state.update(running=True, progress=0)
            _executor.submit(_run)
        result = deepcopy(_state)
    moment = now_local()
    result.update(session=session_label(moment), source="新浪公开行情",
                  engine="公开规则扫描 v1（未接入券商或 AI）", rules=RULES,
                  refresh_seconds=300, stale=True)
    if result["fetched_at"]:
        from datetime import datetime
        result["stale"] = (moment - datetime.fromisoformat(result["fetched_at"])).total_seconds() > 600
    result["market_date_current"] = result["trade_date"] == moment.date().isoformat()
    if analyze:
        deepseek.request_analysis(result, retry=True)
    result["ai"] = deepseek.analysis_state(result)
    result["engine"] = "公开规则扫描 v1 · DeepSeek 候选点评" if result["ai"]["configured"] else "公开规则扫描 v1（DeepSeek 未配置）"
    return result
