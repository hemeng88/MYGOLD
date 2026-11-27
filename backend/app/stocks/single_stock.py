"""单只 A 股的按需行情与基于已完成日线的回踩计划。"""
from collections import OrderedDict
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, time as clock_time
import logging
import re
from statistics import mean
from threading import Lock
from time import monotonic

import httpx

from ..config import settings
from ..funds.sources import _HQ_LINE, fetch_market_trade_date, search_stocks
from ..market_session import session_label
from ..timeutil import now_local
from . import deepseek, factors, research, universe

logger = logging.getLogger(__name__)
_code = re.compile(r"(?:00[0-3]|30[01]|60[0135]|68[89]|92\d|[48]\d{2})\d{3}", re.ASCII)
_snapshots = OrderedDict()
_lock = Lock()
SNAPSHOT_TTL = 180


def _dated_quote(symbol):
    with httpx.Client(timeout=6, headers=universe.SINA_HEADERS) as client:
        response = client.get(settings.fund_stock_sina_url + symbol)
        response.raise_for_status()
    for match in _HQ_LINE.finditer(response.content.decode("gbk", errors="replace")):
        if match.group(1) != symbol:
            continue
        fields = match.group(2).split(",")
        if len(fields) < 32:
            continue
        try:
            at = datetime.strptime(fields[30] + " " + fields[31], "%Y-%m-%d %H:%M:%S")
        except ValueError:
            continue
        price = factors.number(fields[3])
        prev = factors.number(fields[2])
        volume = factors.number(fields[8])
        if fields[0] and price and price > 0:
            return {"name": fields[0], "price": price, "prev_close": prev,
                    "volume": volume, "at": at, "source": "新浪公开报价", "status": fields[32] if len(fields) > 32 else None}
    return None


def _raw_bars(symbol):
    return research.raw_history(symbol, count=90)


def _try(fetch, *args):
    try:
        return fetch(*args)
    except Exception:
        logger.warning("单股公开数据获取失败：%s", fetch.__name__)
        return None


def _pullback_plan(raw, daily, stats):
    """用未复权价格给出可读的价位，技术均线用复权比例换算。"""
    if len(raw) < 20 or not stats or raw[-1][0] != stats["as_of"]:
        return None
    adjusted = dict(daily)
    scale = raw[-1][1] / stats["last"]
    window = []
    for day, close, high, low in raw[-20:]:
        if day not in adjusted:
            return None
        basis = adjusted[day] * scale / close
        window.append((day, close * basis, high * basis, low * basis))
    atr = mean(max(high - low, abs(high - prev_close), abs(low - prev_close))
               for (_, prev_close, _, _), (_, _, high, low) in zip(window[-15:-1], window[-14:]))
    if not atr or atr < 0.01:
        return None
    center = raw[-1][1] * stats["ma20"] / stats["last"]
    low = round(center - .25 * atr, 2)
    high = round(center + .25 * atr, 2)
    stop = round(low - atr, 2)
    target = round(max(row[2] for row in window), 2)
    if not 0 < stop < low <= high < target:
        return None
    return {"entry_low": low, "entry_high": high, "target": target, "stop": stop,
            "reward_risk": (target - high) / (high - stop), "as_of": raw[-1][0],
            "method": "以20日均线和14日真实波幅计算回踩区间。近20日高点为卖出目标，跌破失效价为退出参考。价位已换算到最近收盘口径。"}


