"""全 A 股快照扫描。公开行情适配器，规则候选不等同于已验证的交易策略。"""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
import math
import json
import threading
import time
from datetime import time as clock_time, timedelta
from sqlalchemy import select

from ..funds.sources import _num, fetch_market_trade_date
from ..market_session import session_label, should_poll_quotes
from ..timeutil import now_local
from . import universe
from . import deepseek
from . import research, paper, factors, watchlists, learning
from ..database import SessionLocal
from ..models import StockResearchPreference, StockCloseWatchlist
from .preferences import normalize_boards, price_range, scope_key, parse_scope

RULES = [
    "范围：沪深 A 股及北交所；剔除 ST、退市标记、停牌或缺失关键报价的证券。",
    "不再用固定涨幅、换手率或一亿元门槛筛候选；先保留关键行情有效、有成交的股票。",
    "各板块按成交额分档，在每档内分散抽取日线样本，再检验趋势延续、趋势回调和低波动。",
    "按策略与成交档位轮换分配最多20个展示位置，重复股票只展示一次。",
    "技术候选再检查已披露财报、行业当日相对强弱和大盘环境；缺数据、基本面未过或行业/大盘偏弱时禁止AI标为优先观察。",
    "价格参考：成交均价至现价为回踩观察区，当日高点为突破参考，当日低点为失效参考。",
    "历史验证为当前样本事件研究，存在样本选择偏差；前向跟踪尚需积累，失效参考价不保证成交。",
]
_lock = threading.Lock()
_executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="ashare-scan")
_last_attempt = 0.0
_state = {"running": False, "fetched_at": None, "trade_date": None, "scanned": 0,
          "expected": 0, "complete": False, "items": [], "errors": [], "progress": 0,
          "boards": {}, "matched": 0}
_states = {}
_attempts = {}
_market_cache = {}


class SnapshotChanged(ValueError):
    pass


def _scope(boards, mode="intraday", price_min=0, price_max=None):
    if boards == ["主板"] and mode == "intraday" and not price_min and price_max is None:
        return _state
    key = (mode, scope_key(boards, price_min, price_max)) if price_min or price_max is not None else tuple(boards) if mode == "intraday" else (mode, *boards)
    if key not in _states:
        _states[key] = {"running": False, "fetched_at": None, "trade_date": None, "scanned": 0,
                        "expected": 0, "complete": False, "items": [], "errors": [], "progress": 0,
                        "boards": {}, "matched": 0}
    return _states[key]


def _number(value):
    number = _num(value)
    return number if number is not None and math.isfinite(number) else None


def _attach_history(snapshot):
    try:
        with SessionLocal() as db:
            watchlists.attach_history(db, snapshot)
    except Exception:
        snapshot["history_context"] = {"status": "unavailable", "archive_days": 0, "dates": [],
                                       "note": "历史收盘归档读取失败；本轮AI不得推断连续入选或历史价格变化。"}


def queue_close_archives():
    return queue_scans("close")


def queue_scans(mode="intraday", bootstrap=False):
    moment = now_local()
    if mode == "close":
        if moment.weekday() >= 5 or moment.time() < clock_time(15, 30):
            return 0
    elif not bootstrap and not should_poll_quotes():
        return 0
    with SessionLocal() as db:
        scopes = {scope_key(["主板"], 0, 50)}
        for row in db.scalars(select(StockResearchPreference)).all():
            try:
                scopes.add(scope_key(normalize_boards(json.loads(row.boards_json)), row.price_min, row.price_max))
            except (ValueError, TypeError):
                continue
        done = {row.scope for row in db.scalars(select(StockCloseWatchlist)).all()
                if row.trade_date == moment.date().isoformat()} if mode == "close" else set()
    queued = 0
    with _lock:
        for scope in sorted(scopes):
            if scope in done:
                continue
            boards, low, high = parse_scope(scope)
            state = _scope(boards, mode, low, high)
            key = (mode, scope)
            if state["running"] or (mode == "intraday" and time.monotonic() - _attempts.get(key, 0) < 120):
                continue
            state.update(running=True, progress=0, allowed_boards=boards)
            _attempts[key] = time.monotonic()
            _executor.submit(_run, boards, mode, low, high)
            queued += 1
    return queued


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
    if amount <= 0 or turnover < 0:
        return None
    average = amount / volume
    if not low <= average <= high:
        return None
    return {"code": code, "symbol": symbol, "name": name, "board": universe.board_of(code), "price": price,
            "open": opening, "high": high, "low": low, "volume": volume,
            "change_pct": change, "amount": amount, "turnover_pct": turnover,
            "watch_low": round(min(average, price), 2), "watch_high": round(max(average, price), 2),
            "breakout_price": high, "invalidation_price": low,
            "quote_time": str(row.get("ticktime") or "") or None,
            "reason": "成交额充足、温和上涨，现价高于开盘价且不低于当日成交均价",
            "status": "观察候选"}


