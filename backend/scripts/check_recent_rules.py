#!/usr/bin/env python3
"""拉取当前规则样本及近期日线，保存技术规则事件研究与可交给AI的摘要。

在项目根目录运行：python backend/scripts/check_recent_rules.py
不调用收费模型、不修改账号/持仓/每日归档，也不把结果冒充完整组合策略回测。
"""
import argparse
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.config import DATA_DIR
from app.stocks import research, signals
from app.timeutil import now_local


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=DATA_DIR / "historical_checks" / now_local().date().isoformat())
    args = parser.parse_args()
    captured = {}

    def build(items, trade_date):
        sample = research.stratified_sample(items, research.settings.stock_research_sample_size)
        print("主板有效报价 %d 只，按当前取样规则研究 %d 只" % (len(items), len(sample)), flush=True)
        selected, report, histories = research.build_research(
            items, trade_date, progress=lambda count: print("日线已取得 %d 个结果" % count, flush=True) if count % 10 == 0 else None)
        captured.update(sample=sample, histories=histories)
        return selected, report, histories

    snapshot = signals.scan_market(
        allowed_boards=["主板"], research_builder=build,
        progress=lambda count: print("市场快照已读取 %d 只" % count, flush=True) if count % 400 == 0 else None)
    report = snapshot["research"]
    coverage = {
        "full_rule_backtest": False,
        "tested": ["趋势延续", "趋势回调", "低波动观察"],
        "not_replayed": ["历史当日全市场成交额取样及20只平衡候选", "按当时披露版本的财务数据", "历史行业分类与行业当日强弱", "全市场历史上涨家数和大盘环境", "AI当时的判断", "真实委托成交"],
        "note": "当前活跃主板样本的技术事件研究，存在幸存者和选择偏差；不是当前完整筛选规则的历史胜率。",
    }
    args.output.mkdir(parents=True, exist_ok=True)
    payload = {"generated_at": now_local().isoformat(), "coverage": coverage, "snapshot": snapshot, **captured}
    (args.output / "data_and_results.json").write_text(json.dumps(payload, ensure_ascii=False, indent=2, allow_nan=False))
    ai_input = {"task": "仅解读程序计算的技术事件统计，不得声称是完整规则或未来胜率；说明样本量、成本和样本外表现。",
                "coverage": coverage, "market_snapshot_complete": snapshot["complete"], "errors": snapshot["errors"], "research": report}
    (args.output / "ai_input.json").write_text(json.dumps(ai_input, ensure_ascii=False, indent=2, allow_nan=False))
    print(json.dumps({"output": str(args.output.resolve()), "market_snapshot_complete": snapshot["complete"],
                      "errors": snapshot["errors"], "sample_usable": report["sample_usable"],
                      "history_start": report["history_start"], "history_end": report["history_end"],
                      "split_date": report["split_date"], "strategies": report["strategies"]}, ensure_ascii=False, indent=2), flush=True)
    return 0 if snapshot["complete"] and report["sample_usable"] and report["benchmark_available"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
