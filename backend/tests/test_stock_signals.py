import unittest
from unittest.mock import patch
from types import SimpleNamespace

from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.app.auth import require_auth
from backend.app.routers.api import router

from backend.app.stocks.signals import candidate, scan_market


def quote(code="000823", symbol="sz000823", **changes):
    row = dict(code=code, symbol=symbol, name="测试股票", trade="10.5", open="10.1",
               high="10.8", low="9.9", amount=210000000, volume=20000000,
               changepercent=3.1, turnoverratio=2.5, ticktime="10:30:00")
    row.update(changes)
    return row


class SignalsTests(unittest.TestCase):
    def test_authenticated_api_and_refresh_dispatch(self):
        app = FastAPI()
        app.include_router(router, prefix="/api")
        app.dependency_overrides[require_auth] = lambda: SimpleNamespace(id=1)
        with TestClient(app) as client, patch("backend.app.routers.api.get_signals", return_value={"running": True}) as get:
            self.assertEqual(client.get("/api/stocks/signals").json(), {"running": True})
            get.assert_called_with()
            self.assertEqual(client.post("/api/stocks/signals/refresh").status_code, 200)
            get.assert_called_with(refresh=True)

    def test_prices_come_from_observed_data(self):
        item = candidate(quote())
        self.assertEqual((item["watch_low"], item["watch_high"]), (10.5, 10.5))
        self.assertEqual(item["breakout_price"], 10.8)
        self.assertEqual(item["invalidation_price"], 9.9)

    def test_rejects_invalid_suspended_st_and_illiquid_quotes(self):
        for changes in [dict(name="*ST测试"), dict(trade=0), dict(volume=0),
                        dict(trade="NaN"), dict(high="Infinity"), dict(amount=5000),
                        dict(low=12), dict(changepercent=9.9), dict(turnoverratio=None),
                        dict(symbol="sh000001")]:
            with self.subTest(changes=changes):
                self.assertIsNone(candidate(quote(**changes)))

    @patch("backend.app.stocks.signals.fetch_market_trade_date", return_value="2026-11-26")
    def test_all_boards_counted_including_beijing(self, _date):
        rows = [quote(), quote("600519", "sh600519"), quote("300001", "sz300001"),
                quote("688001", "sh688001"), quote("920001", "bj920001")]
        result = scan_market(get_json=lambda *args: rows, count_loader=lambda node: 5)
        self.assertTrue(result["complete"])
        self.assertEqual(result["scanned"], 5)
        self.assertEqual(result["boards"], {"主板": 2, "创业板": 1, "科创板": 1, "北交所": 1})

    @patch("backend.app.stocks.signals.fetch_market_trade_date", return_value=None)
    def test_repeated_pages_do_not_claim_complete_coverage(self, _date):
        result = scan_market(get_json=lambda *args: [quote()], count_loader=lambda node: 81)
        self.assertFalse(result["complete"])
        self.assertEqual(result["scanned"], 1)
        self.assertTrue(result["errors"])

    @patch("backend.app.stocks.signals.fetch_market_trade_date", return_value=None)
    def test_source_failure_is_visible(self, _date):
        result = scan_market(count_loader=lambda node: 0)
        self.assertFalse(result["complete"])
        self.assertEqual(result["items"], [])


if __name__ == "__main__":
    unittest.main()
