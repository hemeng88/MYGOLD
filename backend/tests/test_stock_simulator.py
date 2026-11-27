import json
import unittest
from datetime import datetime, timedelta
from types import SimpleNamespace
from unittest.mock import patch

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from backend.app.auth import require_auth
from backend.app.database import Base, get_db
from backend.app.models import StockCloseArchive, StockSimAccount
from backend.app.routers.api import router
from backend.app.schemas import StockSimConfig
from backend.app.stocks import simulator
from backend.app.stocks.simulator_quotes import BENCHMARK, Quote, _parse

SYMBOL = "sz000823"
OPEN = datetime(2026, 11, 27, 9, 36)
NEXT = datetime(2026, 11, 30, 9, 36)


def quote(moment, last=1000, size=500, bid=999, ask=1000, status="00"):
    return Quote("超声电子", moment - timedelta(seconds=5), last, bid, size, ask, size, 50000, status)


class SimulatorTests(unittest.TestCase):
    def setUp(self):
        engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
        self.addCleanup(engine.dispose)
        Base.metadata.create_all(engine)
        self.session = sessionmaker(engine, autoflush=False)
        self.config = StockSimConfig(strategies=["trend"], require_factors=True)

    def create(self):
        with self.session() as db, patch.object(simulator, "now_local", return_value=OPEN - timedelta(minutes=20)):
            simulator.save_config(db, 1, self.config)
            simulator.set_running(db, 1, True)
            db.add(StockCloseArchive(scope="主板|price=0:50", trade_date="2026-11-26", snapshot_json=json.dumps({
                "complete": True, "close_ready": True, "items": [
                    {"symbol": SYMBOL, "code": "000823", "name": "超声电子", "board": "主板", "strategies": ["trend"],
                     "factors": {"passed": True}},
                    {"symbol": "sh600000", "code": "600000", "name": "浦发银行", "board": "主板", "strategies": ["trend"],
                     "factors": {"passed": False}},
                ],
            })))
            db.commit()
            self.assertEqual(simulator.entry_scopes(db), {"主板|price=0:50"})

    def tick(self, moment, stock, market_day=None):
        prior = [("2026-11-26", 4200)]
        if moment.date() == NEXT.date():
            prior.append(("2026-11-27", 4210))
        bench = Quote("沪深300", moment - timedelta(seconds=5), 422000, 0, 0, 0, 0, 1000, "00")
        quotes = {SYMBOL: stock, BENCHMARK: bench}
        with patch.object(simulator, "now_local", return_value=moment), \
                patch.object(simulator, "SessionLocal", self.session), \
                patch.object(simulator, "fetch_market_trade_date", return_value=market_day or moment.date().isoformat()), \
                patch.object(simulator.research, "history", return_value=prior), \
                patch.object(simulator, "fetch", side_effect=lambda symbols: {s: quotes[s] for s in symbols if quotes.get(s)}):
            simulator.run_cycle()

    def state(self, user_id=1):
        with self.session() as db:
            return simulator.view(db, user_id, "all")

    def test_stale_quotes_do_not_fill_then_cash_and_partial_sales_reconcile(self):
        self.create()
        self.tick(OPEN, quote(OPEN - timedelta(minutes=4)))
        self.assertFalse(self.state()["trades"])
        fill = OPEN + timedelta(minutes=1)
        self.tick(fill, quote(fill))
        state = self.state()
        self.assertEqual(state["positions"][0]["shares"], 400)
        self.assertEqual(state["account"]["cash"], 15993)
        self.assertEqual(state["trades"][0]["signal_day"], "2026-11-26")

        afternoon = OPEN.replace(hour=13)
        self.tick(afternoon, quote(afternoon, last=800, bid=800, ask=801))
        self.assertEqual(len(self.state()["trades"]), 1)
        self.tick(NEXT, quote(NEXT, last=900, bid=0, ask=900))
        self.assertEqual(self.state()["positions"][0]["exit_reason"], "止损")
        sell = NEXT + timedelta(minutes=1)
        first = quote(sell, last=900, bid=900, ask=901, size=100)
        self.tick(sell, first)
        self.tick(sell + timedelta(seconds=35), first)
        self.assertEqual(self.state()["positions"][0]["shares"], 300)
        finish = sell + timedelta(minutes=1)
        self.tick(finish, quote(finish, last=900, bid=900, ask=901))
        state = self.state()
        self.assertFalse(state["positions"])
        self.assertEqual(state["account"]["cash"], 19579.4)
        self.assertEqual(state["period"]["realized"], -420.6)
        self.assertEqual(state["period"]["trade_count"], 3)
        self.assertEqual(len(state["curve"]), 2)
        self.assertEqual(self.state(2), {"account": None})

    def test_pause_marks_positions_without_selling_and_holiday_leaves_no_point(self):
        self.create()
        self.tick(OPEN, quote(OPEN))
        with self.session() as db, patch.object(simulator, "now_local", return_value=NEXT - timedelta(hours=1)):
            simulator.set_running(db, 1, False)
            self.assertEqual(simulator.entry_scopes(db), set())
        self.tick(NEXT, quote(NEXT, last=800, bid=800, ask=801), market_day="2026-11-27")
        self.assertEqual(len(self.state()["curve"]), 1)
        self.tick(NEXT, quote(NEXT, last=800, bid=800, ask=801))
        state = self.state()
        self.assertEqual(state["positions"][0]["price"], 8)
        self.assertEqual(len(state["trades"]), 1)
        self.assertEqual(len(state["curve"]), 2)

    def test_drawdown_blocks_new_entries_and_close_point_stays_final(self):
        self.create()
        with self.session() as db:
            account = db.get(StockSimAccount, 1)
            account.peak_cents = 2500000
            db.commit()
        self.tick(OPEN, quote(OPEN))
        state = self.state()
        self.assertFalse(state["trades"])
        self.assertIn("回撤阈值", state["account"]["message"])
        close = OPEN.replace(hour=15, minute=3)
        self.tick(close, None)
        self.assertTrue(self.state()["curve"][-1]["final_mark"])
        self.assertEqual(self.state()["account"]["max_drawdown_pct"], 20)
        self.tick(close + timedelta(minutes=1), None)
        self.assertEqual(self.state()["account"]["checked_at"], close)

    def test_wont_trade_on_an_archive_older_than_the_previous_session(self):
        self.create()
        self.tick(NEXT, quote(NEXT))
        state = self.state()
        self.assertFalse(state["trades"])
        self.assertIn("上一交易日", state["account"]["message"])

    def test_account_routes_create_pause_update_and_restrict_starting_capital(self):
        app = FastAPI()
        app.include_router(router, prefix="/api")
        def get_session():
            with self.session() as db:
                yield db
        app.dependency_overrides[get_db] = get_session
        with TestClient(app) as client:
            self.assertEqual(client.get("/api/stocks/simulator").status_code, 401)
            app.dependency_overrides[require_auth] = lambda: SimpleNamespace(id=51)
            self.assertEqual(client.put("/api/stocks/simulator/run", json={"running": True}).status_code, 409)
            payload = self.config.model_dump()
            self.assertEqual(client.put("/api/stocks/simulator/config", json=payload).status_code, 200)
            self.assertFalse(client.get("/api/stocks/simulator").json()["account"]["running"])
            self.assertEqual(client.put("/api/stocks/simulator/run", json={"running": True}).status_code, 200)
            self.assertTrue(client.get("/api/stocks/simulator?period=7").json()["account"]["running"])
            self.assertEqual(client.put("/api/stocks/simulator/config", json=dict(payload, starting_cash=12000)).status_code, 400)
            self.assertEqual(client.put("/api/stocks/simulator/config", json=dict(payload, hold_days=10)).status_code, 200)
            with self.session() as db:
                self.assertEqual(db.get(StockSimAccount, 51).cash_cents, 2000000)

    def test_sina_snapshot_keeps_exchange_time_and_book_sides(self):
        fields = ["0"] * 33
        fields[0], fields[3], fields[8] = "超声电子", "10.05", "12345"
        fields[10], fields[11], fields[20], fields[21] = "500", "10.04", "800", "10.06"
        fields[30], fields[31], fields[32] = "2026-11-27", "09:36:00", "00"
        parsed = _parse(SYMBOL, ",".join(fields))
        self.assertEqual((parsed.at, parsed.bid, parsed.bid_size, parsed.ask, parsed.ask_size), (OPEN, 1004, 500, 1006, 800))
        fields[31] = "--"
        self.assertIsNone(_parse(SYMBOL, ",".join(fields)))
