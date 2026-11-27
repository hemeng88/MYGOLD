"""针对账号已填报的 A 股持仓计算退出参考，并按需交给模型复核。"""
from decimal import Decimal, localcontext, ROUND_HALF_UP
import hashlib
import json
from math import isfinite

from ..market_session import session_label
from . import deepseek, single_stock, universe

LOSS_RATE = Decimal("0.05")
PROFIT_RATE = Decimal("0.10")
ATR_MULTIPLE = Decimal("2.5")
TICK = Decimal("0.01")


def position_values(favorite):
    secid = favorite.secid
    code = secid.split(".")[-1] if secid else ""
    if favorite.asset_type != "stock" or not secid or secid != universe.secid_of(code):
        raise ValueError("持仓分析仅适用于基金估值里的 A 股股票。")
    shares, cost = favorite.shares, favorite.cost_price
    if (shares is None or cost is None or not isfinite(shares) or not isfinite(cost)
            or shares <= 0 or cost <= 0 or not isfinite(shares * cost)):
        raise ValueError("请先为这只股票保存有效的持仓股数和成本价。")
    return {"code": code, "secid": secid, "shares": shares, "cost_price": cost}


def _at_price(price, shares, cost):
    price = Decimal(str(price))
    shares, cost = Decimal(str(shares)), Decimal(str(cost))
    cash_pnl = float((price - cost) * shares)
    pct = float((price / cost - 1) * 100)
    numeric_price = float(price)
    if not all(map(isfinite, (numeric_price, cash_pnl, pct))):
        raise ValueError("持仓数据超出可计算范围，请核对股数和成本价。")
    return {"price": numeric_price, "pnl": round(cash_pnl, 2), "pnl_pct": round(pct, 2)}


def _plan(position, reference):
    cost = Decimal(str(position["cost_price"]))
    stop = cost * (1 - LOSS_RATE)
    target = cost * (1 + PROFIT_RATE)
    atr, recent_high = None, None
    if reference:
        window, atr, _ = reference
        atr = Decimal(str(atr))
        recent_high = max(row[2] for row in window)
        trailing = Decimal(str(max(row[1] for row in window))) - ATR_MULTIPLE * atr
        stop = max(stop, trailing)
        target = max(target, Decimal(str(recent_high)), stop + atr)
    with localcontext() as context:
        context.prec = max(28, stop.adjusted() + 4, target.adjusted() + 4)
        stop = max(TICK, stop.quantize(TICK, rounding=ROUND_HALF_UP))
        target = max(stop + TICK, target.quantize(TICK, rounding=ROUND_HALF_UP))
    return {
        "stop": _at_price(stop, position["shares"], cost),
        "take_profit": _at_price(target, position["shares"], cost),
        "atr14": round(float(atr), 3) if atr is not None else None,
        "recent_high": round(recent_high, 2) if recent_high is not None else None,
        "cost_loss_pct": int(LOSS_RATE * 100), "cost_profit_pct": int(PROFIT_RATE * 100),
        "atr_multiple": float(ATR_MULTIPLE) if reference else None,
    }


