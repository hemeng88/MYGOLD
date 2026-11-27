"""多策略研究：预先固定规则、时间切分、次日收盘入场的五交易日事件研究。

数据只有前复权收盘，不声称可以复现真实委托成交，也不将事件收益当成组合收益。
"""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed, TimeoutError
from datetime import date, timedelta, time as clock_time
import math
import statistics
import threading
from copy import deepcopy
from collections import Counter, deque
from zlib import crc32

import httpx

from ..config import settings
from ..timeutil import now_local
from . import universe

VERSION = "multi-v3"
LIQUIDITY_BANDS = ("high", "upper_mid", "mid")
STRATEGIES = {
    "trend": {"label": "趋势延续", "rule": "20日均价高于60日均价，收盘高于20日均价且10日涨幅为正"},
    "pullback": {"label": "趋势回调", "rule": "20日均价高于60日均价，收盘在20日均价的97%～101%，5日涨幅为负"},
    "low_vol": {"label": "低波动观察", "rule": "20日收益波动率不高于2%，20日均价不低于60日均价，收盘距20日均价不超过3%"},
}
HOLD = 5
COMPARE_HOLDS = (3, HOLD, 10)
# 假设成本（非券商报价）：买卖各0.03%佣金、各0.05%滑点，卖出另计0.05%税费。
BUY_COST = 0.0008
SELL_COST = 0.0013
_cache = {}
_lock = threading.Lock()
_preferred_url = None
TENCENT_MIRROR = "https://proxy.finance.qq.com/ifzqgtimg/appstock/app/fqkline/get"


def clean_bars(bars, before):
    unique = {}
    for day, value in bars:
        try:
            price = float(value)
        except (ValueError, TypeError):
            continue
        try:
            date.fromisoformat(day)
        except (ValueError, TypeError):
            continue
        if day < before and math.isfinite(price) and price > 0:
            unique[day] = price
    return sorted(unique.items())


def history(symbol, transport=None, include_today=False):
    global _preferred_url
    moment = now_local()
    include_today = include_today and moment.time() >= clock_time(15, 30)
    cutoff = (moment.date() + timedelta(days=1 if include_today else 0)).isoformat()
    expected_day = moment.date().isoformat() if include_today else None
    with _lock:
        cached = _cache.get(symbol)
        if cached and cached[0] == cutoff and (not expected_day or cached[1][-1][0] == expected_day):
            return cached[1]
    # 研究不能混用未复权新浪日线和前复权日线，避免除权被误判为暴跌。
    with _lock:
        preferred = _preferred_url
    urls = list(dict.fromkeys([preferred or settings.fund_kline_tencent_url,
                              settings.fund_kline_tencent_url, TENCENT_MIRROR]))
    last_error = None
    fallback = []
    with httpx.Client(timeout=settings.request_timeout_seconds, follow_redirects=True, transport=transport) as client:
        for url in urls:
            try:
                response = client.get(url, params={"param": "%s,day,,,260,qfq" % symbol},
                                      headers={"User-Agent": universe.SINA_HEADERS["User-Agent"], "Referer": "https://gu.qq.com/"})
                response.raise_for_status()
                block = ((response.json() or {}).get("data") or {}).get(symbol) or {}
                raw = block.get("day") if symbol == "sh000300" else block.get("qfqday")
                bars = clean_bars([(str(row[0])[:10], row[2]) for row in (raw or []) if len(row) > 2], cutoff)
                if bars:
                    if expected_day and bars[-1][0] != expected_day:
                        if not fallback or bars[-1][0] > fallback[-1][0]:
                            fallback = bars
                        continue
                    with _lock:
                        _cache[symbol] = (cutoff, bars)
                        _preferred_url = url
                    return bars
            except (httpx.HTTPError, ValueError, TypeError, AttributeError) as exc:
                last_error = exc
    if fallback:
        return fallback
    if last_error:
        raise last_error
    return []


