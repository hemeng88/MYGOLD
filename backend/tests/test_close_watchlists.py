from datetime import datetime, timedelta
import unittest
from unittest.mock import patch, MagicMock

import httpx
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from backend.app.database import Base
from backend.app.stocks import research, signals, watchlists, deepseek, factors, learning


NOW = datetime(2026, 11, 26, 16, 0)


def bars():
    days = []
    moment = NOW
    while len(days) < 180:
        if moment.weekday() < 5:
            days.append(moment.date().isoformat())
        moment -= timedelta(days=1)
    return [(day, 10 * 1.001 ** index) for index, day in enumerate(reversed(days))]


def snapshot():
    return {"mode": "close", "close_ready": True, "complete": True, "running": False,
            "trade_date": "2026-11-26", "fetched_at": NOW.isoformat(), "allowed_boards": ["主板"],
            "items": [{"code": "000823", "price": 10}], "errors": []}


class CloseResearchTests(unittest.TestCase):
    def test_today_is_used_only_in_close_mode_after_cutoff(self):
        series = bars()
        item = {"code": "000823", "symbol": "sz000823", "board": "主板", "amount": 1000, "price": series[-1][1]}
        with patch.object(research, "now_local", return_value=NOW):
            close_items, close_report, _ = research.build_research([item], "2026-11-26", loader=lambda symbol: series, mode="close")
            live_items, live_report, _ = research.build_research([item], "2026-11-26", loader=lambda symbol: series)
        self.assertTrue(close_report["close_ready"])
        self.assertEqual(close_items[0]["historical_as_of"], "2026-11-26")
        self.assertEqual(live_items[0]["historical_as_of"], "2026-11-25")
        with patch.object(research, "now_local", return_value=NOW.replace(hour=14)):
            selected, report, _ = research.build_research([item], "2026-11-26", loader=lambda symbol: series, mode="close")
        self.assertFalse(report["close_ready"])
        self.assertEqual(selected, [])

    def test_missing_today_index_or_stock_never_uses_yesterday_as_today(self):
        series = bars()
        item = {"code": "000823", "symbol": "sz000823", "board": "主板", "amount": 1000, "price": series[-1][1]}
        with patch.object(research, "now_local", return_value=NOW):
            for missing in ("sh000300", "sz000823"):
                selected, report, _ = research.build_research([item], "2026-11-26", mode="close",
                    loader=lambda symbol: series[:-1] if symbol == missing else series)
                self.assertEqual(selected, [])
                self.assertFalse(report["close_ready"])
            selected, _, _ = research.build_research([dict(item, price=1)], "2026-11-26", mode="close", loader=lambda symbol: series)
            self.assertEqual(selected, [])

    def test_morning_history_cache_is_refetched_after_close(self):
        def handler(request):
            return httpx.Response(200, json={"data": {"sz000823": {"qfqday": [
                ["2026-11-25", "10", "10"], ["2026-11-26", "10", "11"]]}}})
        transport = httpx.MockTransport(handler)
        with patch.object(research, "_cache", {}), patch.object(research, "_preferred_url", None):
            with patch.object(research, "now_local", return_value=NOW.replace(hour=10)):
                morning = research.history("sz000823", transport)
            with patch.object(research, "now_local", return_value=NOW):
                close = research.history("sz000823", transport, include_today=True)
        self.assertEqual(morning[-1][0], "2026-11-25")
        self.assertEqual(close[-1][0], "2026-11-26")

    def test_retry_refreshes_incomplete_disk_and_memory_caches(self):
        series = bars()
        item = {"code": "000823", "symbol": "sz000823", "board": "主板", "amount": 1000, "price": series[-1][1]}
        cutoff = "2026-11-27"
        disk = series[:-1]
        memory = {symbol: (cutoff, disk) for symbol in ("sh000300", item["symbol"])}

        def handler(request):
            symbol = request.url.params["param"].split(",")[0]
            field = "day" if symbol == "sh000300" else "qfqday"
            rows = [[day, price, price] for day, price in series]
            return httpx.Response(200, json={"data": {symbol: {field: rows}}})

        transport = httpx.MockTransport(handler)
        real_history = research.history
        with patch.object(research, "now_local", return_value=NOW), patch.object(research, "_cache", memory), \
                patch.object(learning, "cached_history", return_value=disk), \
                patch.object(research, "history", side_effect=lambda symbol, **kwargs: real_history(symbol, transport, **kwargs)):
            _, report, histories = research.build_research([item], "2026-11-26", mode="close")
        self.assertTrue(report["close_ready"])
        self.assertTrue(all(rows[-1][0] == "2026-11-26" for rows in histories.values()))

    def test_intraday_quote_moves_do_not_change_daily_extension_filter(self):
        series = bars()[:-1]
        item = {"code": "000823", "symbol": "sz000823", "board": "主板", "amount": 1000}
        params = {"trend": {"max_extension": .06}}
        with patch.object(research, "now_local", return_value=NOW):
            for multiplier in (1, 1.08):
                quote = dict(item, price=series[-1][1] * multiplier)
                picks, _, _ = research.build_research([quote], "2026-11-26", loader=lambda _: series, parameters=params)
                self.assertIn("trend", picks[0]["strategies"])
                self.assertEqual(picks[0]["signal_close"], series[-1][1])

    def test_holding_period_comparison_uses_same_dates_and_skips_incomplete_windows(self):
        series = bars()
        entry = series[166][1]
        comparison = research.compare_holding_periods([series], dict(series), series[165][0])
        periods = comparison["periods"]
        self.assertEqual([row["hold_days"] for row in periods], [3, 5, 10])
        self.assertEqual([row["trades"] for row in periods], [1, 1, 1])
        self.assertEqual([row["avg_net_pct"] for row in periods],
                         [round(research.net_return(entry, series[166 + days][1]) * 100, 3) for days in (3, 5, 10)])
        missing = research.compare_holding_periods([series[:170] + series[171:]], dict(series), series[165][0])
        self.assertGreater(missing["missing_windows"], 0)
        self.assertEqual([row["trades"] for row in missing["periods"]], [0, 0, 0])

    @patch.object(factors, "now_local", return_value=NOW)
    def test_close_market_factor_uses_same_day_index(self, _clock):
        rows = [{"change_pct": 1}] * 100
        context = factors.market_context(rows, {"sh000300": bars()}, "2026-11-26", True, mode="close")
        self.assertEqual(context["index_as_of"], "2026-11-26")


