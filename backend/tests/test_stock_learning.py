from copy import deepcopy
from datetime import datetime, timedelta
import json
import unittest
from unittest.mock import patch

from pydantic import SecretStr
from sqlalchemy import create_engine, select, text
from sqlalchemy.orm import Session
from fastapi import FastAPI
from fastapi.testclient import TestClient
from types import SimpleNamespace

from backend.app.database import Base, get_db
from backend.app import database
from backend.app.auth import require_auth
from backend.app.routers.api import router
from backend.app.models import StockHistorySnapshot, StockCloseArchive
from backend.app.stocks import learning, preferences, signals, deepseek
from test_stock_signals import quote, research_stub


class PriceAndManualAITests(unittest.TestCase):
    def test_existing_preferences_are_migrated_without_losing_boards(self):
        engine = create_engine("sqlite://")
        with engine.begin() as conn:
            conn.execute(text("CREATE TABLE stock_research_preferences (user_id INTEGER PRIMARY KEY, boards_json TEXT NOT NULL)"))
            conn.execute(text("INSERT INTO stock_research_preferences VALUES (7, :boards)"), {"boards": json.dumps(["主板", "创业板"])})
        with patch.object(database, "engine", engine):
            database.ensure_schema()
            database.ensure_schema()
        with Session(engine) as db:
            self.assertEqual(preferences.load_boards(db, 7), ["主板", "创业板"])
            self.assertEqual(preferences.load_prices(db, 7), (0, 50))
        engine.dispose()

    def test_market_fetch_is_shared_without_sharing_price_filtered_results(self):
        rows = [quote(), quote("600519", "sh600519", trade=100, open=100, high=101, low=99, amount=10000000000, volume=100000000)]
        with patch.object(signals, "_market_cache", {}), patch.object(signals.universe, "_get_json", return_value=rows) as fetch, \
                patch.object(signals.universe, "fetch_node_count", return_value=2), \
                patch.object(signals, "fetch_market_trade_date", return_value="2026-11-26"):
            affordable = signals.scan_market(research_builder=research_stub, price_max=50)
            unlimited = signals.scan_market(research_builder=research_stub)
        fetch.assert_called_once()
        self.assertEqual(len(affordable["items"]), 1)
        self.assertEqual(len(unlimited["items"]), 2)

    def test_price_endpoint_validates_and_saves_only_current_account(self):
        app = FastAPI()
        app.include_router(router, prefix="/api")
        app.dependency_overrides[require_auth] = lambda: SimpleNamespace(id=7)
        app.dependency_overrides[get_db] = lambda: "fake-db"
        with TestClient(app) as client, patch("backend.app.routers.api.save_prices", return_value={"price_min": 5, "price_max": 30}) as save:
            self.assertEqual(client.put("/api/stocks/signals/prices", json={"price_min": 5, "price_max": 30}).status_code, 200)
            save.assert_called_once_with("fake-db", 7, 5, 30)
            self.assertEqual(client.put("/api/stocks/signals/prices", json={"price_min": -1}).status_code, 422)
            save.side_effect = ValueError("最高价不能低于最低价")
            self.assertEqual(client.put("/api/stocks/signals/prices", json={"price_min": 40, "price_max": 30}).status_code, 400)

    def test_prices_are_account_specific_and_survive_board_changes(self):
        engine = create_engine("sqlite://")
        Base.metadata.create_all(engine)
        with Session(engine) as db:
            self.assertEqual(preferences.load_prices(db, 1), (0, 50))
            preferences.save_prices(db, 1, 5, 30)
            preferences.save_boards(db, 1, ["主板", "创业板"])
            self.assertEqual(preferences.load_prices(db, 1), (5, 30))
            self.assertEqual(preferences.load_prices(db, 2), (0, 50))
            preferences.save_prices(db, 2, 0, None)
            preferences.save_prices(db, 1, 0, None)
            self.assertEqual(preferences.load_prices(db, 1), (0, None))
            self.assertEqual(preferences.load_prices(db, 2), (0, None))
        engine.dispose()

    def test_invalid_ranges_are_rejected_and_scope_keeps_cents(self):
        for low, high in ((10, 5), (-1, 10), (0, 0), (0, .001), (0, float("nan")), (float("inf"), None)):
            with self.assertRaises(ValueError):
                preferences.price_range(low, high)
        key = preferences.scope_key(["主板"], 12345.67, 22345.67)
        self.assertEqual(preferences.parse_scope(key), (["主板"], 12345.67, 22345.67))

    @patch.object(signals, "fetch_market_trade_date", return_value="2026-11-26")
    def test_price_filter_happens_before_sampling_and_keeps_market_breadth_full(self, _date):
        rows = [quote(), quote("600519", "sh600519", trade=100, open=100, high=101, low=99, amount=10000000000, volume=100000000)]
        captured = []
        def builder(items, day):
            captured.extend(items)
            return research_stub(items, day)
        result = signals.scan_market(get_json=lambda *args: rows, count_loader=lambda node: 2,
                                     research_builder=builder, price_min=5, price_max=30)
        self.assertEqual([item["code"] for item in captured], ["000823"])
        self.assertEqual(result["scanned"], 2)
        self.assertEqual(result["eligible"], 1)

    def test_price_scopes_and_ai_caches_do_not_mix(self):
        with patch.object(signals, "_states", {}), patch.object(deepseek, "_states", {}):
            self.assertIsNot(signals._scope(["主板"], price_max=30), signals._scope(["主板"], price_max=50))
            self.assertIsNot(deepseek._scope({"price_max": 30}), deepseek._scope({"price_max": 50}))

    def test_poll_and_refresh_never_charge_ai_but_explicit_analyze_does(self):
        now = datetime(2026, 11, 26, 10)
        state = dict(running=False, fetched_at=now.isoformat(), trade_date="2026-11-26", complete=True,
                     items=[{"code": "000823"}], errors=[], boards={}, scanned=1, expected=1, progress=1, matched=1)
        ai_state = dict(status="idle", snapshot_at=None, analyzed_at=None, items=[], summary=None, error=None)
        with patch.object(signals, "_state", state), patch.object(signals, "_attempts", {("intraday", "主板"): 99}), \
                patch.object(signals, "now_local", return_value=now), patch.object(deepseek, "now_local", return_value=now), \
                patch.object(deepseek, "_state", ai_state), patch.object(deepseek, "_last_attempt", 0), \
                patch.object(signals.time, "monotonic", return_value=100), patch.object(signals, "should_poll_quotes", return_value=True), \
                patch.object(deepseek.settings, "deepseek_api_key", SecretStr("fake-test-key")), \
                patch.object(deepseek._executor, "submit") as model, patch.object(signals._executor, "submit") as scanner:
            visible = signals.get_signals()
            signals.get_signals(refresh=True)
            model.assert_not_called()
            state["items"] = [{"code": "600519"}]
            with self.assertRaises(signals.SnapshotChanged):
                signals.get_signals(analyze=True, requested_snapshot_id=visible["snapshot_id"])
            model.assert_not_called()
            current = signals.get_signals()
            signals.get_signals(analyze=True, requested_snapshot_id=current["snapshot_id"])
            model.assert_called_once()
            self.assertEqual(model.call_args.args[1]["items"], [{"code": "600519"}])
            scanner.assert_not_called()

    def test_selected_codes_restrict_model_input_without_restricting_displayed_candidates(self):
        state = dict(signals._state, items=[{"code": "000823"}, {"code": "600519"}])
        with patch.object(signals, "_state", state), patch.object(signals, "_attempts", {}), \
                patch.object(signals._executor, "submit"), patch.object(deepseek, "request_analysis") as request:
            batch = signals.get_signals()["snapshot_id"]
            for invalid in ([], ["300001"], ["000823", "000823"]):
                with self.assertRaises(ValueError):
                    signals.get_signals(analyze=True, requested_snapshot_id=batch, requested_codes=invalid)
            request.assert_not_called()
            result = signals.get_signals(analyze=True, requested_snapshot_id=batch, requested_codes=["600519"])
        self.assertEqual(request.call_args.args[0]["items"], [{"code": "600519"}])
        self.assertEqual(result["items"], state["items"])

    def test_complete_previous_snapshot_can_be_manually_analyzed_during_background_scan(self):
        now = datetime(2026, 11, 26, 10)
        state = {"complete": True, "running": True, "analysis_snapshot_ready": True, "fetched_at": now.isoformat(),
                 "trade_date": "2026-11-26", "items": [{"code": "000823"}]}
        with patch.object(deepseek, "now_local", return_value=now):
            self.assertIsNone(deepseek.snapshot_issue(state))
            self.assertIsNotNone(deepseek.snapshot_issue(dict(state, complete=False)))


