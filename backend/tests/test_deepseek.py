from copy import deepcopy
from datetime import datetime, timedelta
import json
import unittest
from unittest.mock import patch

import httpx
from pydantic import SecretStr

from backend.app.stocks import deepseek

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
        def handler(request):
            self.assertEqual(str(request.url), "https://api.deepseek.com/chat/completions")
            self.assertEqual(request.headers["Authorization"], "Bearer test-secret")
            body = json.loads(request.content)
            self.assertEqual(body["response_format"], {"type": "json_object"})
            public_input = json.loads(body["messages"][1]["content"])
            self.assertEqual(set(public_input), {"source", "fetched_at", "trade_date", "items", "research", "allowed_boards"})
            return httpx.Response(200, json=response())
        with patch.object(deepseek.settings, "deepseek_api_key", SecretStr("test-secret")):
            result = deepseek.analyze(SNAPSHOT, httpx.MockTransport(handler))
        self.assertEqual(result, REPORT)

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
                patch.object(deepseek.time, "monotonic", return_value=100), patch.object(deepseek._executor, "submit") as submit:
            deepseek.request_analysis(SNAPSHOT)
            self.assertEqual(submit.call_count, 1)
            state["status"] = "ready"
            deepseek.request_analysis(SNAPSHOT)
            deepseek.request_analysis(SNAPSHOT, retry=True)
            self.assertEqual(submit.call_count, 1)

    def test_old_comment_is_not_attached_to_new_quote(self):
        state = dict(status="ready", snapshot_at="2026-11-26T09:55:00", analyzed_at=NOW.isoformat(), **REPORT, error=None)
        with patch.object(deepseek.settings, "deepseek_api_key", SecretStr("test-secret")), patch.object(deepseek, "_state", state):
            public = deepseek.analysis_state(SNAPSHOT)
            self.assertEqual(public["status"], "waiting")
            self.assertEqual(public["items"], [])
            self.assertIsNone(public["summary"])

    def test_timeout_is_reported_without_request_details(self):
        def handler(request):
            raise httpx.ReadTimeout("private-request-details", request=request)
        with self.assertRaisesRegex(ValueError, "超时"):
            deepseek.analyze(SNAPSHOT, httpx.MockTransport(handler))


if __name__ == "__main__":
    unittest.main()
