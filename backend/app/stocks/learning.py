"""持久化历史与低维参数滚动评估；缺少前向日期时只做影子评估。"""
import json
from datetime import date

from sqlalchemy import select, func

from ..database import SessionLocal
from ..models import StockHistorySnapshot, StockRuleEvaluation, StockCloseArchive, StockMarketArchive

VERSION = "tuning-v3"


def cached_history(symbol, cutoff):
    try:
        with SessionLocal() as db:
            row = db.scalar(select(StockHistorySnapshot).where(
                StockHistorySnapshot.symbol == symbol, StockHistorySnapshot.as_of == cutoff))
            return json.loads(row.bars_json) if row else None
    except Exception:
        return None


def store_histories(db, histories, cutoff):
    count = 0
    for symbol, bars in histories.items():
        if not bars:
            continue
        row = db.scalar(select(StockHistorySnapshot).where(
            StockHistorySnapshot.symbol == symbol, StockHistorySnapshot.as_of == cutoff))
        if row is None:
            row = StockHistorySnapshot(symbol=symbol, as_of=cutoff)
            db.add(row)
        row.bars_json = json.dumps(bars, allow_nan=False)
        count += len(bars)
    db.commit()
    return count


def load_evaluation(scope):
    try:
        with SessionLocal() as db:
            row = db.get(StockRuleEvaluation, scope)
            result = json.loads(row.report_json) if row else None
            return result if result and result.get("version") == VERSION else None
    except Exception:
        return None


def accepts(stats, parameters, index_stats):
    if not stats:
        return False
    extension = parameters.get("max_extension")
    if extension is not None and stats["last"] / stats["ma20"] - 1 > extension:
        return False
    if parameters.get("require_index_up"):
        return bool(index_stats and index_stats["last"] > index_stats["ma20"] >= index_stats["ma60"])
    return True


def forward_context(db, scope, cutoff):
    from . import research
    rows = list(db.scalars(select(StockCloseArchive).where(StockCloseArchive.scope == scope,
        StockCloseArchive.trade_date < cutoff).order_by(StockCloseArchive.trade_date.desc()).limit(90)).all())
    archives = [(row.trade_date, json.loads(row.snapshot_json)) for row in reversed(rows)]
    return [(day, archive) for day, archive in archives if (archive.get("research") or {}).get("version") == research.VERSION]


def pending_symbols(db, scope, cutoff):
    pools = forward_context(db, scope, cutoff)
    symbols = {item.get("symbol") for _, pool in pools for item in pool.get("baseline_items", pool.get("items", [])) if item.get("symbol")}
    if not symbols:
        return []
    latest = dict(db.execute(select(StockHistorySnapshot.symbol, func.max(StockHistorySnapshot.as_of))
                            .where(StockHistorySnapshot.symbol.in_(symbols)).group_by(StockHistorySnapshot.symbol)).all())
    return sorted([symbol for symbol in symbols if latest.get(symbol, "") < cutoff],
                  key=lambda symbol: (latest.get(symbol, ""), symbol))[:20]