def _evaluate(moment, market_date, quote, raw, stats, plan, board, name, allowed_boards, low, high, financial):
    if universe.is_st(name):
        return "暂不买入", "股票有风险警示或退市整理标记。"
    if board not in allowed_boards:
        return "暂不买入", "该板块未加入你设置的参与范围。"
    if financial["status"] == "risk":
        return "暂不买入", "基本面检查未通过：" + "、".join(financial["reasons"]) + "。"
    if not plan:
        return "等待确认", "完整日线不足，或无法形成合理的买入区和卖出价。"
    if not stats or stats["ma20"] < stats["ma60"]:
        return "暂不买入", "20日均线低于60日均线，回踩计划的趋势条件未通过。"
    if plan["reward_risk"] < 1.5:
        return "暂不买入", "目标空间与风险的比值低于1.5。"
    if market_date != moment.date().isoformat() or session_label(moment) != "开盘中":
        return "等待确认", "当前不在可确认的交易时段，参考价位待下次开盘核实。"
    if not quote or not 0 <= (moment - quote["at"]).total_seconds() <= 300 or not (quote.get("volume") or 0) > 0 or quote.get("status") != "00":
        return "等待确认", "个股报价缺失、超过五分钟或无成交，需核实交易状态。"
    if not quote.get("prev_close") or abs(quote["prev_close"] / raw[-1][1] - 1) > .005:
        return "等待确认", "昨收与日线基准不一致，需核实除权或行情更新。"
    price = quote["price"]
    if price < low or (high is not None and price > high):
        return "暂不买入", "最新价超出你设置的股价范围。"
    if price <= plan["stop"]:
        return "暂不买入", "当前价已触及回踩计划的失效价。"
    if not plan["entry_low"] <= price <= plan["entry_high"]:
        return "等待确认", "当前价在买入区间之外，等待价格和趋势重新确认。"
    return "符合条件，可考虑买入", "已进入观察区，趋势与预设的收益风险条件均满足。"


def build_snapshot(code, allowed_boards, price_min, price_max):
    if not _code.fullmatch(code):
        raise LookupError("请输入有效的六位 A 股股票代码。")
    symbol, secid = universe.sina_symbol(code), universe.secid_of(code)
    with ThreadPoolExecutor(max_workers=5) as pool:
        raw_job = pool.submit(_try, _raw_bars, symbol)
        quote_job = pool.submit(_try, _dated_quote, symbol)
        market_job = pool.submit(_try, fetch_market_trade_date)
        daily_job = pool.submit(_try, research.history, symbol, None, True)
        finance_job = pool.submit(_try, factors.financial_rows, code)
        raw, quote, market_date, daily, financial_rows = (job.result() for job in (raw_job, quote_job, market_job, daily_job, finance_job))
    if not raw and not quote:
        raise LookupError("未找到该 A 股的有效行情，检查代码或稍后重试。")

    moment = now_local()
    # 只有确认当日已收盘时才纳入当天的日线。
    completed_today = market_date == moment.date().isoformat() and moment.time() >= clock_time(15, 30)
    today = moment.date().isoformat()
    raw = [row for row in raw or [] if row[0] < today or (completed_today and row[0] == today)]
    daily = [(day, close) for day, close in daily or [] if day < today or (completed_today and day == today)]
    stats = research.features(daily)
    financial = factors.fundamentals(financial_rows or [], moment.date())
    identity = quote or {}
    if not identity.get("name"):
        matches = _try(search_stocks, code) or []
        identity = next((row for row in matches if row["secid"] == secid), {})
    name = identity.get("name")
    if not name:
        raise LookupError("暂时无法核实这只股票的身份，请稍后重试。")
    board = universe.board_of(code)
    if quote and (quote["at"] > moment or quote["at"].date().isoformat() != market_date):
        quote = None
    last_day = raw[-1][0] if raw else None
    plan = _pullback_plan(raw, daily, stats)
    decision, reason = _evaluate(moment, market_date, quote, raw, stats, plan, board, name,
                                 allowed_boards, price_min, price_max, financial)
    # 若昨收与价位基准可能处于不同除权口径，不并列展示作当日计划。
    if plan and quote and not completed_today and quote.get("prev_close") and abs(quote["prev_close"] / raw[-1][1] - 1) > .005:
        plan = None
    price = quote["price"] if quote else raw[-1][1] if raw else None
    hits = research.triggers(stats)
    item = {"code": code, "symbol": symbol, "name": name, "board": board, "price": price,
            "quote_time": quote["at"].isoformat() if quote else None,
            "historical_as_of": stats["as_of"] if stats else None,
            "strategy_labels": [research.STRATEGIES[key]["label"] for key in hits],
            "priority_eligible": decision == "符合条件，可考虑买入",
            "factors": {"fundamentals": financial}}
    if stats:
        item.update(signal_close=stats["last"], ma20=round(stats["ma20"], 3), ma60=round(stats["ma60"], 3),
                    return5_pct=round(stats["return5"] * 100, 2), return10_pct=round(stats["return10"] * 100, 2),
                    vol20_pct=round(stats["vol20"] * 100, 2))
    single = {"code": code, "secid": secid, "name": name, "board": board, "price": price,
              "quote_at": item["quote_time"], "price_date": quote["at"].date().isoformat() if quote else last_day,
              "price_source": quote["source"] if quote else "腾讯未复权收盘价", "session": session_label(moment),
              "decision": decision, "decision_reason": reason, "plan": plan}
    snapshot = {"fetched_at": moment.isoformat(), "trade_date": market_date, "mode": "single", "complete": True,
                "items": [item], "single": single, "allowed_boards": allowed_boards,
                "price_min": price_min, "price_max": price_max}
    snapshot["snapshot_id"] = deepseek.snapshot_id(snapshot)
    return snapshot


