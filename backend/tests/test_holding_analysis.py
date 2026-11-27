from datetime import datetime, timedelta
import json
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from fastapi import FastAPI
from fastapi.testclient import TestClient
import httpx
from pydantic import SecretStr
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from backend.app.auth import require_auth
from backend.app.database import Base, get_db
from backend.app.models import FundFavorite
from backend.app.routers.api import router
from backend.app.stocks import deepseek, holding_analysis, single_stock
from backend.app.stocks.ai_settings import Credentials

NOW = datetime(2026, 11, 27, 10)
POSITION = {"code": "000823", "secid": "0.000823", "shares": 100, "cost_price": 10}
CREDS = Credentials(SecretStr("holding-test-key"), "test-model", "account:1:holding", "account")


def market(price=10.4, now=NOW, quote_updates=None, bars=True):
    days = [(NOW.date() - timedelta(days=25 - i)).isoformat() for i in range(25)] if bars else []
    quote = {"at": now - timedelta(seconds=5), "price": price, "status": "00", "prev_close": 12,
             "volume": 1000, "bid": 10.4, "bid_size": 80, "source": "测试报价"}
    quote.update(quote_updates or {})
    return {"name": "超声电子", "symbol": "sz000823", "secid": "0.000823", "board": "主板",
            "moment": now, "market_date": now.date().isoformat(), "completed_today": False, "quote": quote,
            "raw": [(day, 12, 12.3, 11.7) for day in days], "daily": [(day, 12) for day in days],
            "stats": None, "financial": {"status": "pass"}}


def snapshot(position=POSITION, **kwargs):
    with patch.object(single_stock, "load_market", return_value=market(**kwargs)):
        return holding_analysis.build_snapshot(position, 1)


