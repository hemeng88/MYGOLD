from datetime import datetime, timedelta
import unittest
from unittest.mock import patch, MagicMock

import httpx

from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from backend.app.database import Base
from backend.app.models import StrategyObservation
from backend.app.stocks import research, paper


def series(count=220):
    start = datetime(2025, 12, 1)
    out = []
    while len(out) < count:
        if start.weekday() < 5:
            out.append((start.date().isoformat(), 10 * 1.001 ** len(out)))
        start += timedelta(days=1)
    return out


class ResearchTests(unittest.TestCase):
    def test_negative_and_cost_sensitive_results_do_not_pass_evidence_gate(self):
        base = dict(trades=50, avg_net_pct=1, double_cost_pct=0.5, avg_excess_pct=0.2)
        self.assertEqual(research.evidence_status(base), "待前向验证")
        self.assertEqual(research.evidence_status(dict(base, trades=2)), "样本不足")
        self.assertEqual(research.evidence_status(dict(base, avg_net_pct=-1)), "样本外净收益非正")
        self.assertEqual(research.evidence_status(dict(base, double_cost_pct=-0.1)), "成本敏感")
        self.assertEqual(research.evidence_status(dict(base, avg_excess_pct=-0.1)), "未跑赢基准")
    def test_history_waf_failure_uses_adjusted_mirror_and_caches(self):
        calls = []
        def handler(request):
            calls.append(str(request.url))
            if request.url.host == "web.ifzq.gtimg.cn":
                return httpx.Response(501, text="waf")
            return httpx.Response(200, json={"data": {"sz000823": {"qfqday": [["2026-11-25", "10", "10.5"]]}}})
        with patch.object(research, "_cache", {}), patch.object(research, "_preferred_url", None), \
                patch.object(research, "now_local", return_value=datetime(2026, 11, 26)):
            transport = httpx.MockTransport(handler)
            self.assertEqual(research.history("sz000823", transport), [("2026-11-25", 10.5)])
            self.assertEqual(research.history("sz000823", transport), [("2026-11-25", 10.5)])
            self.assertEqual(len(calls), 2)

    def test_research_pipeline_includes_history_metrics_and_balanced_candidates(self):
        bars = series()
        moment = datetime.fromisoformat(bars[-1][0]) + timedelta(days=1)
        item = {"code": "000823", "symbol": "sz000823", "board": "主板", "amount": 1000}
        with patch.object(research, "now_local", return_value=moment):
            items, report, histories = research.build_research([item], moment.date().isoformat(), loader=lambda symbol: bars)
        self.assertEqual(report["sample_usable"], 1)
        self.assertEqual(report["history_failed"], 0)
        self.assertTrue(report["benchmark_available"])
        self.assertEqual(items[0]["code"], "000823")
        self.assertEqual(items[0]["historical_as_of"], bars[-1][0])
        self.assertEqual(len(report["strategies"]), 3)
        self.assertTrue(report["strategies"][0]["test"]["trades"])

    def test_history_excludes_current_day_and_bad_prices(self):
        rows = [("2026-11-24", 9), ("2026-11-25", 10), ("2026-11-26", 20),
                ("2026-11-27", 50), ("2026-99-99", 10), ("2026-11-23", float("nan"))]
        self.assertEqual(research.clean_bars(rows, "2026-11-26"), rows[:2])

    def test_no_unadjusted_stock_fallback(self):
        response = MagicMock()
        response.json.return_value = {"data": {"sz000823": {"day": [["2026-11-25", 10, 10]]}}}
        with patch.object(research, "_cache", {}), patch.object(research.httpx, "Client") as client:
            client.return_value.__enter__.return_value.get.return_value = response
            self.assertEqual(research.history("sz000823"), [])

    def test_hypotheses_are_distinct(self):
        base = dict(last=11, ma20=10, ma60=9, return10=0.05, return5=0.01, vol20=0.03)
        self.assertEqual(research.triggers(base), ["trend"])
        self.assertEqual(research.triggers(dict(base, last=9.9, return5=-0.02)), ["pullback"])
        self.assertEqual(research.triggers(dict(base, last=10, vol20=0.01)), ["low_vol"])

    def test_events_enter_next_day_hold_five_and_do_not_cross_split(self):
        bars = series()
        benchmark = dict(bars)
        split = bars[140][0]
        result = research.event_study(bars, "trend", split, benchmark)
        self.assertTrue(result["train"])
        self.assertTrue(result["test"])
        for part, events in result.items():
            previous_exit = ""
            for event in events:
                index = [day for day, _ in bars].index(event["signal_date"])
                self.assertEqual(event["entry_date"], bars[index + 1][0])
                self.assertEqual(event["exit_date"], bars[index + 6][0])
                self.assertGreater(event["signal_date"], previous_exit)
                previous_exit = event["exit_date"]
                if part == "train":
                    self.assertLess(event["exit_date"], split)
                else:
                    self.assertGreaterEqual(event["signal_date"], split)

    def test_future_changes_do_not_change_earlier_events(self):
        bars = series()
        result = research.event_study(bars, "trend", bars[140][0], dict(bars))
        changed = bars[:100] + [(day, price * 2) for day, price in bars[100:]]
        second = research.event_study(changed, "trend", bars[140][0], dict(bars))
        original_early = [row for row in result["train"] if row["exit_date"] < bars[100][0]]
        changed_early = [row for row in second["train"] if row["exit_date"] < bars[100][0]]
        self.assertEqual(original_early, changed_early)

    def test_cost_and_benchmark_comparison(self):
        self.assertLess(research.net_return(10, 10), 0)
        self.assertLess(research.net_return(10, 11, 2), research.net_return(10, 11))
        bars = series()
        events = research.event_study(bars, "trend", bars[140][0], dict(bars))["test"]
        metrics = research.summarize(events)
        self.assertLess(metrics["avg_excess_pct"], 0)
        self.assertEqual(metrics["benchmark_trades"], metrics["trades"])
        self.assertIsNone(research.summarize([])["avg_net_pct"])

    def test_missing_trading_day_does_not_fake_execution(self):
        bars = series()
        removed_day = bars[60][0]
        modified = bars[:60] + bars[61:]
        result = research.event_study(modified, "trend", bars[140][0], dict(bars))
        first_signal = bars[59][0]
        self.assertFalse(any(row["signal_date"] == first_signal for row in result["train"]))

    def test_board_sampling_and_strategy_slots_are_balanced(self):
        items = [{"code": str(i), "board": board, "amount": 1000 - i} for i, board in enumerate(["主板"] * 20 + ["北交所"] * 2)]
        sample = research.stratified_sample(items, 4)
        self.assertEqual([row["board"] for row in sample].count("北交所"), 2)
        groups = {"trend": [{"code": "a", "amount": 100}, {"code": "b", "amount": 90}],
                  "pullback": [{"code": "c", "amount": 80}], "low_vol": [{"code": "a", "amount": 100}, {"code": "d", "amount": 60}]}
        selected = research.balanced_candidates(groups, 3)
        self.assertEqual([row["code"] for row in selected], ["a", "c", "d"])


