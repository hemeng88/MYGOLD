from datetime import datetime, timedelta
import json
import unittest
from unittest.mock import patch

import httpx
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from backend.app.database import Base
from backend.app.models import StockCloseArchive, StockCloseWatchlist, StockResearchPreference
from backend.app.stocks import watchlists, signals, deepseek


def snapshot(day="2026-11-26", codes=("000823",), boards=None, price=10):
    return {"mode": "close", "close_ready": True, "complete": True, "running": False,
            "trade_date": day, "fetched_at": day + "T16:00:00", "errors": [],
            "allowed_boards": boards or ["主板"],
            "items": [{"code": code, "price": price, "amount": 100000000,
                       "change_pct": 1, "turnover_pct": 2, "strategy_labels": ["趋势延续"]} for code in codes]}


class CloseArchiveTests(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine("sqlite://")
        Base.metadata.create_all(self.engine)
        self.addCleanup(self.engine.dispose)

    def test_each_date_survives_and_same_day_refresh_does_not_duplicate(self):
        with Session(self.engine) as db:
            watchlists.save(db, snapshot("2026-11-25"))
            watchlists.save(db, snapshot(price=11))
            watchlists.save(db, snapshot(price=12))
        with Session(self.engine) as db:
            rows = list(db.scalars(select(StockCloseArchive).order_by(StockCloseArchive.trade_date)).all())
            self.assertEqual(len(rows), 2)
            self.assertEqual(json.loads(rows[0].snapshot_json)["items"][0]["price"], 10)
            self.assertEqual(json.loads(rows[1].snapshot_json)["items"][0]["price"], 12)
            self.assertEqual(watchlists.load(db, ["主板"])["trade_date"], "2026-11-26")

    def test_ai_history_excludes_same_day_future_and_other_scopes(self):
        with Session(self.engine) as db:
            for day in ("2026-11-23", "2026-11-25", "2026-11-26", "2026-11-27"):
                watchlists.save(db, snapshot(day))
            watchlists.save(db, snapshot("2026-11-24", boards=["创业板"], price=999))
            current = snapshot()
            watchlists.attach_history(db, current)
        self.assertEqual(current["history_context"]["dates"], ["2026-11-25", "2026-11-23"])
        history = current["items"][0]["close_history"]
        self.assertEqual(history["appearances"], 2)
        self.assertEqual(history["consecutive_archives"], 2)
        self.assertEqual([row["trade_date"] for row in history["records"]], ["2026-11-25", "2026-11-23"])
        self.assertNotIn("2026-11-24", current["history_context"]["dates"])

    def test_absent_candidate_breaks_archive_streak_and_does_not_invent_prices(self):
        with Session(self.engine) as db:
            watchlists.save(db, snapshot("2026-11-24"))
            watchlists.save(db, snapshot("2026-11-25", codes=("600519",)))
            current = snapshot()
            watchlists.attach_history(db, current)
        history = current["items"][0]["close_history"]
        self.assertEqual(history["appearances"], 1)
        self.assertEqual(history["consecutive_archives"], 0)
        self.assertEqual(len(history["records"]), 1)

    def test_latest_legacy_pool_is_imported_and_empty_history_is_explicit(self):
        old = snapshot("2026-11-25")
        with Session(self.engine) as db:
            db.add(StockCloseWatchlist(scope="主板", trade_date=old["trade_date"], snapshot_json=json.dumps(old)))
            db.commit()
            current = snapshot()
            watchlists.attach_history(db, current)
            self.assertEqual(current["history_context"]["archive_days"], 1)
            watchlists.attach_history(db, current)
            self.assertEqual(len(list(db.scalars(select(StockCloseArchive)).all())), 1)
            empty = snapshot(boards=["创业板"])
            watchlists.attach_history(db, empty)
        self.assertEqual(empty["history_context"]["status"], "empty")
        self.assertEqual(empty["items"][0]["close_history"]["records"], [])

    def test_history_is_bounded_and_not_nested_in_persisted_snapshot(self):
        with Session(self.engine) as db:
            for index in range(25):
                day = (datetime(2026, 10, 1) + timedelta(days=index)).date().isoformat()
                watchlists.save(db, snapshot(day))
            current = snapshot()
            watchlists.attach_history(db, current)
            self.assertEqual(current["history_context"]["archive_days"], 20)
            self.assertEqual(current["items"][0]["close_history"]["appearances"], 20)
            watchlists.save(db, current)
            row = db.scalar(select(StockCloseArchive).where(StockCloseArchive.trade_date == "2026-11-26"))
            raw = json.loads(row.snapshot_json)
            self.assertNotIn("history_context", raw)
            self.assertNotIn("close_history", raw["items"][0])
            self.assertEqual(len(list(db.scalars(select(StockCloseArchive)).all())), 26)

    def test_incomplete_scan_is_not_archived(self):
        with Session(self.engine) as db:
            with self.assertRaises(ValueError):
                watchlists.save(db, dict(snapshot(), complete=False))
            self.assertEqual(list(db.scalars(select(StockCloseArchive)).all()), [])

    def test_older_result_cannot_replace_newer_same_day_snapshot(self):
        with Session(self.engine) as db:
            watchlists.save(db, dict(snapshot(price=12), fetched_at="2026-11-26T17:00:00"))
            watchlists.save(db, snapshot(price=10))
            self.assertEqual(watchlists.load(db, ["主板"])["items"][0]["price"], 12)
            row = db.scalar(select(StockCloseArchive))
            self.assertEqual(json.loads(row.snapshot_json)["items"][0]["price"], 12)

    def test_scheduler_deduplicates_scopes_and_skips_saved_or_running(self):
        with Session(self.engine) as db:
            watchlists.save(db, dict(snapshot(), price_min=0, price_max=50))
            for user_id, boards in ((1, ["主板", "创业板"]), (2, ["主板", "创业板"]), (3, ["无效板块"])):
                db.add(StockResearchPreference(user_id=user_id, boards_json=json.dumps(boards)))
            db.commit()
        with patch.object(signals, "SessionLocal", side_effect=lambda: Session(self.engine)), \
                patch.object(signals, "now_local", return_value=datetime(2026, 11, 26, 16)), \
                patch.object(signals, "_states", {}), patch.object(signals, "_attempts", {}), \
                patch.object(signals._executor, "submit") as submit, patch.object(deepseek, "request_analysis") as ai:
            self.assertEqual(signals.queue_close_archives(), 1)
            self.assertEqual(signals.queue_close_archives(), 0)
            submit.assert_called_once_with(signals._run, ["主板", "创业板"], "close", 0.0, 50.0)
            ai.assert_not_called()

    def test_scheduler_does_not_queue_before_close_or_on_weekend(self):
        for moment in (datetime(2026, 11, 26, 10), datetime(2026, 11, 28, 16)):
            with patch.object(signals, "now_local", return_value=moment), patch.object(signals, "SessionLocal") as db:
                self.assertEqual(signals.queue_close_archives(), 0)
                db.assert_not_called()

    def test_background_generation_persists_archive_and_attaches_prior_history(self):
        with Session(self.engine) as db:
            watchlists.save(db, snapshot("2026-11-25"))
        states = {}
        with patch.object(signals, "SessionLocal", side_effect=lambda: Session(self.engine)), \
                patch.object(signals, "scan_market", return_value=snapshot()), \
                patch.object(signals, "_states", states), patch.object(deepseek, "request_analysis") as ai:
            signals._run(["主板"], "close")
        self.assertEqual(states[("close", "主板")]["history_context"]["dates"], ["2026-11-25"])
        self.assertEqual(states[("close", "主板")]["items"][0]["close_history"]["appearances"], 1)
        ai.assert_not_called()
        with Session(self.engine) as db:
            self.assertEqual(len(list(db.scalars(select(StockCloseArchive)).all())), 2)

    def test_ai_detail_limit_does_not_modify_saved_history(self):
        current = snapshot()
        records = [{"trade_date": str(index), "price": index} for index in range(20)]
        current["items"][0]["close_history"] = {"appearances": 20, "records": records}
        report = {"summary": "仅比较输入历史", "items": [{"code": "000823", "view": "等待确认", "reason": "需确认", "risk": "存在选择偏差", "trigger": "等待"}]}
        def handler(request):
            public = json.loads(json.loads(request.content)["messages"][1]["content"])
            self.assertEqual(len(public["items"][0]["close_history"]["records"]), 5)
            self.assertEqual(public["items"][0]["close_history"]["appearances"], 20)
            return httpx.Response(200, json={"choices": [{"finish_reason": "stop", "message": {"content": json.dumps(report)}}]})
        deepseek.analyze(current, httpx.MockTransport(handler))
        self.assertEqual(len(current["items"][0]["close_history"]["records"]), 20)

    def test_model_receives_historical_records_without_relaxing_priority(self):
        current = snapshot()
        current["items"][0].update(priority_eligible=False, close_history={"appearances": 1, "records": [{"trade_date": "2026-11-25", "price": 9}]})
        current["history_context"] = {"archive_days": 1, "dates": ["2026-11-25"]}
        report = {"summary": "历史样本少，等待确认", "items": [{"code": "000823", "view": "等待确认", "reason": "仅一次历史记录", "risk": "数据不足", "trigger": "等待"}]}
        def handler(request):
            public = json.loads(json.loads(request.content)["messages"][1]["content"])
            self.assertEqual(public["history_context"], current["history_context"])
            self.assertEqual(public["items"][0]["close_history"], current["items"][0]["close_history"])
            return httpx.Response(200, json={"choices": [{"finish_reason": "stop", "message": {"content": json.dumps(report)}}]})
        deepseek.analyze(current, httpx.MockTransport(handler))
        report["items"][0]["view"] = "优先观察"
        with self.assertRaises(ValueError):
            deepseek.analyze(current, httpx.MockTransport(handler))