class HoldingAnalysisTests(unittest.TestCase):
    def test_uses_saved_cost_shares_and_technical_protection(self):
        data = snapshot()["holding"]
        self.assertEqual(data["signal"], "stop_hit")
        self.assertEqual(data["pnl"]["pnl"], 40)
        self.assertEqual(data["plan"]["stop"], {"price": 10.5, "pnl": 50.0, "pnl_pct": 5.0})
        self.assertEqual(data["plan"]["take_profit"], {"price": 12.3, "pnl": 230.0, "pnl_pct": 23.0})
        self.assertEqual(data["visible_buy_shares"], 80)
        profitable = snapshot(price=12.5)["holding"]
        self.assertEqual(profitable["signal"], "target_hit")
        updated = snapshot(dict(POSITION, shares=200, cost_price=12.0), price=12)["holding"]
        self.assertEqual(updated["signal"], "between")
        self.assertEqual(updated["plan"]["stop"], {"price": 11.4, "pnl": -120.0, "pnl_pct": -5.0})

    def test_old_or_unaligned_quotes_never_emit_a_live_exit_signal(self):
        for kwargs in (
            {"quote_updates": {"at": NOW - timedelta(minutes=8)}},
            {"quote_updates": {"prev_close": 8}},
            {"quote_updates": {"volume": 0}},
            {"now": NOW.replace(hour=16)},
            {"bars": False},
        ):
            with self.subTest(kwargs=kwargs):
                data = snapshot(**kwargs)["holding"]
                self.assertEqual(data["signal"], "reference")
                self.assertFalse(data["current"])
        fallback = snapshot(bars=False)["holding"]["plan"]
        self.assertEqual(fallback["stop"]["price"], 9.5)
        self.assertEqual(fallback["take_profit"]["price"], 11)
        self.assertIsNone(fallback["atr14"])

    def test_ai_review_uses_only_this_position_and_checks_the_program_signal(self):
        data = snapshot(quote_updates={"bid": 0, "bid_size": 0})
        comment = {"code": "000823", "view": "止损关注", "reason": "到了保护成本的参考价", "risk": "没有可见买盘", "trigger": "止损参考"}
        def handler(request):
            body = json.loads(request.content)
            self.assertEqual(body["messages"][0]["content"], deepseek.HOLDING_PROMPT)
            payload = json.loads(body["messages"][1]["content"])
            self.assertEqual(payload["holding"]["shares"], 100)
            self.assertEqual(payload["holding"]["cost_price"], 10)
            self.assertEqual(payload["holding"]["visible_buy_shares"], 0 if payload["holding"]["current"] else None)
            self.assertNotIn("_position_id", payload)
            self.assertNotIn("_holding_scope", payload)
            self.assertEqual([item["code"] for item in payload["items"]], ["000823"])
            return httpx.Response(200, json={"choices": [{"finish_reason": "stop", "message": {
                "content": json.dumps({"summary": "退出条件复核", "items": [comment]})}}]})
        mocked = httpx.MockTransport(handler)
        self.assertEqual(deepseek.analyze(data, mocked, CREDS)["items"][0]["view"], "止损关注")
        with self.assertRaisesRegex(ValueError, "格式无效"):
            deepseek.analyze(snapshot(quote_updates={"bid": 0, "bid_size": 0, "at": NOW - timedelta(minutes=7)}), mocked, CREDS)
        with patch.object(deepseek, "now_local", return_value=NOW + timedelta(minutes=6)):
            self.assertIn("过期", deepseek.snapshot_issue(data))

    def test_can_restore_previous_review_for_unchanged_position_only(self):
        engine = create_engine("sqlite://")
        self.addCleanup(engine.dispose)
        Base.metadata.create_all(engine)
        first = snapshot()
        second = snapshot(now=NOW + timedelta(minutes=1))
        edited = snapshot(dict(POSITION, shares=200), now=NOW + timedelta(minutes=1))
        report = {"summary": "点评", "items": [{"code": "000823", "view": "止损关注", "trigger": "止损参考",
                                            "reason": "触及参考价", "risk": "买盘不足"}]}
        with patch.object(deepseek, "SessionLocal", side_effect=lambda: Session(engine)), \
                patch.object(deepseek, "now_local", return_value=NOW + timedelta(minutes=1)), \
                patch.object(deepseek, "_states", {}):
            deepseek._save_review(first, CREDS, report, NOW)
            restored = holding_analysis.view(second, [CREDS])["ai_results"][0]
            self.assertEqual(restored["status"], "previous")
            self.assertEqual(restored["items"], report["items"])
            self.assertEqual(holding_analysis.view(edited, [CREDS])["ai_results"][0]["items"], [])

    def test_holding_routes_are_private_manual_and_reject_modified_positions(self):
        engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
        self.addCleanup(engine.dispose)
        Base.metadata.create_all(engine)
        with Session(engine) as db:
            db.add_all([
                FundFavorite(user_id=owner, code="0.000823", name="超声电子", asset_type="stock", secid="0.000823",
                             shares=100, cost_price=10, added_at=NOW) for owner in (1, 2)
            ] + [FundFavorite(user_id=1, code="000823", name="同号基金", asset_type="fund", shares=200, cost_price=1, added_at=NOW)])
            db.commit()
        app = FastAPI()
        app.include_router(router, prefix="/api")
        def session():
            with Session(engine) as db:
                yield db
        app.dependency_overrides[get_db] = session
        owner = SimpleNamespace(id=1)
        path = "/api/funds/favorites/0.000823/holding-analysis"
        with TestClient(app) as client, \
                patch.object(single_stock, "load_market", return_value=market()), \
                patch.object(single_stock, "_snapshots", single_stock.OrderedDict()), \
                patch.object(deepseek, "now_local", return_value=NOW), \
                patch.object(deepseek, "SessionLocal", side_effect=lambda: Session(engine)), \
                patch.object(deepseek, "request_analysis") as request:
            self.assertEqual(client.get(path).status_code, 401)
            app.dependency_overrides[require_auth] = lambda: owner
            self.assertEqual(client.get(path.replace("0.000823", "000823")).status_code, 400)
            with patch("backend.app.routers.api.ai_settings.analysis_configs",
                       return_value={"ai_config": CREDS, "ai_profiles": [CREDS]}):
                preview = client.get(path).json()
                suffix = "?snapshot_id=" + preview["snapshot_id"]
                self.assertEqual(client.get(path + "/status" + suffix).status_code, 200)
                owner.id = 2
                self.assertEqual(client.post(path + "/analyze" + suffix, json={"profile_ids": ["default"]}).status_code, 409)
                owner.id = 1
                request.assert_not_called()
                self.assertEqual(client.post(path + "/analyze" + suffix, json={"profile_ids": ["default"]}).status_code, 200)
                self.assertEqual(request.call_args.args[0]["holding"]["shares"], 100)
                self.assertEqual(client.put("/api/funds/favorites/0.000823/position",
                                            json={"shares": 200, "cost_price": 11}).status_code, 200)
                self.assertEqual(client.post(path + "/analyze" + suffix, json={"profile_ids": ["default"]}).status_code, 409)
                request.assert_called_once()
