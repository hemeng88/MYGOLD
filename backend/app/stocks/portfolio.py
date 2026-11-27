"""主板收盘技术信号的资金与成交约束模拟。"""
from concurrent.futures import ThreadPoolExecutor, as_completed, TimeoutError
from threading import Lock
import logging
from uuid import uuid4

from . import learning, research

logger = logging.getLogger(__name__)
_lock = Lock()
_jobs = {}
_executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="portfolio")

SELL_TAX = 0.0005
LOT_SIZE = 100


def _prepare(sample, adjusted, raw, days, price_min, price_max):
    signals = {}
    securities = {}
    calendar = set(days)
    for item in sample:
        symbol = item["symbol"]
        bars = adjusted.get(symbol, [])
        raw_by_date = {row[0]: row[1:] for row in raw.get(symbol, [])}
        if not calendar.intersection(raw_by_date) or not bars or bars[-1][0] < days[0]:
            continue
        marks = dict(bars)
        executions = {}
        for i, (day, price) in enumerate(bars):
            if day not in calendar or day not in raw_by_date:
                continue
            close, high, low = raw_by_date[day]
            # 单一成交价且较前一有效复权收盘同向跳动，保守视为一侧无法成交。
            direction = 0
            if high == low and i:
                previous = bars[i - 1][1]
                direction = (price > previous) - (price < previous)
            executions[day] = (close, direction)
            if price_min <= close and (price_max is None or close <= price_max):
                hits = research.triggers(research.features(bars[max(0, i - 59):i + 1]))
                if hits:
                    groups = signals.setdefault(day, {key: [] for key in research.STRATEGIES})
                    for key in hits:
                        groups[key].append(dict(item, code=symbol))
        securities[symbol] = (marks, executions)
    return signals, securities