def build_snapshot(position, position_id):
    market = single_stock.load_market(position["code"])
    if market["secid"] != position["secid"]:
        raise LookupError("持仓的证券标识与行情不一致，请重新查询。")
    moment, raw, quote = market["moment"], market["raw"], market["quote"]
    today = moment.date().isoformat()
    quoted_today = bool(quote and market["market_date"] == today)
    open_now = session_label(moment) == "开盘中"
    current = bool(quoted_today and open_now and quote["status"] == "00" and (quote.get("volume") or 0) > 0
                   and 0 <= (moment - quote["at"]).total_seconds() <= 300)
    aligned = bool(raw and (not quoted_today or market["completed_today"] or
                            (quote.get("prev_close") and abs(quote["prev_close"] / raw[-1][1] - 1) <= .005)))
    if market["completed_today"] and raw and raw[-1][0] != today:
        aligned = False
    current = current and aligned
    reference = single_stock.price_window(raw, market["daily"]) if aligned else None
    use_quote = quote and not (raw and market["completed_today"] and raw[-1][0] == today)
    price = quote["price"] if use_quote else raw[-1][1] if raw else None
    quote_at = quote["at"].isoformat() if use_quote else None
    as_of = quote["at"].date().isoformat() if use_quote else raw[-1][0] if raw else None
    plan = _plan(position, reference)

    pnl = _at_price(price, position["shares"], position["cost_price"]) if price is not None else None
    signal = "reference"
    if current:
        if price <= plan["stop"]["price"]:
            signal = "stop_hit"
        elif price >= plan["take_profit"]["price"]:
            signal = "target_hit"
        else:
            signal = "between"
    if not current:
        if quoted_today and not aligned:
            note = "昨收和日线口径未对齐，等待核实除权或行情更新。"
        elif open_now:
            note = "缺少当日有效报价，本次价位仅作参考。"
        else:
            note = "当前以最近可用价格回顾持仓，开盘后再确认触发状态。"
    else:
        note = {"stop_hit": "有效报价已触及止损参考。", "target_hit": "有效报价已触及止盈参考。",
                "between": "有效报价尚未触及退出参考线。"}[signal]
    buy_book = None
    if current and quote.get("bid") is not None and quote.get("bid_size") is not None:
        buy_book = max(0, quote["bid_size"]) if quote["bid"] > 0 else 0
    stats = market["stats"]
    item = {"code": position["code"], "symbol": market["symbol"], "name": market["name"], "board": market["board"],
            "price": price, "quote_time": quote_at, "historical_as_of": raw[-1][0] if raw else None,
            "factors": {"fundamentals": market["financial"]}}
    if stats:
        item.update(return5_pct=round(stats["return5"] * 100, 2), return10_pct=round(stats["return10"] * 100, 2),
                    vol20_pct=round(stats["vol20"] * 100, 2))
        if reference:
            item.update(ma20=round(stats["ma20"] * reference[2], 3), ma60=round(stats["ma60"] * reference[2], 3))
    holding = {**position, "name": market["name"], "signal": signal, "signal_note": note, "plan": plan,
               "price": price, "pnl": pnl, "price_date": as_of, "quote_at": quote_at, "current": current,
               "price_source": quote["source"] if use_quote else "腾讯未复权收盘价" if raw else None,
               "basis_date": raw[-1][0] if reference else None, "visible_buy_shares": buy_book}
    position_signature = hashlib.sha256(json.dumps([position_id, position], sort_keys=True).encode()).hexdigest()
    snapshot = {"mode": "holding", "complete": True, "trade_date": market["market_date"],
                "fetched_at": moment.isoformat(), "items": [item], "holding": holding, "_position_id": position_id,
                "_holding_scope": f"holding:{position['secid']}:{position_signature}"}
    snapshot["snapshot_id"] = deepseek.snapshot_id(snapshot)
    return snapshot


def create_preview(user_id, favorite):
    return single_stock.store_preview(user_id, build_snapshot(position_values(favorite), favorite.id))


def saved_preview(user_id, favorite, snapshot_id):
    current = position_values(favorite)
    snapshot = single_stock.saved_preview(user_id, current["code"], snapshot_id, mode="holding")
    if snapshot["_position_id"] != favorite.id or any(snapshot["holding"][key] != value for key, value in current.items()):
        raise LookupError("持仓已变化，请刷新持仓分析后再试。")
    return snapshot


def view(snapshot, profiles, selected=()):
    states = deepseek.profile_results(snapshot, profiles, selected, snapshot)
    issue = deepseek.snapshot_issue(snapshot)
    holding = dict(snapshot["holding"])
    if issue and holding["current"]:
        holding.update(signal="reference", signal_note=issue, current=False, visible_buy_shares=None)
    return {**holding, "snapshot_id": snapshot["snapshot_id"], "can_analyze": not issue, "analysis_issue": issue,
            "ai_results": states}