def raw_history(symbol, count=260):
    headers = {"User-Agent": universe.SINA_HEADERS["User-Agent"], "Referer": "https://gu.qq.com/"}
    with httpx.Client(timeout=6, headers=headers) as client:
        for url in dict.fromkeys((TENCENT_MIRROR, settings.fund_kline_tencent_url)):
            try:
                response = client.get(url, params={"param": f"{symbol},day,,,{count},"})
                response.raise_for_status()
                block = (response.json().get("data") or {}).get(symbol) or {}
                bars = {}
                for row in block.get("day") or []:
                    if len(row) < 6:
                        continue
                    try:
                        day = date.fromisoformat(row[0]).isoformat()
                        opening, close, high, low, volume = map(float, row[1:6])
                    except (ValueError, TypeError):
                        continue
                    if all(map(math.isfinite, (opening, close, high, low, volume))) and volume > 0 and 0 < low <= min(opening, close) <= max(opening, close) <= high:
                        bars[day] = (day, close, high, low)
                if bars:
                    return sorted(bars.values())
            except (httpx.HTTPError, ValueError, TypeError, AttributeError):
                continue
    return []


def features(bars):
    if len(bars) < 60:
        return None
    closes = [row[1] for row in bars[-60:]]
    returns = [closes[i] / closes[i - 1] - 1 for i in range(40, 60)]
    return {"as_of": bars[-1][0], "ma20": statistics.mean(closes[-20:]),
            "ma60": statistics.mean(closes), "return5": closes[-1] / closes[-6] - 1,
            "return10": closes[-1] / closes[-11] - 1, "vol20": statistics.pstdev(returns),
            "last": closes[-1]}


def triggers(stats):
    if not stats:
        return []
    price, ma20, ma60 = (stats[k] for k in ("last", "ma20", "ma60"))
    out = []
    if ma20 > ma60 and price > ma20 and stats["return10"] > 0:
        out.append("trend")
    if ma20 > ma60 and 0.97 * ma20 <= price <= 1.01 * ma20 and stats["return5"] < 0:
        out.append("pullback")
    if stats["vol20"] <= 0.02 and ma20 >= ma60 and abs(price / ma20 - 1) <= 0.03:
        out.append("low_vol")
    return out


def net_return(entry, exit_price, multiplier=1):
    return exit_price * (1 - SELL_COST * multiplier) / (entry * (1 + BUY_COST * multiplier)) - 1


def event_study(bars, strategy, split_date, benchmark):
    """信号仅看 t 及之前数据，t+1 收盘进入，持有五根后退出；单股不重叠。"""
    result = {"train": [], "test": []}
    next_free = 0
    dates = list(benchmark)
    positions = {day: index for index, day in enumerate(dates)}
    for index in range(59, len(bars) - HOLD - 1):
        if index < next_free or strategy not in triggers(features(bars[index - 59:index + 1])):
            continue
        entry_i, exit_i = index + 1, index + 1 + HOLD
        signal_date, entry_date, exit_date = bars[index][0], bars[entry_i][0], bars[exit_i][0]
        # 不让训练区间的持仓跨入样本外，也不让样本外用训练末日的信号。
        if exit_date < split_date:
            part = "train"
        elif signal_date >= split_date:
            part = "test"
        else:
            continue
        # 缺失交易日或停牌的股票不能按“下一根”假装次日成交。
        if dates:
            pos = positions.get(signal_date)
            if pos is None or dates[pos + 1:pos + HOLD + 2] != [row[0] for row in bars[entry_i:exit_i + 1]]:
                continue
        entry, exit_price = bars[entry_i][1], bars[exit_i][1]
        net = net_return(entry, exit_price)
        base = benchmark[exit_date] / benchmark[entry_date] - 1 if entry_date in benchmark and exit_date in benchmark else None
        result[part].append({"signal_date": signal_date, "entry_date": entry_date, "exit_date": exit_date,
                             "net": net, "double_cost_net": net_return(entry, exit_price, 2),
                             "excess": net - base if base is not None else None})
        next_free = exit_i + 1
    return result


def summarize(events):
    excess = [row["excess"] for row in events if row["excess"] is not None]
    return {"trades": len(events),
            "win_pct": round(sum(row["net"] > 0 for row in events) / len(events) * 100, 2) if events else None,
            "avg_net_pct": round(statistics.mean(row["net"] for row in events) * 100, 3) if events else None,
            "worst_trade_pct": round(min(row["net"] for row in events) * 100, 3) if events else None,
            "double_cost_pct": round(statistics.mean(row["double_cost_net"] for row in events) * 100, 3) if events else None,
            "avg_excess_pct": round(statistics.mean(excess) * 100, 3) if excess else None,
            "benchmark_trades": len(excess)}


