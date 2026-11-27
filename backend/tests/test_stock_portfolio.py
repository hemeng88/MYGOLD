from datetime import date, timedelta
from threading import Event
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.app.auth import require_auth
from backend.app.database import get_db
from backend.app.routers.api import router
from backend.app.schemas import StockPortfolioIn
from backend.app.stocks import portfolio, research


class PortfolioTests(unittest.TestCase):
    def setUp(self):
        self.days = [(date(2026, 1, 1) + timedelta(days=i)).isoformat() for i in range(74)]
        self.symbols = ["sz000001", "sz000002", "sz000003"]
        self.sample = [{"symbol": symbol, "board": "主板", "liquidity_band": "high"} for symbol in self.symbols]
        self.config = StockPortfolioIn(starting_cash=2000, max_positions=1, max_position_pct=60).model_dump()

    def replay(self, changes, price_max=50):
        raw = {symbol: [(day, 10, 10.1, 9.9) for day in self.days] for symbol in self.symbols}
        for symbol, index, bar in changes:
            raw[symbol][index] = (self.days[index], *bar) if bar else None
        raw = {symbol: [row for row in bars if row] for symbol, bars in raw.items()}
        adjusted = {symbol: [(day, close) for day, close, _, _ in bars] for symbol, bars in raw.items()}
        split = self.days[60]
        with patch.object(research, "triggers", side_effect=lambda stats: ["trend"] if stats and stats["as_of"] == split else []):
            return portfolio.simulate(self.sample, adjusted, raw, dict.fromkeys(self.days, 3000),
                                      split, self.days[-1], 0, price_max, self.config)

    def test_cash_costs_slots_locked_entry_and_delayed_exit(self):
        a, b, _ = self.symbols
        result = self.replay([(a, 61, (11, 11, 11)), (b, 66, (9, 9, 9)), (b, 67, None),
                              (b, 68, (11, 11.1, 10.9))])
        self.assertEqual(result["skipped"], {"no_buy_fill": 1, "outside_price_range": 0, "insufficient_budget": 0,
                                            "position_limit": 1, "delayed_exit_days": 2})
        self.assertEqual(result["closed_trades"], 1)
        self.assertEqual(result["win_pct"], 100)
        self.assertEqual(result["open_positions"], 0)
        self.assertAlmostEqual(result["cost_total"], 11.60, places=2)
        self.assertAlmostEqual(result["end_equity"], 2088.40, places=2)
        self.assertGreater(result["max_drawdown_pct"], 5)

    def test_minimum_commission_and_price_ceiling_can_stop_entry(self):
        self.config["max_position_pct"] = 50
        result = self.replay([(self.symbols[0], 61, (10.5, 10.6, 10.4))], price_max=10)
        self.assertEqual(result["skipped"]["insufficient_budget"], 2)
        self.assertEqual(result["skipped"]["outside_price_range"], 1)
        self.assertEqual(result["end_equity"], 2000)
        self.assertIsNone(result["win_pct"])

    def test_background_study_is_account_scoped_and_duplicate_start_is_reused(self):
        entered, release = Event(), Event()
        def study(*args):
            entered.set()
            release.wait(2)
            return {"closed_trades": 3}

        snapshot = {"complete": True, "research": {"split_date": self.days[60], "_study_sample": self.sample}}
        app = FastAPI()
        app.include_router(router, prefix="/api")
        app.dependency_overrides[require_auth] = lambda: SimpleNamespace(id=71)
        app.dependency_overrides[get_db] = lambda: None
        with patch.object(portfolio, "_jobs", {}), patch.object(portfolio, "_study", side_effect=study), \
                patch("backend.app.routers.api.load_prices", return_value=(0, 50)), \
                patch("backend.app.routers.api.load_boards", return_value=["主板"]), \
                patch("backend.app.routers.api.get_signals", return_value=snapshot) as scans:
            try:
                with TestClient(app) as client:
                    response = client.post("/api/stocks/portfolio-study?mode=close", json=self.config)
                    self.assertEqual(response.status_code, 202)
                    self.assertTrue(entered.wait(1))
                    duplicate = client.post("/api/stocks/portfolio-study?mode=close", json=self.config).json()
                    self.assertEqual(duplicate["id"], response.json()["id"])
                    self.assertEqual(client.get("/api/stocks/portfolio-study").json()["status"], "running")
                    self.assertEqual(portfolio.status(72), {"status": "idle"})
                    self.assertEqual(scans.call_args.kwargs["mode"], "close")
            finally:
                release.set()
                portfolio._executor.submit(lambda: None).result(timeout=2)
            self.assertEqual(portfolio.status(71)["result"], {"closed_trades": 3})
