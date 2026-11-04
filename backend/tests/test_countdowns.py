import unittest
from datetime import datetime

from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from backend.app.database import Base
from backend.app.misc import countdowns
from backend.app.models import CountdownItem


class CountdownResolveTests(unittest.TestCase):
    def test_once_future_today_past(self):
        now = datetime(2026, 11, 4, 15, 0)
        future = countdowns.resolve("once", "2026-12-15", None, None, None, now)
        self.assertEqual(future["status"], "upcoming")
        self.assertEqual(future["next_date"], "2026-12-15")
        self.assertGreater(future["remaining_seconds"], 0)

        today = countdowns.resolve("once", "2026-11-04", None, None, None, now)
        self.assertEqual(today["status"], "today")
        self.assertEqual(today["remaining_seconds"], 0)

        past = countdowns.resolve("once", "2026-10-01", None, None, None, now)
        self.assertEqual(past["status"], "past")
        self.assertEqual(past["elapsed_days"], 34)

    def test_once_with_time_rolls_to_past_after_clock(self):
        now = datetime(2026, 11, 4, 15, 0)
        before = countdowns.resolve("once", "2026-11-04", None, 18, 30, now)
        self.assertEqual(before["status"], "today")
        after = countdowns.resolve("once", "2026-11-04", None, 10, 0, now)
        self.assertEqual(after["status"], "past")

    def test_monthly_wraps_and_clamps_short_months(self):
        now = datetime(2026, 2, 20, 9, 0)
        feb = countdowns.resolve("monthly", None, 31, None, None, now)
        self.assertEqual(feb["next_date"], "2026-02-28")
        self.assertEqual(feb["status"], "upcoming")

        after = countdowns.resolve("monthly", None, 15, None, None, now)
        self.assertEqual(after["next_date"], "2026-03-15")
        self.assertEqual(after["status"], "upcoming")

        payday = countdowns.resolve("monthly", None, 20, None, None, now)
        self.assertEqual(payday["status"], "today")
        self.assertEqual(payday["next_date"], "2026-02-20")

        timed_out = countdowns.resolve("monthly", None, 20, 8, 0, now)
        self.assertEqual(timed_out["next_date"], "2026-03-20")
        self.assertEqual(timed_out["status"], "upcoming")

    def test_validate_rejects_bad_payloads(self):
        with self.assertRaises(ValueError):
            countdowns.validate_payload("", "once", "2026-12-15", None, None, None)
        with self.assertRaises(ValueError):
            countdowns.validate_payload("发售", "once", "2026-13-40", None, None, None)
        with self.assertRaises(ValueError):
            countdowns.validate_payload("工资", "monthly", None, 32, None, None)
        with self.assertRaises(ValueError):
            countdowns.validate_payload("工资", "weekly", None, 1, None, None)
        ok = countdowns.validate_payload(" 发工资 ", "monthly", None, 15, 10, 0)
        self.assertEqual(ok["title"], "发工资")
        self.assertEqual(ok["hour"], 10)


class CountdownStoreTests(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine("sqlite://")
        Base.metadata.create_all(self.engine)
        self.db = Session(self.engine)
        self.now = datetime(2026, 11, 4, 15, 0)

    def tearDown(self):
        self.db.close()
        self.engine.dispose()

    def test_crud_is_per_user_and_sorted(self):
        countdowns.add_countdown(
            self.db, 1, {"title": "已过发售", "kind": "once", "date": "2026-01-01"}, self.now
        )
        countdowns.add_countdown(
            self.db, 1, {"title": "发工资", "kind": "monthly", "day": 15}, self.now
        )
        countdowns.add_countdown(
            self.db, 1, {"title": "某游戏", "kind": "once", "date": "2026-12-15"}, self.now
        )
        countdowns.add_countdown(
            self.db, 2, {"title": "别人的", "kind": "once", "date": "2026-11-05"}, self.now
        )
        mine = countdowns.list_countdowns(self.db, 1, self.now)
        self.assertEqual([row["title"] for row in mine], ["发工资", "某游戏", "已过发售"])
        self.assertEqual([row["title"] for row in countdowns.list_countdowns(self.db, 2, self.now)], ["别人的"])

        updated = countdowns.update_countdown(
            self.db, 1, mine[0]["id"], {"title": "发工资日", "kind": "monthly", "day": 10}, self.now
        )
        self.assertEqual(updated["title"], "发工资日")
        self.assertEqual(updated["next_date"], "2026-11-10")

        countdowns.delete_countdown(self.db, 1, mine[0]["id"])
        self.assertEqual(len(countdowns.list_countdowns(self.db, 1, self.now)), 2)
        with self.assertRaises(KeyError):
            countdowns.delete_countdown(self.db, 2, mine[1]["id"])
        leftover = list(self.db.scalars(select(CountdownItem)).all())
        self.assertEqual(len(leftover), 3)


if __name__ == "__main__":
    unittest.main()
