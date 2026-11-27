"""按自然形成的收盘信号和盘中报价运行账号私有模拟盘。"""
from collections import Counter
from datetime import datetime, time, timedelta
from decimal import Decimal, ROUND_HALF_UP
import json
import logging
from threading import Lock

from sqlalchemy import func, select

from ..database import SessionLocal
from ..funds.sources import fetch_market_trade_date
from ..models import StockCloseArchive, StockSimAccount, StockSimEquity, StockSimPosition, StockSimTrade
from ..schemas import StockSimConfig
from ..timeutil import now_local
from . import research, universe
from .portfolio import LOT_SIZE, SELL_TAX
from .preferences import price_range, scope_key
from .simulator_quotes import BENCHMARK, cents, fetch

logger = logging.getLogger(__name__)
_lock = Lock()
ENTRY_START = time(9, 35)
ENTRY_END = time(10, 0)
CLOSE = time(15, 0)
MAX_QUOTE_AGE = 90


def _scope(config):
    return scope_key(["主板"], config.price_min, config.price_max)


def entry_scopes(db):
    return {_scope(StockSimConfig.model_validate_json(raw)) for raw in
            db.scalars(select(StockSimAccount.config_json).where(StockSimAccount.running)).all()}


def save_config(db, user_id, payload):
    low, high = price_range(payload.price_min, payload.price_max)
    if high is not None and not cents(high):
        raise ValueError("最高股价至少为 0.01 元。")
    config = payload.model_copy(update={
        "price_min": low, "price_max": high, "strategies": list(dict.fromkeys(payload.strategies)),
        "starting_cash": cents(payload.starting_cash) / 100,
    })
    with _lock:
        account = db.get(StockSimAccount, user_id)
        if account is None:
            start = cents(config.starting_cash)
            account = StockSimAccount(user_id=user_id, cash_cents=start, peak_cents=start, created_at=now_local())
            db.add(account)
        elif StockSimConfig.model_validate_json(account.config_json).starting_cash != config.starting_cash:
            raise ValueError("模拟账户已创建，起始资金固定为建账时的金额。")
        account.config_json = config.model_dump_json()
        db.commit()


def set_running(db, user_id, running):
    with _lock:
        account = db.get(StockSimAccount, user_id)
        if account is None:
            raise LookupError("请先保存模拟账户配置。")
        if account.running != running:
            account.running = running
            account.enabled_at = now_local() if running else None
            account.message = "已启动，等待下一个行情检查。" if running else "已暂停买卖，持仓继续随有效报价估值。"
            db.commit()


def _positions(db, user_id):
    return list(db.scalars(select(StockSimPosition).where(StockSimPosition.user_id == user_id)
                           .order_by(StockSimPosition.opened_at, StockSimPosition.symbol)))


def _signals(db, config, previous_day):
    if not previous_day:
        return None
    row = db.scalar(select(StockCloseArchive).where(
        StockCloseArchive.scope == _scope(config), StockCloseArchive.trade_date == previous_day))
    if row is None:
        return None
    snapshot = json.loads(row.snapshot_json)
    if not snapshot.get("complete") or not snapshot.get("close_ready"):
        return None
    result = []
    for item in snapshot.get("items", []):
        symbol = item["symbol"]
        matches = [strategy for strategy in config.strategies if strategy in item.get("strategies", [])]
        if (matches and item.get("board") == "主板" and universe.sina_symbol(item["code"]) == symbol
                and not universe.is_st(item["name"]) and (not config.require_factors or (item.get("factors") or {}).get("passed"))):
            result.append((symbol, " / ".join(research.STRATEGIES[key]["label"] for key in matches)))
    return result


def _trading(moment):
    return moment.weekday() < 5 and (time(9, 30) <= moment.time() < time(11, 30)
                                     or time(13) <= moment.time() < time(14, 57))


def _closing(moment):
    return moment.weekday() < 5 and time(15, 2) <= moment.time() < time(15, 20)


def _entries_open(moment, account):
    return (account.running and account.entry_day != moment.date().isoformat()
            and ENTRY_START <= moment.time() < ENTRY_END and _trading(moment))


def _fresh(quote, moment, closing=False):
    if not quote or quote.at.date() != moment.date() or quote.volume <= 0:
        return False
    if closing:
        # 收盘后股价快照可以停止刷新；必须明确包含当日收盘。
        return CLOSE <= quote.at.time() and quote.at <= moment
    return 0 <= (moment - quote.at).total_seconds() <= MAX_QUOTE_AGE and _trading(quote.at)


