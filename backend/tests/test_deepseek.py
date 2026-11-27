from copy import deepcopy
from datetime import datetime, timedelta
import json
import unittest
from unittest.mock import patch

import httpx
from pydantic import SecretStr
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from backend.app.database import Base
from backend.app.models import StockAIReview
from backend.app.stocks import deepseek
from backend.app.stocks.ai_settings import Credentials

NOW = datetime(2026, 11, 26, 10, 0)
SNAPSHOT = {"fetched_at": NOW.isoformat(), "trade_date": "2026-11-26", "complete": True,
            "running": False, "items": [{"code": "000823", "price": 10.5, "watch_low": 10.2,
                                          "watch_high": 10.5, "breakout_price": 10.8, "invalidation_price": 9.9}]}
REPORT = {"summary": "本轮仅比较公开行情。", "items": [{"code": "000823", "view": "等待确认",
          "reason": "等待量价进一步确认", "risk": "行情可能延迟", "trigger": "等待"}]}


def response(report=REPORT, finish="stop"):
    return {"choices": [{"finish_reason": finish, "message": {"content": json.dumps(report)}}]}


class DeepSeekTests(unittest.TestCase):
    def setUp(self):
        self.clock = patch.object(deepseek, "now_local", return_value=NOW)
        self.clock.start()
        self.addCleanup(self.clock.stop)

    def call(self, payload, status=200):
        transport = httpx.MockTransport(lambda request: httpx.Response(status, json=payload))
        return deepseek.analyze(SNAPSHOT, transport)

    def test_valid_json_and_request_shape(self):
        snapshot = deepcopy(SNAPSHOT)
        snapshot.update(price_min=5, price_max=40, parameter_evaluation={"status": "active", "parameters": {"trend": {}}})
        snapshot["items"][0].update(signal_close=10.25, ma20_gap_pct=2.5, internal_note="仅保留在服务端")

        def handler(request):
            self.assertEqual(str(request.url), "https://api.deepseek.com/chat/completions")
            self.assertEqual(request.headers["Authorization"], "Bearer test-secret")
            body = json.loads(request.content)
            self.assertEqual(body["response_format"], {"type": "json_object"})
            public_input = json.loads(body["messages"][1]["content"])
            self.assertEqual(public_input["price_range"], {"min": 5, "max": 40})
            self.assertEqual(public_input["items"][0]["price"], 10.5)
            self.assertEqual(public_input["items"][0]["signal_close"], 10.25)
            self.assertEqual(public_input["items"][0]["ma20_gap_pct"], 2.5)
            self.assertNotIn("internal_note", public_input["items"][0])
            self.assertEqual(public_input["parameter_evaluation"], {"status": "active"})
            self.assertIsNone(public_input["applied_parameters"])
            return httpx.Response(200, json=response())
        with patch.object(deepseek.settings, "deepseek_api_key", SecretStr("test-secret")):
            result = deepseek.analyze(snapshot, httpx.MockTransport(handler))
        self.assertEqual(result, REPORT)

    def test_factor_context_and_financials_are_sent_and_priority_gate_is_enforced(self):
        snapshot = deepcopy(SNAPSHOT)
        snapshot["factor_context"] = {"market": {"status": "weak"}}
        snapshot["items"][0].update(priority_eligible=False, technical_priority_eligible=True,
                                     factors={"fundamentals": {"status": "risk"}, "blockers": ["营业收入同比下降"]})
        report = deepcopy(REPORT)
        report["items"][0]["view"] = "优先观察"
        def handler(request):
            public = json.loads(json.loads(request.content)["messages"][1]["content"])
            self.assertEqual(public["factor_context"], snapshot["factor_context"])
            self.assertEqual(public["items"][0]["factors"], snapshot["items"][0]["factors"])
            return httpx.Response(200, json=response(report))
        with self.assertRaises(ValueError):
            deepseek.analyze(snapshot, httpx.MockTransport(handler))

    def test_rejects_invented_missing_duplicate_codes_and_prices(self):
        cases = []
        for code in ("600519",):
            report = deepcopy(REPORT)
            report["items"][0]["code"] = code
            cases.append(report)
        report = deepcopy(REPORT)
        report["items"] *= 2
        cases.append(report)
        report = deepcopy(REPORT)
        report["items"][0]["buy_price"] = 123
        cases.append(report)
        report = deepcopy(REPORT)
        report["items"] = []
        cases.append(report)
        for report in cases:
            with self.subTest(report=report), self.assertRaisesRegex(ValueError, "格式无效"):
                self.call(response(report))

    def test_rejects_truncated_and_blank_output(self):
        for payload in (response(finish="length"), {"choices": [{"finish_reason": "stop", "message": {"content": " "}}]}):
            with self.assertRaises(ValueError):
                self.call(payload)

    def test_ai_cannot_prioritize_unvalidated_candidate(self):
        report = deepcopy(REPORT)
        report["items"][0]["view"] = "优先观察"
        with self.assertRaises(ValueError):
            self.call(response(report))

    def test_api_errors_hide_raw_response(self):
        for status in (401, 402, 429, 500):
            with self.subTest(status=status), self.assertRaises(ValueError) as exc:
                self.call({"error": "secret-from-provider"}, status)
            self.assertNotIn("secret-from-provider", str(exc.exception))

    def test_eligibility_blocks_stale_incomplete_and_noncurrent_snapshots(self):
        self.assertIsNone(deepseek.snapshot_issue(SNAPSHOT))
        cases = [dict(complete=False), dict(running=True), dict(items=[]), dict(trade_date=None),
                 dict(trade_date="2026-11-25"), dict(fetched_at=(NOW - timedelta(minutes=11)).isoformat())]
        for changes in cases:
            self.assertTrue(deepseek.snapshot_issue(dict(SNAPSHOT, **changes)))

    def test_unconfigured_does_not_call_api(self):
        with patch.object(deepseek.settings, "deepseek_api_key", SecretStr("")), patch.object(deepseek._executor, "submit") as submit:
            deepseek.request_analysis(SNAPSHOT)
            self.assertFalse(submit.called)
            state = deepseek.analysis_state(SNAPSHOT)
            self.assertEqual(state["status"], "unconfigured")
            self.assertFalse(state["items"])

    def test_same_snapshot_no_repeat_and_manual_cooldown(self):
        state = dict(status="idle", snapshot_at=None, analyzed_at=None, items=[], summary=None, error=None)
        with patch.object(deepseek.settings, "deepseek_api_key", SecretStr("test-secret")), \
                patch.object(deepseek, "_state", state), patch.object(deepseek, "_last_attempt", 0), \
                patch.object(deepseek.time, "monotonic", return_value=100) as clock, patch.object(deepseek._executor, "submit") as submit:
            deepseek.request_analysis(SNAPSHOT)
            self.assertEqual(submit.call_count, 1)
            state["status"] = "ready"
            clock.return_value = 161
            deepseek.request_analysis(SNAPSHOT)
            deepseek.request_analysis(SNAPSHOT, retry=True)
            self.assertEqual(submit.call_count, 1)
            state["status"] = "failed"
            deepseek.request_analysis(SNAPSHOT, retry=True)
            self.assertEqual(submit.call_count, 2)

    def test_snapshot_id_tracks_evidence_but_ignores_scan_progress(self):
        after = dict(SNAPSHOT, progress=99, factor_context={"market": {"status": "weak"}})
        self.assertNotEqual(deepseek.snapshot_id(SNAPSHOT), deepseek.snapshot_id(after))
        self.assertEqual(deepseek.snapshot_id(after), deepseek.snapshot_id(dict(after, progress=100)))

    def test_saved_review_reuses_same_selection_after_restart_and_is_private(self):
        engine = create_engine("sqlite://")
        self.addCleanup(engine.dispose)
        Base.metadata.create_all(engine)
        credentials = Credentials(SecretStr("private-key"), "test-model", "account:1:server", "server")
        other_account = Credentials(SecretStr("other-key"), "test-model", "account:2:server", "server")
        first = dict(SNAPSHOT, snapshot_id=deepseek.snapshot_id(SNAPSHOT),
                     review_candidates=[*SNAPSHOT["items"], {"code": "600519", "price": 52}])
        second = dict(first, items=[{"code": "600519", "price": 52}])
        with patch.object(deepseek, "SessionLocal", side_effect=lambda: Session(engine)), \
                patch.object(deepseek, "_states", {}), patch.object(deepseek, "_attempts", {}), \
                patch.object(deepseek, "analyze", return_value=REPORT), patch.object(deepseek._executor, "submit") as submit:
            deepseek.request_analysis(first, credentials=credentials)
            worker, *args = submit.call_args.args
            worker(*args)
            with Session(engine) as db:
                row = db.scalar(select(StockAIReview))
                self.assertEqual(row.account_scope, credentials.scope)
                self.assertEqual([item["code"] for item in json.loads(row.input_json)["items"]], ["000823"])
                self.assertEqual([item["code"] for item in json.loads(row.candidates_json)], ["000823", "600519"])
                self.assertNotIn("private-key", row.input_json + row.report_json)
            with patch.object(deepseek, "_states", {}), patch.object(deepseek, "_attempts", {}):
                restored = deepseek.analysis_state(first, credentials=credentials)
                self.assertEqual(restored["reviewed_codes"], ["000823"])
                self.assertTrue(restored["archived"])
                deepseek.request_analysis(first, credentials=credentials)
                submit.assert_called_once()
                self.assertEqual(deepseek.analysis_state(first, credentials=other_account)["items"], [])
                deepseek.request_analysis(second, credentials=credentials)
                self.assertEqual(submit.call_count, 2)

    def test_model_card_reviews_keep_separate_symbols_and_require_explicit_selection(self):
        engine = create_engine("sqlite://")
        self.addCleanup(engine.dispose)
        Base.metadata.create_all(engine)
        first = Credentials(SecretStr("key-first"), "test-first", "account:1:first", "account", profile_id="first")
        second = Credentials(SecretStr("key-second"), "test-second", "account:1:second", "account", profile_id="second")
        other = Credentials(SecretStr("key-other"), "test-first", "account:2:first", "account", profile_id="first")
        both = dict(SNAPSHOT, items=[*SNAPSHOT["items"], {"code": "600519", "price": 80}])
        full = dict(both, snapshot_id=deepseek.snapshot_id(both))
        original = dict(full, items=both["items"][:1])
        later = dict(full, items=both["items"][1:])
        later_report = dict(REPORT, items=[dict(REPORT["items"][0], code="600519")])
        second_report = dict(REPORT, items=[dict(REPORT["items"][0], view="暂不考虑")])
        with patch.object(deepseek, "SessionLocal", side_effect=lambda: Session(engine)), \
                patch.object(deepseek, "_states", {}), patch.object(deepseek, "request_analysis") as request:
            deepseek._save_review(original, first, REPORT, NOW)
            deepseek._save_review(later, first, later_report, NOW + timedelta(seconds=5))
            deepseek._save_review(original, second, second_report, NOW)
            one, two = deepseek.profile_results(full, [first, second], include_cards=True)
            request.assert_not_called()
            self.assertEqual(set(one["card_reviews"]), {"000823", "600519"})
            self.assertEqual(one["card_reviews"]["000823"]["view"], "等待确认")
            self.assertEqual(two["card_reviews"]["000823"]["view"], "暂不考虑")
            self.assertEqual(deepseek.profile_results(full, [other], include_cards=True)[0]["card_reviews"], {})
            changed = dict(full, snapshot_id="new-snapshot")
            states = deepseek.profile_results(changed, [first, second], [second], original, include_cards=True)
            request.assert_called_once_with(original, retry=True, credentials=second)
            self.assertTrue(states[0]["card_reviews"]["600519"]["previous"])

    def test_old_comment_is_not_attached_to_new_quote(self):
        state = dict(status="ready", snapshot_at="2026-11-26T09:55:00", analyzed_at=NOW.isoformat(), **REPORT, error=None)
        with patch.object(deepseek.settings, "deepseek_api_key", SecretStr("test-secret")), patch.object(deepseek, "_state", state):
            public = deepseek.analysis_state(SNAPSHOT)
            self.assertEqual(public["status"], "previous")
            self.assertEqual(public["snapshot_at"], state["snapshot_at"])
            self.assertEqual(public["summary"], REPORT["summary"])

    def test_timeout_is_reported_without_request_details(self):
        def handler(request):
            raise httpx.ReadTimeout("private-request-details", request=request)
        with self.assertRaisesRegex(ValueError, "超时"):
            deepseek.analyze(SNAPSHOT, httpx.MockTransport(handler))


if __name__ == "__main__":
    unittest.main()