def compare_holding_periods(histories, benchmark, split_date):
    """对同一批样本外信号计算不同持有期，按最长持有期去重。"""
    if not benchmark or not split_date:
        return None
    dates = list(benchmark)
    positions = {day: index for index, day in enumerate(dates)}
    longest = max(COMPARE_HOLDS)
    events = {hold: [] for hold in COMPARE_HOLDS}
    missing = 0
    for bars in histories:
        prices = dict(bars)
        next_free = 0
        for index in range(59, len(bars)):
            day = bars[index][0]
            pos = positions.get(day)
            if day < split_date or pos is None or pos < next_free or pos + 1 + longest >= len(dates):
                continue
            if not triggers(features(bars[index - 59:index + 1])):
                continue
            window = dates[pos + 1:pos + longest + 2]
            if any(session not in prices for session in window):
                missing += 1
                continue
            entry_day = window[0]
            entry = prices[entry_day]
            for hold in COMPARE_HOLDS:
                exit_day = window[hold]
                exit_price = prices[exit_day]
                net = net_return(entry, exit_price)
                events[hold].append({"net": net, "double_cost_net": net_return(entry, exit_price, 2),
                                     "excess": net - (benchmark[exit_day] / benchmark[entry_day] - 1)})
            next_free = pos + longest + 2
    return {"missing_windows": missing,
            "periods": [{"hold_days": hold, **summarize(events[hold])} for hold in COMPARE_HOLDS]}


def evidence_status(metrics):
    if metrics["trades"] < 30:
        return "样本不足"
    if metrics["avg_net_pct"] is None or metrics["avg_net_pct"] <= 0:
        return "样本外净收益非正"
    if metrics["double_cost_pct"] is None or metrics["double_cost_pct"] <= 0:
        return "成本敏感"
    if metrics["avg_excess_pct"] is None:
        return "缺少基准验证"
    if metrics["avg_excess_pct"] <= 0:
        return "未跑赢基准"
    return "待前向验证"


def stratified_sample(items, limit):
    """按板块和成交额分位分配预算，在每档内均匀取样。"""
    groups = {}
    for item in sorted(items, key=lambda row: (-row["amount"], row["code"])):
        groups.setdefault(item["board"], []).append(item)
    strata = {}
    for board, rows in groups.items():
        size = len(rows)
        cuts = (0, math.ceil(size * .20), math.ceil(size * .50),
                size if size <= limit else math.ceil(size * .80))
        strata[board] = {band: rows[start:end] for band, start, end in zip(LIQUIDITY_BANDS, cuts, cuts[1:])}

    # 每轮每个板块一个名额，板块内部轮换成交额档位。
    budgets = Counter()
    schedule = []
    while len(schedule) < limit:
        before = len(schedule)
        for board, bands in sorted(strata.items()):
            available = [band for band in bands if budgets[board, band] < len(bands[band])]
            if available:
                band = min(available, key=lambda key: budgets[board, key])
                budgets[board, band] += 1
                schedule.append((board, band))
            if len(schedule) >= limit:
                break
        if len(schedule) == before:
            break

    queues = {}
    for (board, band), count in budgets.items():
        rows = strata[board][band]
        # 档内用稳定散列抽样，成交排名小幅变化不会大规模换样。
        ranked = sorted(rows, key=lambda row: (crc32(row["code"].encode()), row["code"]))
        queues[board, band] = deque(dict(row, liquidity_band=band) for row in ranked[:count])
    return [queues[key].popleft() for key in schedule]


def balanced_candidates(groups, limit=20):
    out, picked = [], set()
    # 同一股票可属于多种策略，但只占一个候选位置。
    queues = {}
    for band in (*LIQUIDITY_BANDS, None):
        for key, rows in groups.items():
            ranked = sorted((row for row in rows if row.get("liquidity_band") == band),
                            key=lambda row: (-row.get("amount", 0), row["code"]))
            if ranked:
                queues[key, band] = deque(ranked)
    while queues and len(out) < limit:
        for key in list(queues):
            while queues[key] and queues[key][0]["code"] in picked:
                queues[key].popleft()
            if queues[key]:
                item = queues[key].popleft()
                picked.add(item["code"])
                out.append(item)
            if not queues[key]:
                del queues[key]
            if len(out) >= limit:
                break
    return out


