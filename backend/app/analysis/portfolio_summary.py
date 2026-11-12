"""按数据库里的实际持仓汇总账号整体收益。

消息和网页必须复用 fund_estimate 的单项口径，不能在通知里写死基金代码或另算一套。
这里会自动纳入指定账号 fund_favorites 中所有 shares/cost_price 有效的基金和股票。
"""

from __future__ import annotations

from typing import Dict, List, Optional

from sqlalchemy.orm import Session

from .fund_estimate import list_funds


def _number(value) -> Optional[float]:
    return float(value) if isinstance(value, (int, float)) else None


def portfolio_summary(db: Session, user_id: int, trade_date: Optional[str] = None) -> Dict:
    """汇总指定账号的全部数据库持仓。

    当日收益率 = 有当日盈亏项目的 Σ今日盈亏 / Σ前一交易日市值。
    累计收益率 = 有完整成本和现值项目的 Σ累计盈亏 / Σ成本。

    两个分母都只纳入对应数据完整的项目，避免把缺数据项目只塞进分母。
    传 trade_date 时，还会要求当日收益所依据的报价/官方净值就是这一天，
    防止收盘刷新失败后拿数据库里昨天的涨跌冒充今天。
    返回覆盖数量，让消息明确告诉用户是否算全。
    """
    rows: List[Dict] = list_funds(db, user_id).get("items") or []
    positions = [row for row in rows if (_number(row.get("shares")) or 0) > 0]

    cumulative_rows = []
    daily_rows = []
    for row in positions:
        shares = _number(row.get("shares"))
        cost_price = _number(row.get("cost_price"))
        cost = shares * cost_price if shares and cost_price and cost_price > 0 else None
        current_value = _number(row.get("estimate_value"))
        if current_value is None:
            current_value = _number(row.get("nav_value"))
        today_pnl = _number(row.get("today_pnl"))
        data_date = row.get("_trade_date")
        if trade_date is not None and data_date != trade_date:
            # 行情不是今天就不能把旧涨跌当今日收益。唯一例外是基金今天已经公布了
            # 官方净值：无股票持仓的货币/债券基金也能据官方字段补出今日盈亏。
            today_pnl = None
            if row.get("asset_type") == "fund" and row.get("nav_date") == trade_date:
                official_pct = _number(row.get("nav_chg_pct"))
                yield_10k = _number(row.get("yield_10k"))
                if row.get("is_cash_fund") and shares and yield_10k is not None:
                    today_pnl = shares * yield_10k / 10000.0
                elif current_value is not None and official_pct is not None and official_pct > -100:
                    today_pnl = current_value - current_value / (1 + official_pct / 100.0)

        if cost is not None and cost > 0 and current_value is not None:
            # 用数据库里的原始份额×成本价，不沿用页面为了展示而逐项四舍五入到整元的 cost。
            cumulative_rows.append((row, cost, current_value, current_value - cost))
        if current_value is not None and today_pnl is not None:
            previous_value = current_value - today_pnl
            if previous_value > 0:
                daily_rows.append((row, previous_value, today_pnl))

    total_cost = sum(item[1] for item in cumulative_rows)
    total_value = sum(item[2] for item in cumulative_rows)
    total_pnl = sum(item[3] for item in cumulative_rows)
    previous_value = sum(item[1] for item in daily_rows)
    today_pnl = sum(item[2] for item in daily_rows)

    return {
        "position_count": len(positions),
        "cumulative_count": len(cumulative_rows),
        "daily_count": len(daily_rows),
        "total_cost": round(total_cost, 2) if cumulative_rows else None,
        "total_value": round(total_value, 2) if cumulative_rows else None,
        "today_pnl": round(today_pnl, 2) if daily_rows else None,
        "daily_return_pct": round(today_pnl / previous_value * 100, 3)
        if previous_value > 0
        else None,
        "total_pnl": round(total_pnl, 2) if cumulative_rows else None,
        "total_return_pct": round(total_pnl / total_cost * 100, 3) if total_cost > 0 else None,
    }


def format_close_report(summary: Dict, gold_price: Optional[float], trade_date: str) -> str:
    """生成确定性的飞书正文。OpenClaw 只负责原样投递，不参与计算或改写数字。"""
    daily = summary.get("daily_return_pct")
    total = summary.get("total_return_pct")
    lines = [
        "交易日：%s" % trade_date,
        "整体当日收益率：%s" % ("—" if daily is None else "%+.2f%%" % daily),
        "整体累计收益率：%s" % ("—" if total is None else "%+.2f%%" % total),
        "实时金价：%s" % ("获取失败" if gold_price is None else "%.2f 元/克（浙商积存金）" % gold_price),
    ]
    position_count = int(summary.get("position_count") or 0)
    daily_count = int(summary.get("daily_count") or 0)
    cumulative_count = int(summary.get("cumulative_count") or 0)
    if daily_count < position_count or cumulative_count < position_count:
        lines.append(
            "数据覆盖：当日 %d/%d 只，累计 %d/%d 只"
            % (daily_count, position_count, cumulative_count, position_count)
        )
    return "\n".join(lines)