def create_preview(user_id, code, boards, price_min, price_max):
    now = monotonic()
    with _lock:
        for (owner, _), (created, snapshot) in reversed(_snapshots.items()):
            if (owner == user_id and snapshot["single"]["code"] == code and now - created < 10
                    and (snapshot["allowed_boards"], snapshot["price_min"], snapshot["price_max"]) == (boards, price_min, price_max)):
                return snapshot
    snapshot = build_snapshot(code, boards, price_min, price_max)
    with _lock:
        _snapshots[user_id, snapshot["snapshot_id"]] = (monotonic(), snapshot)
        while len(_snapshots) > 128:
            _snapshots.popitem(last=False)
    return snapshot


def saved_preview(user_id, code, snapshot_id):
    with _lock:
        match = _snapshots.get((user_id, snapshot_id))
        if match and monotonic() - match[0] <= 900 and match[1]["single"]["code"] == code:
            return match[1]
    raise LookupError("这份行情已失效，请重新查询股票。")


def _current_review(snapshot, ai):
    # 只显示当前这份行情的点评，避免沿用其他价位的建议。
    if ai["status"] == "previous":
        ai.update(status="waiting", summary=None, items=[], error=ai.get("request_error"))
    elif ai["status"] in ("failed", "running") and ai.get("snapshot_id") != snapshot["snapshot_id"]:
        ai.update(status="waiting", summary=None, items=[], error=ai.get("request_error"))
    return ai


def view(snapshot, credentials, analyze=False, profiles=None, selected=()):
    if profiles is None:
        error = deepseek.request_analysis(snapshot, retry=True, credentials=credentials) if analyze else None
        ai = deepseek.analysis_state(snapshot, credentials)
        if error:
            ai.update(error=error, request_error=error)
        states = []
    else:
        states = [_current_review(snapshot, state) for state in
                  deepseek.profile_results(snapshot, profiles, selected, snapshot)]
        ai = next((state for state in states if state["configured"]), None) or deepseek.analysis_state(snapshot, credentials)
    ai = _current_review(snapshot, ai)
    issue = deepseek.snapshot_issue(snapshot)
    stock = dict(snapshot["single"])
    if issue and snapshot["items"][0].get("priority_eligible"):
        stock.update(decision="等待确认", decision_reason=issue)
    return {**stock, "snapshot_id": snapshot["snapshot_id"], "fetched_at": snapshot["fetched_at"],
            "allowed_boards": snapshot["allowed_boards"], "price_min": snapshot["price_min"], "price_max": snapshot["price_max"],
            "strategy_labels": snapshot["items"][0]["strategy_labels"], "can_analyze": not issue, "analysis_issue": issue,
            "ai": ai, "ai_results": states}