class WatchlistStorageTests(unittest.TestCase):
    def test_saved_pool_survives_new_session_and_is_scoped_by_boards(self):
        engine = create_engine("sqlite://")
        Base.metadata.create_all(engine)
        with Session(engine) as db:
            watchlists.save(db, snapshot())
        with Session(engine) as db:
            loaded = watchlists.load(db, ["主板"])
            self.assertEqual(loaded["trade_date"], snapshot()["trade_date"])
            self.assertEqual(loaded["items"][0]["price"], snapshot()["items"][0]["price"])
            self.assertIsNone(watchlists.load(db, ["创业板"]))
            for changes in ({"close_ready": False}, {"complete": False}):
                with self.assertRaises(ValueError):
                    watchlists.save(db, dict(snapshot(), **changes))
            self.assertEqual(watchlists.load(db, ["主板"])["items"][0]["price"], 10)
        engine.dispose()

    def test_failed_regeneration_keeps_saved_cards(self):
        state = dict(snapshot(), running=True)
        with patch.object(signals, "_states", {("close", "主板"): state}), \
                patch.object(signals, "scan_market", return_value={"close_ready": False, "complete": True, "errors": []}), \
                patch.object(watchlists, "save") as save:
            signals._run(["主板"], "close")
        save.assert_not_called()
        self.assertEqual(state["items"], snapshot()["items"])
        self.assertFalse(state["running"])
        self.assertTrue(state["errors"])

    def test_close_mode_never_generates_before_cutoff_or_on_weekend(self):
        for moment in (NOW.replace(hour=14), datetime(2026, 11, 28, 16)):
            state = dict(snapshot(), loaded=True)
            with patch.object(signals, "_states", {("close", "主板"): state}), \
                    patch.object(signals, "_attempts", {}), patch.object(signals, "now_local", return_value=moment), \
                    patch.object(signals._executor, "submit") as submit, \
                    patch.object(deepseek, "request_analysis"), patch.object(deepseek, "analysis_state", return_value={"configured": False}):
                result = signals.get_signals(refresh=True, mode="close")
            submit.assert_not_called()
            self.assertEqual(result["items"], snapshot()["items"])
            self.assertFalse(result["can_generate_close"])

    def test_ai_uses_separate_mode_cache_and_can_explain_yesterdays_pool(self):
        saved = snapshot()
        with patch.object(deepseek, "now_local", return_value=NOW + timedelta(days=1)):
            self.assertIsNone(deepseek.snapshot_issue(saved))
            self.assertIsNotNone(deepseek.snapshot_issue(dict(saved, mode="intraday")))
            self.assertIsNotNone(deepseek.snapshot_issue(dict(saved, close_ready=False)))
        with patch.object(deepseek, "_states", {}):
            self.assertIsNot(deepseek._scope(saved), deepseek._scope(dict(saved, mode="intraday")))