def scan_market(get_json=None, count_loader=None, progress=None, research_builder=None, allowed_boards=None, mode="intraday", price_min=0, price_max=None):
    use_cache = get_json is None and count_loader is None
    get_json = get_json or universe._get_json
    count_loader = count_loader or universe.fetch_node_count
    by_symbol, errors, expected = {}, [], 0
    started = time.monotonic()
    cached = use_cache and _market_cache and time.monotonic() - _market_cache["at"] < 120
    if cached:
        by_symbol = deepcopy(_market_cache["rows"])
        expected = _market_cache["expected"]
        if progress:
            progress(len(by_symbol))
    else:
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
        if use_cache and not errors:
            _market_cache.update(at=time.monotonic(), rows=deepcopy(by_symbol), expected=expected,
                                 fetched_at=now_local().isoformat())
    boards = {}
    for row in by_symbol.values():
        board = universe.board_of(str(row.get("code") or ""))
        boards[board] = boards.get(board, 0) + 1
    selected_boards = normalize_boards(allowed_boards)
    market_items = [result for row in by_symbol.values() if (result := candidate(row)) is not None]
    price_min, price_max = price_range(price_min, price_max)
    items = [row for row in market_items if row["board"] in selected_boards and row["price"] >= price_min
             and (price_max is None or row["price"] <= price_max)]
    # 日期来自交易日接口，并非单只证券的报价时间戳，前端明确区分。
    try:
        trade_date = fetch_market_trade_date()
    except Exception:
        trade_date = None
    fetched_at = _market_cache["fetched_at"] if use_cache and not errors and _market_cache else now_local().isoformat()
    builder = research_builder or research.build_research
    if research_builder is None:
        scope = scope_key(selected_boards, price_min, price_max)
        moment = now_local()
        closing = mode == "close" and moment.time() >= clock_time(15, 30)
        cutoff = (moment.date() + timedelta(days=int(closing))).isoformat()
        try:
            with SessionLocal() as db:
                extras = paper.pending_symbols(db, boards=selected_boards)
                extras = list(set(extras) | set(learning.pending_symbols(db, scope, cutoff)))
        except Exception:
            extras = []
        options = {"mode": mode} if mode == "close" else {}
        evaluation = learning.load_evaluation(scope)
        if evaluation and evaluation.get("active"):
            options["parameters"] = evaluation["parameters"]
        selected, report, histories = builder(items, trade_date, extra_symbols=extras, **options)
    else:
        selected, report, histories = builder(items, trade_date)
    result = {"fetched_at": fetched_at, "trade_date": trade_date,
            "scanned": len(by_symbol), "expected": expected, "progress": len(by_symbol),
            "complete": not errors, "errors": errors, "boards": boards,
            "eligible": len(items), "matched": sum(row.get("current_matches", 0) for row in report.get("strategies", [])),
            "items": selected, "research": report, "allowed_boards": selected_boards, "mode": mode,
            "price_min": price_min, "price_max": price_max,
            "close_ready": bool(report.get("close_ready")) if mode == "close" else False}
    result["baseline_items"] = report.pop("_baseline_items", deepcopy(selected))
    # 在后台任务中持久化，独立测试可注入纯研究函数，不读写用户数据库。
    if research_builder is None:
        try:
            with SessionLocal() as db:
                fresh_histories = histories
                if closing:
                    expected_day = moment.date().isoformat()
                    fresh_histories = {symbol: bars for symbol, bars in histories.items() if bars and bars[-1][0] == expected_day}
                learning.store_histories(db, fresh_histories, cutoff)
                sample_symbols = {item["symbol"] for item in research.stratified_sample(items, research.settings.stock_research_sample_size)} | {"sh000300"}
                result["parameter_evaluation"] = learning.persist_evaluation(db,
                    {symbol: bars for symbol, bars in histories.items() if symbol in sample_symbols}, scope, cutoff)
                if mode == "close" and result["close_ready"] and result["complete"]:
                    learning.store_market(db, trade_date, fetched_at, market_items)
        except Exception:
            result["parameter_evaluation"] = {"status": "unavailable", "active": False, "strategies": [],
                "forward_days": 0, "required_forward_days": 60, "note": "历史数据或参数评估更新失败，本轮沿用此前方案。"}
        result["adaptive_applied"] = bool(evaluation and evaluation.get("active"))
        result["applied_parameters"] = options.get("parameters")
        options = {"mode": mode} if mode == "close" else {}
        result["factor_context"] = factors.enrich(selected, market_items, histories, trade_date, not errors, **options)
        if mode == "close":
            return result
        _attach_history(result)
        try:
            with SessionLocal() as db:
                result["paper"] = paper.update(db, result, histories)
        except Exception:
            result["paper"] = {"recorded": 0, "completed": 0, "pending": 0, "avg_net_pct": None,
                               "note": "前向跟踪记录失败，请检查数据库结构和服务日志。"}
    return result


