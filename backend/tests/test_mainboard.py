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

    def test_period_windows(self):
        from datetime import date, timedelta

        start = date(2025, 10, 1)
        bars = [((start + timedelta(days=i)).isoformat(), 10.0 + i) for i in range(260)]
        self.assertEqual(len(universe.period_window(bars, "1m")), 22)
        self.assertEqual(len(universe.period_window(bars, "6m")), 122)
        self.assertEqual(len(universe.period_window(bars, "1y")), 244)
        ytd = universe.period_window(bars, "ytd")
        self.assertEqual(ytd[0][0], "2026-01-01")
        stats = universe.period_stats(bars, "1m")
        closes = [item[1] for item in bars[-22:]]
        self.assertEqual(stats["avg"], round(sum(closes) / 22, 3))
        self.assertEqual(stats["first"], closes[0])
        self.assertEqual(set(universe.all_period_stats(bars)), {"1m", "3m", "6m", "ytd", "1y"})
        # 只有 30 根时一年和半年都不出数，不拿短窗口冒充
        self.assertEqual(set(universe.all_period_stats(bars[-30:])), {"1m", "ytd"})


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

        one_month = collector.list_mainboard(self.db, "1m")
        self.assertEqual(one_month["period"], "1m")
        self.assertEqual(one_month["items"][0]["avg"], 10.0)
        self.assertEqual(one_month["items"][0]["period_change_pct"], -20.0)
        self.assertEqual(collector.list_mainboard(self.db, "bogus")["period"], "3m")

        index_bars = [("2026-07-%02d" % day, 3000.0 + day) for day in range(1, 23)]
        detail = collector.mainboard_detail(self.db, "600519", "1m", index_loader=lambda symbol: index_bars)
        self.assertEqual(detail["series"][-1], {"d": "2026-10-30", "c": 8.0})
        self.assertEqual(len(detail["indexes"]), 3)
        self.assertEqual(detail["indexes"][0]["name"], "上证指数")
        self.assertIsNone(collector.mainboard_detail(self.db, "300750", "1m"))

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
