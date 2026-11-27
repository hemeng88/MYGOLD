import json
import unittest
from collections import OrderedDict
from datetime import datetime, timedelta
from types import SimpleNamespace
from unittest.mock import patch

import httpx
from fastapi import FastAPI
from fastapi.testclient import TestClient
from pydantic import SecretStr

from backend.app.auth import require_auth
from backend.app.database import get_db
from backend.app.routers.api import router
from backend.app.stocks import deepseek, single_stock
from backend.app.stocks.ai_settings import Credentials

NOW = datetime(2026, 11, 27, 10, 0)
QUOTE = {"name": "超声电子", "price": 10.07, "prev_close": 10.09, "volume": 1000,
         "at": NOW - timedelta(seconds=10), "source": "新浪公开报价", "status": "00"}
DAILY = [((NOW.date() - timedelta(days=60 - i)).isoformat(), 9.5 + i * .01) for i in range(60)]
RAW = [(day, close, close + .65, close - .08) for day, close in DAILY]
RAW[-1] = (RAW[-1][0], RAW[-1][1], 12.30, RAW[-1][3])
TODAY = NOW.date().isoformat()
CREDS = Credentials(SecretStr("fake-key"), "test-model", "account:1:test", "account")


def preview(quote=QUOTE, cap=50, time=NOW, boards=None):
    with patch.object(single_stock, "now_local", return_value=time), \
            patch.object(single_stock, "_raw_bars", return_value=RAW + [(TODAY, 999, 1000, 1)]), \
            patch.object(single_stock, "_dated_quote", return_value=quote), \
            patch.object(single_stock, "fetch_market_trade_date", return_value=TODAY), \
            patch.object(single_stock.research, "history", return_value=DAILY + [(TODAY, 999)]), \
            patch.object(single_stock.factors, "financial_rows", return_value=[]):
        return single_stock.build_snapshot("000823", boards or ["主板"], 0, cap)


class SingleStockTests(unittest.TestCase):
    def test_intraday_preview_uses_complete_daily_prices_and_exact_code(self):
        snapshot = preview()
        self.assertEqual(snapshot["single"]["secid"], "0.000823")
        self.assertEqual(snapshot["single"]["name"], "超声电子")
        plan = snapshot["single"]["plan"]
        self.assertEqual(plan["as_of"], "2026-11-26")
        self.assertEqual(plan["target"], 12.30)
        self.assertLess(plan["stop"], plan["entry_low"])
        self.assertEqual(snapshot["single"]["decision"], "符合条件，可考虑买入")

    def test_stale_volume_and_budget_do_not_yield_buy_signal(self):
        for quote, cap in ((dict(QUOTE, at=NOW - timedelta(minutes=6)), 50), (dict(QUOTE, status="03"), 50),
                           (dict(QUOTE, volume=0), 50), (dict(QUOTE, price=8.00), 50), (QUOTE, 10)):
            with self.subTest(quote=quote, cap=cap):
                self.assertFalse(preview(quote, cap)["items"][0]["priority_eligible"])
        self.assertIn("超出", preview(cap=10)["single"]["decision_reason"])
        self.assertIsNone(preview(dict(QUOTE, prev_close=8))["single"]["plan"])
        self.assertFalse(preview(boards=["科创板"])["items"][0]["priority_eligible"])
        for code in ("161725", "hk00700", "00x823"):
            with self.assertRaises(LookupError):
                single_stock.build_snapshot(code, ["主板"], 0, 50)

    def test_queued_analysis_cannot_use_an_expired_intraday_recommendation(self):
        late_quote = dict(QUOTE, at=NOW - timedelta(minutes=4))
        snapshot = preview(late_quote)
        self.assertTrue(snapshot["items"][0]["priority_eligible"])
        with patch.object(deepseek, "now_local", return_value=NOW + timedelta(minutes=2)), \
                patch.object(deepseek, "_states", {}), patch.object(deepseek, "analyze") as analyze:
            deepseek._run(snapshot, CREDS)
            analyze.assert_not_called()
            self.assertEqual(single_stock.view(snapshot, CREDS)["decision"], "等待确认")

    def test_model_uses_single_stock_prompt_and_cannot_override_guard(self):
        snapshot = preview(cap=10)

        def handler(request):
            messages = json.loads(request.content)["messages"]
            self.assertEqual(messages[0]["content"], deepseek.SINGLE_STOCK_PROMPT)
            payload = json.loads(messages[1]["content"])
            self.assertEqual([item["code"] for item in payload["items"]], ["000823"])
            self.assertEqual(payload["single"]["plan"]["target"], snapshot["single"]["plan"]["target"])
            content = {"summary": "数据摘要", "items": [{"code": "000823", "view": "优先观察", "reason": "原因",
                                                        "risk": "风险", "trigger": "回踩观察"}]}
            return httpx.Response(200, json={"choices": [{"finish_reason": "stop", "message": {"content": json.dumps(content)}}]})

        with self.assertRaisesRegex(ValueError, "格式无效"):
            deepseek.analyze(snapshot, httpx.MockTransport(handler), CREDS)

    def test_preview_and_status_do_not_call_ai_and_snapshot_is_account_specific(self):
        snapshot = preview()
        app = FastAPI()
        app.include_router(router, prefix="/api")
        user = SimpleNamespace(id=1)
        app.dependency_overrides[require_auth] = lambda: user
        app.dependency_overrides[get_db] = lambda: "fake-db"
        base = "/api/stocks/single-analysis/000823"
        query = "?snapshot_id=" + snapshot["snapshot_id"]
        with TestClient(app) as client, patch.object(single_stock, "_snapshots", OrderedDict()), \
                patch.object(single_stock, "build_snapshot", return_value=snapshot), \
                patch("backend.app.routers.api.load_boards", return_value=["主板"]), \
                patch("backend.app.routers.api.load_prices", return_value=(0, 50)), \
                patch("backend.app.routers.api.ai_settings.resolve", return_value=CREDS), \
                patch.object(deepseek, "analysis_state", return_value={"status": "waiting"}), \
                patch.object(deepseek, "request_analysis") as analyze:
            self.assertEqual(client.get(base).json()["snapshot_id"], snapshot["snapshot_id"])
            self.assertEqual(client.get(base + "/status" + query).status_code, 200)
            analyze.assert_not_called()
            user.id = 2
            self.assertEqual(client.post(base + "/analyze" + query).status_code, 409)
            analyze.assert_not_called()
            user.id = 1
            self.assertEqual(client.post(base + "/analyze" + query).status_code, 200)
            self.assertEqual(analyze.call_args.args[0]["snapshot_id"], snapshot["snapshot_id"])