class PaperTests(unittest.TestCase):
    def test_first_observation_preserved_then_evaluated_with_future_data(self):
        engine = create_engine("sqlite://")
        Base.metadata.create_all(engine)
        signal_date = "2026-11-02"
        snapshot = {"complete": True, "trade_date": signal_date, "items": [
            {"code": "000823", "symbol": "sz000823", "price": 10, "strategies": ["trend"]}]}
        with Session(engine) as db:
            with patch.object(paper, "now_local", return_value=datetime(2026, 11, 2, 10)):
                self.assertEqual(paper.update(db, snapshot, {})["pending"], 1)
                snapshot["items"][0]["price"] = 15
                paper.update(db, snapshot, {})
                self.assertEqual(db.scalar(select(StrategyObservation)).reference_price, 10)
            future = [("2026-11-%02d" % day, price) for day, price in [(3, 10), (4, 11), (5, 11), (6, 11), (9, 11), (10, 12)]]
            with patch.object(paper, "now_local", return_value=datetime(2026, 11, 11, 10)):
                result = paper.update(db, {"complete": False, "items": []}, {"sz000823": future, "sh000300": future})
            row = db.scalar(select(StrategyObservation))
            self.assertEqual(row.entry_date, "2026-11-03")
            self.assertEqual(row.exit_date, "2026-11-10")
            self.assertAlmostEqual(row.net_pct, round(research.net_return(10, 12) * 100, 3))
            self.assertEqual(result["completed"], 1)
        engine.dispose()


if __name__ == "__main__":
    unittest.main()