def evaluate(histories, scope, forward_days=0, forward_pools=None):
    from . import research
    benchmark = histories.get("sh000300") or []
    days = [row[0] for row in benchmark]
    base = {"version": VERSION, "status": "accumulating", "forward_days": forward_days, "required_forward_days": 60,
            "sample_count": sum(symbol != "sh000300" and len(bars) >= 120 for symbol, bars in histories.items()),
            "active": False, "parameters": {}, "strategies": [],
            "history_days": len(days), "note": "只评估技术乖离过滤及沪深300趋势过滤；财报、行业和历史全市场筛选仍需逐日归档。参数只在训练区选择，再分别验证和留出检查；归档不足60天不自动采用。历史样本存在选择偏差，不能保证提高胜率。"}
    if len(days) < 220:
        base["reason"] = "完整基准日线不足220根"
        return base
    forward_pools = forward_pools or []
    forward_mode = len(forward_pools) >= 60
    calendar_days = [day for day, _ in forward_pools] if forward_mode else days
    validation_start, holdout_start = calendar_days[int(len(calendar_days) * .65)], calendar_days[int(len(calendar_days) * .85)]
    allowed = {day: {item.get("symbol"): item for item in pool.get("baseline_items", pool.get("items", []))}
               for day, pool in forward_pools} if forward_mode else {}
    base["evaluation_basis"] = "实际逐日归档的原始技术候选" if forward_mode else "当前样本历史影子研究，暂不采用参数"
    base["note"] += "达到门槛后改用逐日归档的原始技术候选选择参数，另要求成熟候选的未来日线覆盖至少90%。"
    base.update(validation_start=validation_start, holdout_start=holdout_start)
    index_features = {day: research.features(benchmark[:i + 1]) for i, (day, _) in enumerate(benchmark)}
    prepared = {}
    for symbol, bars in histories.items():
        if symbol != "sh000300":
            prepared[symbol] = (bars, [research.features(bars[:i + 1]) if i >= 59 else None for i in range(len(bars))])
    eligible, covered = 0, 0
    if forward_mode:
        positions = {day: i for i, day in enumerate(days)}
        for day, members in allowed.items():
            pos = positions.get(day)
            if pos is None or pos + research.HOLD + 1 >= len(days):
                continue
            required = days[pos + 1:pos + research.HOLD + 2]
            for symbol in members:
                eligible += 1
                stock_days = {day for day, _ in histories.get(symbol, [])}
                covered += all(value in stock_days for value in required)
    coverage = covered / eligible if eligible else 0
    base["forward_coverage_pct"] = round(coverage * 100, 2)

    def events(strategy, parameter):
        groups = {"train": [], "validation": [], "holdout": []}
        calendar = dict(benchmark)
        positions = {day: i for i, day in enumerate(days)}
        for symbol, (bars, stats) in prepared.items():
            free = 0
            for i in range(59, len(bars) - research.HOLD - 1):
                signal = bars[i][0]
                if forward_mode and (symbol not in allowed.get(signal, {}) or
                        strategy not in allowed[signal][symbol].get("strategies", [])):
                    continue
                if i < free or strategy not in research.triggers(stats[i]) or not accepts(stats[i], parameter, index_features.get(signal)):
                    continue
                entry_i, exit_i = i + 1, i + 1 + research.HOLD
                entry_day, exit_day = bars[entry_i][0], bars[exit_i][0]
                pos = positions.get(signal)
                if pos is None or days[pos + 1:pos + research.HOLD + 2] != [day for day, _ in bars[entry_i:exit_i + 1]]:
                    continue
                part = "train" if exit_day < validation_start else "validation" if signal >= validation_start and exit_day < holdout_start else "holdout" if signal >= holdout_start else None
                if part is None:
                    continue
                entry, close = bars[entry_i][1], bars[exit_i][1]
                net = research.net_return(entry, close)
                groups[part].append({"net": net, "double_cost_net": research.net_return(entry, close, 2),
                                     "excess": net - (calendar[exit_day] / calendar[entry_day] - 1)})
                free = exit_i + 1
        return {part: research.summarize(value) for part, value in groups.items()}

    parameters = {}
    passed_all = True
    for key, spec in research.STRATEGIES.items():
        variants = [{"max_extension": extension, "require_index_up": trend}
                    for extension in ([None, .06, .10] if key == "trend" else [None]) for trend in (False, True)]
        results = [{"parameter": parameter, **events(key, parameter)} for parameter in variants]
        eligible = [row for row in results if row["train"]["trades"] >= 30]
        chosen = max(eligible, key=lambda row: row["train"]["avg_net_pct"]) if eligible else results[0]
        baseline = results[0]
        passed = bool(eligible) and all(chosen[part]["trades"] >= 30 and
            (chosen[part]["double_cost_pct"] or 0) > 0 and (chosen[part]["avg_excess_pct"] or 0) > 0 and
            chosen[part]["avg_net_pct"] >= (baseline[part]["avg_net_pct"] or 0)
            for part in ("validation", "holdout"))
        parameters[key] = chosen["parameter"] if passed else baseline["parameter"]
        passed_all = passed_all and passed
        base["strategies"].append({"key": key, "label": spec["label"], "selected": chosen,
                                   "baseline": baseline, "passed": passed, "tested_variants": len(results)})
    # 先积累真实新增日期，再允许门槛同时满足的方案用于未来扫描。
    active = forward_days >= 60 and forward_mode and coverage >= .9 and passed_all
    base.update(active=active, parameters=parameters, status="active" if active else "shadow",
                reason="已通过前向日期、覆盖率及验证/留出门槛" if active else "继续采用原规则，等待60个归档日期、90%后续行情覆盖及验证/留出区间各30个事件通过")
    return base


def persist_evaluation(db, histories, scope, as_of):
    row = db.get(StockRuleEvaluation, scope)
    if row is not None and row.as_of >= as_of:
        previous = json.loads(row.report_json)
        incoming = sum(symbol != "sh000300" and len(bars) >= 120 for symbol, bars in histories.items())
        if previous.get("version") == VERSION and not (previous.get("sample_count", 0) < min(12, incoming)):
            return previous
    pools = forward_context(db, scope, as_of)
    if len(pools) >= 60:
        symbols = {item.get("symbol") for _, pool in pools for item in pool.get("baseline_items", pool.get("items", [])) if item.get("symbol")}
        latest = select(StockHistorySnapshot.symbol, func.max(StockHistorySnapshot.as_of).label("last_asof")).where(
            StockHistorySnapshot.symbol.in_(symbols), StockHistorySnapshot.as_of <= as_of).group_by(StockHistorySnapshot.symbol).subquery()
        rows = db.scalars(select(StockHistorySnapshot).join(latest,
            (StockHistorySnapshot.symbol == latest.c.symbol) & (StockHistorySnapshot.as_of == latest.c.last_asof))).all()
        histories = dict(histories, **{row.symbol: json.loads(row.bars_json) for row in rows})
    report = evaluate(histories, scope, len(pools), forward_pools=pools)
    if row is None:
        row = StockRuleEvaluation(scope=scope)
        db.add(row)
    row.as_of, row.report_json = as_of, json.dumps(report, ensure_ascii=False, allow_nan=False)
    db.commit()
    return report


def store_market(db, trade_date, fetched_at, items):
    row = db.get(StockMarketArchive, trade_date)
    if row is None:
        row = StockMarketArchive(trade_date=trade_date)
        db.add(row)
    row.snapshot_json = json.dumps({"fetched_at": fetched_at, "source": "新浪完整扫描中的有效非ST成交股票",
        "items": [{key: item.get(key) for key in ("code", "symbol", "name", "board", "price", "open", "high", "low",
                   "volume", "quote_time", "change_pct", "amount", "turnover_pct")} for item in items]}, ensure_ascii=False, allow_nan=False)
    db.commit()
