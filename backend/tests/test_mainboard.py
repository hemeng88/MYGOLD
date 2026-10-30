import unittest
from datetime import datetime
from unittest.mock import patch

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from backend.app.database import Base
from backend.app.models import MainboardMeta, MainboardStock
from backend.app.stocks import collector, universe


class MainboardUniverseTests(unittest.TestCase):
    def test_board_and_st_rules(self):
        self.assertEqual(universe.board_of("600519"), "主板")
        self.assertEqual(universe.board_of("000001"), "主板")
        self.assertEqual(universe.board_of("002475"), "主板")
        self.assertEqual(universe.board_of("003816"), "主板")
        self.assertEqual(universe.board_of("300750"), "创业板")
        self.assertEqual(universe.board_of("688981"), "科创板")
        self.assertEqual(universe.board_of("830799"), "北交所")
        self.assertTrue(universe.is_st("*ST闻泰"))
        self.assertTrue(universe.is_st("ST extra"))
        self.assertFalse(universe.is_st("贵州茅台"))
        self.assertEqual(universe.classify("300750", "宁德时代")[1], False)
        self.assertEqual(universe.classify("600745", "*ST闻泰")[2], "ST")
        self.assertEqual(universe.classify("600519", "贵州茅台"), ("主板", True, None))

    def test_avg_and_vs(self):
        closes = [10 + i * 0.1 for i in range(66)]
        avg = universe.window_avg(closes)
        self.assertAlmostEqual(avg, sum(closes) / 66)
        self.assertEqual(universe.vs_avg_pct(closes[-1], avg), round((closes[-1] / avg - 1) * 100, 2))
        self.assertEqual(universe.lot_cost(13.69), 1369.0)
        self.assertIsNone(universe.window_avg([1, 2, 3]))

    def test_stale_kline_dropped(self):
        bars = [("2025-01-%02d" % day, 10.0) for day in range(1, 28)]
        bars.append(("2025-08-12", 20.0))
        self.assertIsNone(universe.summarize_klines(bars, "2026-10-29"))
        fresh = [("2026-07-%02d" % day, 10.0) for day in range(1, 23)]
        fresh.append(("2026-10-29", 9.0))
        summary = universe.summarize_klines(fresh, "2026-10-29")
        self.assertIsNotNone(summary)
        self.assertEqual(summary["window_end"], "2026-10-29")
        self.assertEqual(summary["last"], 9.0)


class MainboardCollectorTests(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine("sqlite://")
        Base.metadata.create_all(self.engine)
        self.db = Session(self.engine)

    def tearDown(self):
        self.db.close()
        self.engine.dispose()

    @patch("backend.app.stocks.collector.fetch_market_trade_date", return_value="2026-10-29")
    def test_collect_and_quote_updates_vs_avg(self, _trade_date):
        bars = [("2026-07-%02d" % day, 10.0) for day in range(1, 23)]
        bars.append(("2026-10-29", 10.0))
        result = collector.collect_universe(
            self.db,
            fetch_counts=lambda: {"hs_a": 10, "sh_a": 6, "sz_a": 7, "cyb": 2, "kcb": 1, "main_est": 10},
            fetch_hs300=lambda: [
                {"code": "600519", "name": "贵州茅台", "symbol": "sh600519", "trade": 1354},
                {"code": "300750", "name": "宁德时代", "symbol": "sz300750", "trade": 200},
                {"code": "600745", "name": "*ST闻泰", "symbol": "sh600745", "trade": 30},
            ],
            fetch_klines=lambda symbol: bars,
        )
        self.assertTrue(result["ok"])
        self.assertEqual(result["klines"], 1)
        listed = collector.list_mainboard(self.db)
        self.assertTrue(listed["ready"])
        self.assertEqual(listed["usable"], 1)
        self.assertEqual(listed["items"][0]["code"], "600519")
        self.assertEqual({row["reason"] for row in listed["blocked_items"]}, {"创业板", "ST"})

        collector.collect_quotes(
            self.db,
            quote_loader=lambda _secids: {
                "1.600519": {
                    "secid": "1.600519",
                    "price": 8.0,
                    "change_pct": -2.0,
                    "name": "贵州茅台",
                    "trade_date": "2026-10-30",
                }
            },
        )
        listed = collector.list_mainboard(self.db)
        row = listed["items"][0]
        self.assertEqual(row["last"], 8.0)
        self.assertEqual(row["vs_avg_pct"], universe.vs_avg_pct(8.0, row["avg3m"]))
        self.assertEqual(row["lot_cost"], 800.0)

    @patch("backend.app.stocks.collector.fetch_market_trade_date", return_value="2026-10-29")
    def test_empty_hs300_keeps_old_rows(self, _trade_date):
        self.db.add(
            MainboardStock(
                secid="1.600519",
                code="600519",
                name="贵州茅台",
                symbol="sh600519",
                board="主板",
                eligible=1,
                last=10,
                avg3m=11,
                vs_avg_pct=-9.09,
                kline_at=datetime(2026, 10, 29),
            )
        )
        self.db.add(MainboardMeta(id=1, usable_count=1, hs300_count=1))
        self.db.commit()
        with self.assertRaises(RuntimeError):
            collector.collect_universe(
                self.db,
                fetch_counts=lambda: {"hs_a": 0, "sh_a": 0, "sz_a": 0, "cyb": 0, "kcb": 0, "main_est": 0},
                fetch_hs300=lambda: [],
                fetch_klines=lambda symbol: [],
            )
        self.assertEqual(self.db.get(MainboardStock, "1.600519").name, "贵州茅台")


if __name__ == "__main__":
    unittest.main()