def _run(boards, mode="intraday", price_min=0, price_max=None):
    def progress(value):
        with _lock:
            _scope(boards, mode, price_min, price_max)["progress"] = value
    try:
        options = {"price_min": price_min, "price_max": price_max} if price_min or price_max is not None else {}
        result = scan_market(progress=progress, allowed_boards=boards, mode=mode, **options)
        if mode == "close":
            if not result["close_ready"] or not result["complete"]:
                with _lock:
                    _scope(boards, mode, price_min, price_max).update(errors=result["errors"] or ["等待当日完整收盘日线，稍后可重新生成；保留上一份观察池。"])
                return
            with SessionLocal() as db:
                watchlists.save(db, result)
            _attach_history(result)
        with _lock:
            _scope(boards, mode, price_min, price_max).update(result)
    except Exception as exc:
        with _lock:
            _scope(boards, mode, price_min, price_max).update(errors=["扫描失败：%s" % exc])
            if mode != "close":
                _scope(boards, mode, price_min, price_max)["complete"] = False
    finally:
        with _lock:
            _scope(boards, mode, price_min, price_max)["running"] = False


def get_signals(refresh=False, analyze=False, boards=None, ai_config=None, mode="intraday", price_min=0, price_max=None,
                requested_snapshot_id=None, requested_codes=None, for_portfolio=False):
    global _last_attempt
    selected_boards = normalize_boards(boards)
    if mode not in ("intraday", "close"):
        raise ValueError("无效选股模式")
    price_min, price_max = price_range(price_min, price_max)
    moment = now_local()
    with _lock:
        state = _scope(selected_boards, mode, price_min, price_max)
        if mode == "close" and not state.get("loaded"):
            try:
                with SessionLocal() as db:
                    saved = watchlists.load(db, selected_boards, price_min, price_max)
                    if saved:
                        state.update(saved)
                state["loaded"] = True
            except Exception:
                state["errors"] = ["收盘观察池读取失败，请检查数据库或重新生成。"]
        key = (mode, scope_key(selected_boards, price_min, price_max))
        last_attempt = _attempts.get(key, 0)
        elapsed = time.monotonic() - last_attempt
        due = not last_attempt or (elapsed >= 120 and should_poll_quotes())
        allowed = True
        if mode == "close":
            allowed = moment.weekday() < 5 and moment.time() >= clock_time(15, 30)
            due = state.get("trade_date") != moment.date().isoformat() and (not last_attempt or elapsed >= 120)
        # 共享任务：多账号、多标签页不会重复拉取全市场。
        if not analyze and allowed and not state["running"] and (due or (refresh and elapsed >= 30)):
            _last_attempt = time.monotonic()
            _attempts[key] = _last_attempt
            state.update(running=True, progress=0, allowed_boards=selected_boards)
            _executor.submit(_run, selected_boards, mode, price_min, price_max)
        result = deepcopy(state)
    if for_portfolio:
        return result
    if result.get("research"):
        result["research"].pop("_study_sample", None)
        result["research"].pop("_history_cutoff", None)
    result["allowed_boards"] = selected_boards
    result["mode"] = mode
    result["analysis_snapshot_ready"] = bool(result.get("complete") and result.get("fetched_at"))
    result.update(price_min=price_min, price_max=price_max)
    result["can_generate_close"] = moment.weekday() < 5 and moment.time() >= clock_time(15, 30)
    result["close_notice"] = "交易日15:30后生成下一交易日观察池；生成后保存，次日仍可查看。价格及因子固定于生成时，盘中请切换模式重新确认。" if mode == "close" else None
    result.update(session=session_label(moment), source="新浪公开行情",
                  rules=RULES,
                  refresh_seconds=120, stale=True)
    if result["fetched_at"]:
        from datetime import datetime
        result["stale"] = (moment - datetime.fromisoformat(result["fetched_at"])).total_seconds() > 600
    result["market_date_current"] = result["trade_date"] == moment.date().isoformat()
    result["snapshot_id"] = deepseek.snapshot_id(result)
    # 规则快照共享，AI 请求按当前账号的密钥和配置版本隔离。
    if analyze and requested_snapshot_id != result["snapshot_id"]:
        raise SnapshotChanged("候选或分析依据已更新。请查看刷新后的名单，再点击 AI 分析。")
    request_error = None
    if analyze and not result.get("errors"):
        analysis_snapshot = result
        if requested_codes is not None:
            codes = set(requested_codes)
            available = {item["code"] for item in result["items"]}
            if not codes or len(codes) != len(requested_codes) or not codes <= available:
                raise ValueError("请选择当前候选名单中的股票，每只股票只能选择一次。")
            analysis_snapshot = dict(result, review_candidates=result["items"],
                                     items=[item for item in result["items"] if item["code"] in codes])
        request_error = deepseek.request_analysis(analysis_snapshot, retry=True, credentials=ai_config)
    result["ai"] = deepseek.analysis_state(result, credentials=ai_config)
    if request_error:
        result["ai"]["error"] = request_error
    result["engine"] = "技术策略 + 财报/行业/大盘 · %s 候选点评" % result["ai"]["provider_label"] if result["ai"]["configured"] else "技术策略 + 财报/行业/大盘（AI 未配置）"
    return result