def build_research(items, trade_date, loader=None, progress=None, extra_symbols=(), mode="intraday", parameters=None):
    closing = mode == "close" and now_local().time() >= clock_time(15, 30)
    cutoff = (now_local().date() + timedelta(days=1 if closing else 0)).isoformat()
    if loader is None:
        from .learning import cached_history
        expected_day = now_local().date().isoformat() if closing else None

        def loader(symbol):
            cached = cached_history(symbol, cutoff)
            if cached and (not expected_day or cached[-1][0] == expected_day):
                return cached
            return history(symbol, include_today=closing)
    sample = stratified_sample(items, settings.stock_research_sample_size)
    histories, errors = {}, []
    pool = ThreadPoolExecutor(max_workers=4, thread_name_prefix="research-history")
    symbols = {item["symbol"] for item in sample} | set(extra_symbols)
    futures = {pool.submit(loader, symbol): symbol for symbol in symbols}
    futures[pool.submit(loader, "sh000300")] = "sh000300"
    try:
        for future in as_completed(futures, timeout=90):
            symbol = futures[future]
            try:
                histories[symbol] = clean_bars(future.result(), cutoff)
            except Exception:
                errors.append(symbol)
            if progress:
                progress(len(histories))
    except TimeoutError:
        errors.extend(symbol for future, symbol in futures.items() if not future.done())
    finally:
        pool.shutdown(wait=False, cancel_futures=True)
    benchmark = dict(histories.get("sh000300") or [])
    close_ready = bool(closing and trade_date == now_local().date().isoformat()
                       and benchmark and max(benchmark) == trade_date)
    dates = sorted(benchmark) or sorted({date for bars in histories.values() for date, _ in bars})
    split = dates[int(len(dates) * 0.65)] if len(dates) >= 100 else None
    groups = {key: [] for key in STRATEGIES}
    studies = {key: {"train": [], "test": []} for key in STRATEGIES}
    usable = 0
    insufficient = 0
    comparison_histories = []
    signal_features = {}
    for item in sample:
        bars = histories.get(item["symbol"]) or []
        stats = features(bars)
        if not stats or len(bars) < 120:
            insufficient += 1
            continue
        usable += 1
        comparison_histories.append(bars)
        if split:
            for key in STRATEGIES:
                result = event_study(bars, key, split, benchmark)
                for part in ("train", "test"):
                    studies[key][part].extend(result[part])
        # 老日线可用于历史研究，不能伪装成最新技术信号。
        if not benchmark or bars[-1][0] != dates[-1] or (now_local().date() - date.fromisoformat(bars[-1][0])).days > 10:
            continue
        if mode == "close" and (not close_ready or bars[-1][0] != trade_date):
            continue
        if mode == "close" and abs(item["price"] / bars[-1][1] - 1) > 0.005:
            # 当前前复权收盘应与最新现价一致；源未对齐时不拿旧报价生成观察区间。
            continue
        hits = triggers(stats)
        if not hits:
            continue
        signal_features[item["symbol"]] = stats
        row = dict(item, strategies=hits, strategy_labels=[STRATEGIES[key]["label"] for key in hits],
                   historical_as_of=stats["as_of"], ma20=round(stats["ma20"], 3), ma60=round(stats["ma60"], 3),
                   signal_close=stats["last"], ma20_gap_pct=round((stats["last"] / stats["ma20"] - 1) * 100, 3),
                   return5_pct=round(stats["return5"] * 100, 3), return10_pct=round(stats["return10"] * 100, 3),
                   vol20_pct=round(stats["vol20"] * 100, 3), status="待前向验证",
                   reason=" / ".join(STRATEGIES[key]["label"] for key in hits) + "：基于最近完整交易日日线触发")
        for key in hits:
            groups[key].append(row)
    reports = []
    for key, specification in STRATEGIES.items():
        test = summarize(studies[key]["test"])
        reports.append({"key": key, **specification, "current_matches": len(groups[key]),
                        "train": summarize(studies[key]["train"]), "test": test,
                        "status": evidence_status(test)})
    close_pending = [item["symbol"] for item in sample
                     if not histories.get(item["symbol"]) or
                     (len(histories[item["symbol"]]) >= 120 and histories[item["symbol"]][-1][0] != trade_date)] if mode == "close" else []
    if mode == "close":
        has_current_stock = any(len(histories.get(row["symbol"], [])) >= 120
                                and histories[row["symbol"]][-1][0] == trade_date for row in sample)
        close_ready = close_ready and has_current_stock and len(close_pending) <= len(sample) // 10
    selected = balanced_candidates(groups)
    baseline_items = deepcopy(selected)
    if parameters:
        from .learning import accepts
        index_stats = features(histories.get("sh000300") or [])
        for item in selected:
            stats = signal_features[item["symbol"]]
            item["strategies"] = [key for key in item["strategies"] if accepts(stats, parameters.get(key, {}), index_stats)]
            item["strategy_labels"] = [STRATEGIES[key]["label"] for key in item["strategies"]]
            item["reason"] = " / ".join(item["strategy_labels"]) + "：基于最近完整交易日日线触发"
        selected = [item for item in selected if item["strategies"]]
    evidence = {row["key"]: row["status"] for row in reports}
    for item in selected:
        item["validation"] = [STRATEGIES[key]["label"] + "：" + evidence[key] for key in item["strategies"]]
        item["priority_eligible"] = any(evidence[key] == "待前向验证" for key in item["strategies"])
        item["status"] = "待前向验证" if item["priority_eligible"] else "验证证据不足"
    result = {"version": VERSION, "sample_requested": len(sample), "sample_usable": usable,
              "_baseline_items": baseline_items,
              "_study_sample": [{"symbol": row["symbol"], "board": row["board"],
                                 "liquidity_band": row["liquidity_band"]} for row in sample
                                if len(histories.get(row["symbol"], [])) >= 120],
              "_history_cutoff": cutoff,
              "sample_bands": dict(Counter(row["liquidity_band"] for row in sample)),
              "candidate_bands": dict(Counter(row["liquidity_band"] for row in selected)),
              "holding_comparison": compare_holding_periods(comparison_histories, benchmark, split),
              "close_ready": close_ready,
              "close_pending": len(close_pending),
              "history_failed": len(set(errors)), "history_insufficient": insufficient, "split_date": split,
              "history_start": dates[0] if dates else None, "history_end": dates[-1] if dates else None,
              "benchmark_available": bool(benchmark), "strategies": reports,
              "assumptions": [
                  "各板块内按当前成交额排名分档抽样。样本多时取前20%、20%～50%、50%～80%；历史结果存在幸存者和当前样本选择偏差。",
                  "三套规则预先固定，没有用样本外成绩挑参数；统一日期按前65%/后35%分为研究区间和样本外。",
                  ("收盘模式在15:30后纳入当日完整日线，沪深300需为当日，最多容许10%抽样股票仍缺日线，缺失标的退出本轮候选；" if mode == "close" else "盘中模式只使用今天之前的完整日线；") + "历史事件信号次日收盘假设入场，持有五个交易日，单股单策略不重叠。",
                  "假设买卖佣金各0.03%、滑点各0.05%、卖出税费0.05%；不代表实际券商费率，另展示双倍成本结果。",
                  "只有前复权收盘，未模拟涨跌停、最低佣金、整手、容量及真实成交；展示的是事件均值，不是组合收益率。",
                  "股票研究仅采用腾讯明确标注的前复权日线；取不到不混用未复权数据，缺少120根日线的样本不参与。",
                  "超额收益相对同起止日沪深300价格涨幅（不含分红）；缺基准数据则留空。",
                  "样本外不足30个事件、净收益非正、成本加倍后非正或未跑赢基准时，不允许AI标为优先观察。",
                  "样本外仍共享当前股票样本，不能证明未来收益；通过历史初筛也仅标为待前向验证。",
              ]}
    return selected, result, histories