class LearningTests(unittest.TestCase):
    def test_auto_activation_requires_both_new_dates_and_validation_events(self):
        days = [(datetime(2025, 10, 1) + timedelta(days=i)).date().isoformat() for i in range(260)]
        histories = {"sh000300": [[day, 100 * 1.0002 ** i] for i, day in enumerate(days)]}
        for stock in range(16):
            histories["sz%06d" % stock] = [[day, 10 * 1.002 ** i] for i, day in enumerate(days)]
        pools = [(day, {"items": [{"symbol": symbol, "strategies": ["trend", "pullback", "low_vol"]} for symbol in histories if symbol != "sh000300"]}) for day in days[140:230]]
        with patch("backend.app.stocks.research.triggers", return_value=["trend", "pullback", "low_vol"]):
            pending = learning.evaluate(histories, "主板", 59, forward_pools=pools)
            ready = learning.evaluate(histories, "主板", 60, forward_pools=pools)
        self.assertFalse(pending["active"])
        self.assertTrue(ready["active"])
        self.assertTrue(all(row["selected"]["holdout"]["trades"] >= 30 for row in ready["strategies"]))

    def test_historical_snapshots_do_not_mix_adjustment_dates(self):
        engine = create_engine("sqlite://")
        Base.metadata.create_all(engine)
        with Session(engine) as db:
            learning.store_histories(db, {"sz000823": [["2026-11-25", 10]]}, "2026-11-26")
            learning.store_histories(db, {"sz000823": [["2026-11-25", 9], ["2026-11-26", 11]]}, "2026-11-27")
            self.assertEqual(len(list(db.scalars(select(StockHistorySnapshot)).all())), 2)
        with patch.object(learning, "SessionLocal", side_effect=lambda: Session(engine)):
            self.assertEqual(learning.cached_history("sz000823", "2026-11-26"), [["2026-11-25", 10]])
            self.assertIsNone(learning.cached_history("sz000823", "2026-11-28"))
        engine.dispose()

    def test_insufficient_data_never_activates_parameters(self):
        result = learning.evaluate({"sh000300": [["2026-11-25", 100]]}, "主板", forward_days=100)
        self.assertFalse(result["active"])
        self.assertEqual(result["status"], "accumulating")

    def test_filter_respects_index_regime_and_extension(self):
        stats = dict(last=11, ma20=10)
        self.assertFalse(learning.accepts(stats, {"max_extension": .06}, None))
        self.assertFalse(learning.accepts(stats, {"require_index_up": True}, None))
        self.assertTrue(learning.accepts(stats, {}, None))
        self.assertTrue(learning.accepts(stats, {"require_index_up": True}, {"last": 11, "ma20": 10, "ma60": 9}))

    def test_parameter_selection_is_unchanged_when_only_holdout_prices_change(self):
        start = datetime(2025, 10, 1)
        days = [(start + timedelta(days=i)).date().isoformat() for i in range(260)]
        histories = {"sh000300": [[day, 100 * 1.0002 ** i] for i, day in enumerate(days)]}
        for stock in range(3):
            histories["sz%06d" % stock] = [[day, 10 * 1.002 ** i] for i, day in enumerate(days)]
        first = learning.evaluate(histories, "主板", 0)
        changed = deepcopy(histories)
        for symbol, values in changed.items():
            if symbol != "sh000300":
                for i in range(230, 260):
                    values[i][1] *= .95 ** (i - 229)
        second = learning.evaluate(changed, "主板", 0)
        self.assertEqual([row["selected"]["parameter"] for row in first["strategies"]],
                         [row["selected"]["parameter"] for row in second["strategies"]])
        self.assertFalse(first["active"])
        self.assertFalse(second["active"])

    def test_daily_evaluation_counts_only_same_scope_real_archives(self):
        engine = create_engine("sqlite://")
        Base.metadata.create_all(engine)
        with Session(engine) as db:
            db.add(StockCloseArchive(scope="主板", trade_date="2026-11-25", snapshot_json="{}"))
            db.add(StockCloseArchive(scope="创业板", trade_date="2026-11-25", snapshot_json="{}"))
            db.commit()
            with patch.object(learning, "evaluate", return_value={"active": False, "version": learning.VERSION}) as evaluate:
                learning.persist_evaluation(db, {}, "主板", "2026-11-26")
                learning.persist_evaluation(db, {}, "主板", "2026-11-26")
                self.assertEqual(evaluate.call_args.args, ({}, "主板", 1))
                self.assertEqual(len(evaluate.call_args.kwargs["forward_pools"]), 1)
        engine.dispose()