def simulate(sample, adjusted, raw, benchmark, split, end, price_min, price_max, config):
    days = sorted(day for day in benchmark if split <= day <= end)
    if len(days) <= research.HOLD + 1:
        raise ValueError("可用的样本外交易日不足，暂时无法模拟。")
    signals, securities = _prepare(sample, adjusted, raw, days, price_min, price_max)
    if not securities:
        raise ValueError("未取得可对齐的主板日线，请稍后重试。")

    cash = config["starting_cash"]
    commission = config["commission_pct"] / 100
    slippage = config["slippage_pct"] / 100
    positions = {}
    curve = []
    closed, wins = 0, 0
    fees = 0.0
    skipped = {"no_buy_fill": 0, "outside_price_range": 0, "insufficient_budget": 0,
               "position_limit": 0, "delayed_exit_days": 0}
    orders = []

    def cost(value, selling=False):
        return max(config["min_commission"], value * commission) + value * (slippage + (SELL_TAX if selling else 0))

    for index, day in enumerate(days):
        # 同一个收盘撮合点，卖出所得从下一交易日开始用于买入。
        available_cash = cash
        previous_equity = curve[-1]["equity"] if curve else cash
        exited = set()
        for symbol, position in list(positions.items()):
            marks, executions = securities[symbol]
            if day in marks:
                position["value"] = position["units"] * marks[day]
            if index < position["exit_index"]:
                continue
            fill = executions.get(day)
            if not fill or fill[1] < 0:
                skipped["delayed_exit_days"] += 1
                continue
            fee = cost(position["value"], selling=True)
            proceeds = position["value"] - fee
            fees += fee
            cash += proceeds
            closed += 1
            wins += proceeds > position["spent"]
            del positions[symbol]
            exited.add(symbol)

        for order in orders:
            symbol = order["symbol"]
            if symbol in positions or symbol in exited:
                continue
            if len(positions) >= config["max_positions"]:
                skipped["position_limit"] += 1
                continue
            marks, executions = securities[symbol]
            fill = executions.get(day)
            if not fill or fill[1] > 0:
                skipped["no_buy_fill"] += 1
                continue
            if fill[0] < price_min or (price_max is not None and fill[0] > price_max):
                skipped["outside_price_range"] += 1
                continue
            budget = min(available_cash, previous_equity * config["max_position_pct"] / 100)
            lot_value = fill[0] * LOT_SIZE
            lots = max(0, int((budget - config["min_commission"]) // lot_value))
            while lots and lots * lot_value + cost(lots * lot_value) > budget:
                lots -= 1
            if not lots:
                skipped["insufficient_budget"] += 1
                continue
            value = lots * lot_value
            fee = cost(value)
            spent = value + fee
            positions[symbol] = {"units": value / marks[day], "value": value, "spent": spent,
                                 "exit_index": index + research.HOLD}
            fees += fee
            cash -= spent
            available_cash -= spent

        equity = cash + sum(position["value"] for position in positions.values())
        curve.append({"date": day, "equity": equity})
        orders = research.balanced_candidates(signals.get(day, {})) if index + research.HOLD + 1 < len(days) else []

    peak = config["starting_cash"]
    drawdown = 0.0
    for row in curve:
        peak = max(peak, row["equity"])
        drawdown = max(drawdown, 1 - row["equity"] / peak)
    end_equity = curve[-1]["equity"]
    start = config["starting_cash"]
    return {
        "start_date": days[0], "end_date": days[-1], "sample_size": len(sample),
        "data_symbols": len(securities), "sessions": len(days), "starting_cash": start,
        "end_equity": round(end_equity, 2), "return_pct": round((end_equity / start - 1) * 100, 2),
        "benchmark_pct": round((benchmark[days[-1]] / benchmark[days[0]] - 1) * 100, 2),
        "max_drawdown_pct": round(drawdown * 100, 2), "closed_trades": closed,
        "win_pct": round(wins / closed * 100, 2) if closed else None, "open_positions": len(positions),
        "cost_total": round(fees, 2), "skipped": skipped,
        "curve": [dict(row, equity=round(row["equity"], 2)) for row in curve],
    }


def _study(sample, report, price_min, price_max, config):
    split, end = report["split_date"], report["history_end"]
    cutoff = report["_history_cutoff"]
    benchmark = dict(learning.cached_history("sh000300", cutoff) or research.history("sh000300", include_today=True))
    adjusted, raw = {}, {}

    def load(symbol):
        bars = learning.cached_history(symbol, cutoff) or research.history(symbol, include_today=True)
        return [(day, close) for day, close in bars if day <= end], research.raw_history(symbol)

    pool = ThreadPoolExecutor(max_workers=8, thread_name_prefix="portfolio-history")
    futures = {pool.submit(load, row["symbol"]): row["symbol"] for row in sample}
    try:
        for future in as_completed(futures, timeout=90):
            symbol = futures[future]
            try:
                adjusted[symbol], raw[symbol] = future.result()
            except Exception:
                logger.debug("组合回测日线读取失败：%s", symbol, exc_info=True)
    except TimeoutError:
        logger.warning("组合回测部分日线请求超时")
    finally:
        pool.shutdown(wait=False, cancel_futures=True)
    return simulate(sample, adjusted, raw, benchmark, split, end, price_min, price_max, config)


def status(user_id):
    with _lock:
        return dict(_jobs.get(user_id, {"status": "idle"}))


def _run(user_id, job, sample, report, price_min, price_max, config):
    try:
        result = _study(sample, report, price_min, price_max, config)
        update = {"status": "complete", "result": result}
    except ValueError as exc:
        update = {"status": "error", "error": str(exc)}
    except Exception:
        logger.exception("组合回测失败")
        update = {"status": "error", "error": "组合回测失败，请稍后重试。"}
    with _lock:
        if _jobs[user_id]["id"] == job:
            _jobs[user_id].update(update)


def start(user_id, snapshot, price_min, price_max, config):
    report = snapshot.get("research") or {}
    sample = [row for row in report.get("_study_sample", []) if row["board"] == "主板"]
    if not snapshot.get("complete") or not sample or not report.get("split_date"):
        raise ValueError("请先在包含主板的范围内完成一轮选股扫描，再运行组合回测。")
    with _lock:
        existing = _jobs.get(user_id)
        if existing and existing["status"] == "running":
            return dict(existing)
        if sum(job["status"] == "running" for job in _jobs.values()) >= 4:
            raise RuntimeError("回测任务已排满，请稍后重试。")
        if len(_jobs) >= 64:
            finished = next((key for key, job in _jobs.items() if job["status"] != "running"), None)
            if finished is not None:
                del _jobs[finished]
        job = uuid4().hex
        _jobs[user_id] = {"id": job, "status": "running", "config": config,
                          "price_min": price_min, "price_max": price_max}
        _executor.submit(_run, user_id, job, sample, report, price_min, price_max, config)
        return dict(_jobs[user_id])
