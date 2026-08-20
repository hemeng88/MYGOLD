"""浙商积存金手续费保本公式。

现行常见规则（京东金融 / 支付宝代销，以 App 公示为准）：
- 买入手续费 0
- 卖出按成交金额收取 sell_fee_rate（默认 0.4%）
- 买卖一般使用同一报价

保本卖出价 S 满足：S * (1 - f) = P
因此 S = P / (1 - f)
相对买入价需上涨：breakeven_rate = f / (1 - f)
"""

from .config import settings


def breakeven_rate(sell_fee_rate=None):
    fee = settings.sell_fee_rate if sell_fee_rate is None else sell_fee_rate
    if fee >= 1:
        raise ValueError("手续费率必须小于 1")
    return fee / (1.0 - fee)


def breakeven_sell_price(buy_price, sell_fee_rate=None):
    return round(float(buy_price) / (1.0 - (settings.sell_fee_rate if sell_fee_rate is None else sell_fee_rate)), 2)


def needed_rise_amount(buy_price, sell_fee_rate=None):
    price = float(buy_price)
    return round(breakeven_sell_price(price, sell_fee_rate) - price, 2)


def change_rate(start_price, end_price):
    start = float(start_price)
    if start == 0:
        return 0.0
    return (float(end_price) - start) / start


def rule_payload(buy_price=None):
    fee = settings.sell_fee_rate
    rate = breakeven_rate(fee)
    payload = {
        "sell_fee_rate": fee,
        "breakeven_rate": round(rate, 8),
        "breakeven_rate_pct": round(rate * 100, 4),
        "formula": "S = P / (1 - f)，保本涨幅 = f / (1 - f)",
        "note": "买入 0 费率、卖出按金额抽 f。金价相对买入价持续涨/跌超过保本涨幅时记为有效波动。",
        "watch_window_seconds": settings.move_window_seconds,
        "persist_checks": settings.move_persist_checks,
        "tick_interval_seconds": settings.tick_interval_seconds,
    }
    if buy_price is not None:
        payload["example_buy_price"] = float(buy_price)
        payload["example_breakeven_sell"] = breakeven_sell_price(buy_price, fee)
        payload["example_needed_rise"] = needed_rise_amount(buy_price, fee)
    return payload