def _fee(value, config, selling=False):
    gross = Decimal(value)
    commission = max(cents(config.min_commission), (gross * Decimal(str(config.commission_pct)) / 100)
                     .quantize(Decimal("1"), rounding=ROUND_HALF_UP))
    other_rate = Decimal(str(config.slippage_pct)) / 100 + (Decimal(str(SELL_TAX)) if selling else 0)
    return int(commission + (gross * other_rate).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def _exit(position, config, quote, sessions):
    if position.exit_reason:
        return position.exit_reason
    pnl = 100 * (quote.last * position.shares / position.cost_cents - 1)
    if config.stop_loss_pct and pnl <= -config.stop_loss_pct:
        return "止损"
    if config.take_profit_pct and pnl >= config.take_profit_pct:
        return "止盈"
    if sum(day > position.opened_at.date().isoformat() for day in sessions) >= config.hold_days:
        return "达到持有期限"
    return None


def _sell(db, account, position, quote, config, sessions, moment):
    if (position.opened_at.date() >= moment.date() or quote.status != "00" or quote.at < account.enabled_at
            or (position.last_fill_quote_at and quote.at <= position.last_fill_quote_at)):
        return 0
    position.exit_reason = _exit(position, config, quote, sessions)
    shares = min(position.shares, quote.bid_size // LOT_SIZE * LOT_SIZE)
    if not position.exit_reason or shares <= 0 or quote.bid <= 0 or (quote.ask and quote.bid > quote.ask):
        return 0
    value = quote.bid * shares
    fees = _fee(value, config, selling=True)
    if fees >= value:
        return 0
    basis = position.cost_cents * shares // position.shares
    proceeds = value - fees
    account.cash_cents += proceeds
    db.add(StockSimTrade(user_id=account.user_id, symbol=position.symbol, name=position.name, side="sell",
                         shares=shares, price_cents=quote.bid, fees_cents=fees, realized_cents=proceeds - basis,
                         reason=position.exit_reason, filled_at=moment, quoted_at=quote.at))
    position.cost_cents -= basis
    position.shares -= shares
    position.last_fill_quote_at = quote.at
    if not position.shares:
        db.delete(position)
    return proceeds


def _buy(db, account, config, ranked, positions, quotes, equity, cash, previous_day, moment):
    skipped = Counter()
    count = 0
    held = {row.symbol for row in positions}
    if not ranked:
        account.entry_day = moment.date().isoformat()
        return "上一交易日没有满足所选策略条件的候选。"
    ready = {symbol: quotes[symbol] for symbol, _ in ranked if symbol in quotes
             and _fresh(quotes[symbol], moment) and quotes[symbol].at >= account.enabled_at}
    if not ready:
        return "等待候选的当日有效报价。"

    for symbol, strategy in ranked:
        if symbol in held:
            skipped["已持有"] += 1
            continue
        if len(held) >= config.max_positions:
            skipped["持仓已满"] += 1
            continue
        quote = ready.get(symbol)
        if (not quote or quote.status != "00" or universe.is_st(quote.name)
                or quote.ask <= 0 or quote.ask_size < LOT_SIZE or (quote.bid and quote.bid > quote.ask)):
            skipped["无可用卖盘"] += 1
            continue
        if quote.ask < cents(config.price_min) or (config.price_max is not None and quote.ask > cents(config.price_max)):
            skipped["超出股价区间"] += 1
            continue
        budget = min(cash, int(equity * config.max_position_pct / 100))
        lot_value = quote.ask * LOT_SIZE
        lots = min(budget // lot_value, quote.ask_size // LOT_SIZE)
        while lots and lots * lot_value + _fee(lots * lot_value, config) > budget:
            lots -= 1
        if lots <= 0:
            skipped["资金不足一手"] += 1
            continue
        shares = lots * LOT_SIZE
        value = quote.ask * shares
        fees = _fee(value, config)
        spent = value + fees
        account.cash_cents -= spent
        cash -= spent
        position = StockSimPosition(user_id=account.user_id, symbol=symbol, name=quote.name, shares=shares,
                                    cost_cents=spent, mark_cents=quote.last, marked_at=quote.at, opened_at=moment)
        db.add(position)
        positions.append(position)
        held.add(symbol)
        db.add(StockSimTrade(user_id=account.user_id, symbol=symbol, name=quote.name, side="buy",
                             shares=shares, price_cents=quote.ask, fees_cents=fees, reason=strategy,
                             signal_day=previous_day, filled_at=moment, quoted_at=quote.at))
        count += 1
    account.entry_day = moment.date().isoformat()
    notes = "、".join(f"{reason} {total}" for reason, total in skipped.items())
    return f"本日入场已检查，模拟买入 {count} 只。" + (f"跳过 {notes}。" if notes else "")


def _process(db, account, positions, config, quotes, sessions, moment, ranked, closing):
    day = moment.date().isoformat()
    state = db.get(StockSimEquity, (account.user_id, day))
    if state and (state.final_mark or moment <= state.marked_at):
        return
    available = account.cash_cents
    fresh = {symbol: quote for symbol, quote in quotes.items() if _fresh(quote, moment, closing)}
    prior_positions = positions.copy()
    for position in prior_positions:
        quote = fresh.get(position.symbol)
        if not quote:
            continue
        if quote.at >= position.marked_at:
            position.mark_cents, position.marked_at = quote.last, quote.at
        if account.running and not closing and account.enabled_at and quote.at >= position.marked_at:
            _sell(db, account, position, quote, config, sessions, moment)
            if not position.shares:
                positions.remove(position)

    def value():
        return account.cash_cents + sum(row.mark_cents * row.shares for row in positions)

    stale = sum(row.symbol not in fresh or row.marked_at != fresh[row.symbol].at for row in positions)
    equity = value()
    if not stale:
        account.peak_cents = max(account.peak_cents, equity)
    drawdown = max(0.0, (1 - equity / account.peak_cents) * 100)

    if _entries_open(moment, account) and account.enabled_at and moment >= account.enabled_at:
        if config.max_drawdown_pct and drawdown >= config.max_drawdown_pct:
            account.message = "达到组合回撤阈值，本轮暂停新买入。"
        elif stale:
            account.message = "持仓报价不齐，本轮等待最新行情。"
        elif ranked is None:
            account.message = "等待上一交易日、相同股价区间的完整收盘候选。"
        else:
            # 本轮卖出所得下一次检查才进入买入预算，同一轮退出的股票不会反向买回。
            candidates = [(symbol, label) for symbol, label in ranked
                          if not any(row.symbol == symbol and not row.shares for row in prior_positions)]
            account.message = _buy(db, account, config, candidates, positions, fresh,
                                   equity, available, sessions[-2] if len(sessions) > 1 else None, moment)
    elif not closing and account.running and account.message == "已启动，等待下一个行情检查。":
        account.message = "行情监控已运行，等待次日入场窗口。" if moment.time() >= ENTRY_END else "行情监控已运行，等待 09:35 入场窗口。"

    account.checked_at = moment
    equity = value()
    if not stale:
        account.max_drawdown_pct = max(account.max_drawdown_pct, (1 - equity / account.peak_cents) * 100)
    if state is None:
        state = StockSimEquity(user_id=account.user_id, trade_day=day)
        db.add(state)
    state.cash_cents, state.equity_cents, state.stale_positions = account.cash_cents, equity, stale
    state.marked_at = moment
    bench = fresh.get(BENCHMARK)
    if bench:
        state.benchmark = bench.last / 100
        if state.first_benchmark is None:
            state.first_benchmark = state.benchmark
    state.final_mark = closing and not stale


def run_cycle():
    moment = now_local()
    if not (_trading(moment) or _closing(moment)):
        return
    with SessionLocal() as db:
        ids = set(db.scalars(select(StockSimAccount.user_id).where(StockSimAccount.running))) | set(
            db.scalars(select(StockSimPosition.user_id).distinct()))
    if not ids:
        return
    today = moment.date().isoformat()
    if fetch_market_trade_date() != today:
        return
    try:
        dates = [day for day, _ in research.history(BENCHMARK) if day < today]
    except Exception:
        logger.exception("模拟盘交易日历读取失败")
        return
    if not dates:
        return
    sessions = [*dates, today]
    symbols = {BENCHMARK}
    with SessionLocal() as db:
        for user_id in ids:
            account = db.get(StockSimAccount, user_id)
            if not account:
                continue
            symbols.update(row.symbol for row in _positions(db, user_id))
            if _entries_open(moment, account):
                config = StockSimConfig.model_validate_json(account.config_json)
                symbols.update(symbol for symbol, _ in _signals(db, config, dates[-1]) or [])
    quotes = fetch(symbols)
    moment = now_local()
    closing = _closing(moment)
    if moment.date().isoformat() != today or not (closing or _trading(moment)):
        return
    for user_id in ids:
        with _lock, SessionLocal() as db:
            account = db.get(StockSimAccount, user_id)
            if not account:
                continue
            positions = _positions(db, user_id)
            if not account.running and not positions:
                continue
            config = StockSimConfig.model_validate_json(account.config_json)
            ranked = _signals(db, config, dates[-1]) if _entries_open(moment, account) else None
            _process(db, account, positions, config, quotes, sessions, moment, ranked, closing)
            db.commit()


def view(db, user_id, period):
    account = db.get(StockSimAccount, user_id)
    if not account:
        return {"account": None}
    config = StockSimConfig.model_validate_json(account.config_json)
    start = cents(config.starting_cash)
    positions = _positions(db, user_id)
    market = sum(row.mark_cents * row.shares for row in positions)
    equity = market + account.cash_cents
    series = select(StockSimEquity).where(StockSimEquity.user_id == user_id)
    trades = select(StockSimTrade).where(StockSimTrade.user_id == user_id)
    prior = None
    if period != "all":
        cutoff = now_local().date() - timedelta(days=int(period) - 1)
        prior = db.scalar(series.where(StockSimEquity.trade_day < cutoff.isoformat())
                          .order_by(StockSimEquity.trade_day.desc()).limit(1))
        series = series.where(StockSimEquity.trade_day >= cutoff.isoformat())
        trades = trades.where(StockSimTrade.filled_at >= datetime.combine(cutoff, time.min))
    points = list(db.scalars(series.order_by(StockSimEquity.trade_day)))
    trade_rows = list(db.scalars(trades.order_by(StockSimTrade.id.desc()).limit(100)))
    ledger = trades.subquery()
    count, realized, fees = db.execute(select(func.count(), func.sum(ledger.c.realized_cents), func.sum(ledger.c.fees_cents))).one()
    first_benchmark = prior.benchmark if prior else next((row.first_benchmark for row in points if row.first_benchmark), None)
    last_benchmark = points[-1].benchmark if points else None
    base = prior.equity_cents if prior else start
    high, drawdown = base, 0.0
    for row in points:
        high = max(high, row.equity_cents)
        drawdown = max(drawdown, (1 - row.equity_cents / high) * 100)
    return {
        "account": {"running": account.running, "config": config.model_dump(), "created_at": account.created_at,
                    "checked_at": account.checked_at, "entry_day": account.entry_day, "message": account.message,
                    "cash": account.cash_cents / 100, "equity": equity / 100, "market_value": market / 100,
                    "return_pct": round((equity / start - 1) * 100, 2), "max_drawdown_pct": round(account.max_drawdown_pct, 2)},
        "period": {"base_equity": base / 100, "trade_count": count, "fees": (fees or 0) / 100,
                   "realized": (realized or 0) / 100, "return_pct": round((points[-1].equity_cents / base - 1) * 100, 2) if points and base > 0 else None,
                   "max_drawdown_pct": round(drawdown, 2) if points else None,
                   "benchmark_pct": round((last_benchmark / first_benchmark - 1) * 100, 2) if first_benchmark and last_benchmark else None},
        "positions": [{"symbol": row.symbol, "code": row.symbol[2:], "name": row.name, "shares": row.shares,
                       "avg_cost": round(row.cost_cents / row.shares / 100, 3), "price": row.mark_cents / 100,
                       "market_value": row.shares * row.mark_cents / 100, "pnl": (row.shares * row.mark_cents - row.cost_cents) / 100,
                       "marked_at": row.marked_at, "opened_at": row.opened_at, "exit_reason": row.exit_reason} for row in positions],
        "curve": [{"date": row.trade_day, "equity": row.equity_cents / 100, "stale_positions": row.stale_positions,
                   "final_mark": row.final_mark} for row in points],
        "trades": [{"id": row.id, "code": row.symbol[2:], "name": row.name, "side": row.side, "shares": row.shares,
                    "price": row.price_cents / 100, "fees": row.fees_cents / 100,
                    "realized": row.realized_cents / 100 if row.realized_cents is not None else None,
                    "reason": row.reason, "signal_day": row.signal_day, "filled_at": row.filled_at,
                    "quoted_at": row.quoted_at} for row in trade_rows],
    }
