import unittest
from datetime import date, datetime

from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from backend.app.database import Base
from backend.app.misc import countdowns
from backend.app.misc.holidays import next_holiday
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
        self.assertEqual([row["title"] for row in mine], ["发工资", "某游戏", "元旦", "已过发售"])
        self.assertEqual([row["title"] for row in countdowns.list_countdowns(self.db, 2, self.now)], ["别人的", "元旦"])
        self.assertTrue(mine[2]["builtin"])
        payday = next(row for row in mine if row["title"] == "发工资")
        self.assertFalse(payday["builtin"])

        updated = countdowns.update_countdown(
            self.db, 1, mine[0]["id"], {"title": "发工资日", "kind": "monthly", "day": 10}, self.now
        )
        self.assertEqual(updated["title"], "发工资日")
        self.assertEqual(updated["next_date"], "2026-11-10")

        countdowns.delete_countdown(self.db, 1, mine[0]["id"])
        left = countdowns.list_countdowns(self.db, 1, self.now)
        self.assertEqual([row["title"] for row in left if not row["builtin"]], ["某游戏", "已过发售"])
        self.assertEqual(len(left), 3)
        with self.assertRaises(KeyError):
            countdowns.delete_countdown(self.db, 2, mine[1]["id"])
        leftover = list(self.db.scalars(select(CountdownItem)).all())
        self.assertEqual(len(leftover), 3)
        with self.assertRaises(ValueError):
            countdowns.update_countdown(self.db, 1, countdowns.HOLIDAY_ITEM_ID, {"title": "x", "kind": "once", "date": "2027-01-01"}, self.now)
        with self.assertRaises(ValueError):
            countdowns.delete_countdown(self.db, 1, countdowns.HOLIDAY_ITEM_ID)


class HolidayLookupTests(unittest.TestCase):
    def test_next_holiday_skips_ended_blocks(self):
        # 2026 国庆已过，下一次是 2027 元旦
        found = next_holiday(date(2026, 11, 6))
        self.assertEqual(found["name"], "元旦")
        self.assertEqual(found["start"].isoformat(), "2027-01-01")
        self.assertEqual(found["end"].isoformat(), "2027-01-03")
        self.assertEqual(found["days"], 3)
        self.assertEqual(found["status"], "upcoming")

    def test_holiday_stays_current_until_last_rest_day(self):
        mid = next_holiday(date(2026, 2, 20))
        self.assertEqual(mid["name"], "春节")
        self.assertEqual(mid["status"], "today")
        last = next_holiday(date(2026, 2, 23))
        self.assertEqual(last["status"], "today")
        after = next_holiday(date(2026, 2, 24))
        self.assertEqual(after["name"], "清明节")
        self.assertEqual(after["start"].isoformat(), "2026-04-04")

    def test_single_day_holiday_and_table_end(self):
        duanwu = next_holiday(date(2027, 6, 9))
        self.assertEqual(duanwu["name"], "端午节")
        self.assertEqual(duanwu["days"], 1)
        self.assertEqual(duanwu["status"], "today")
        self.assertIsNone(next_holiday(date(2027, 10, 8)))

    def test_list_injects_builtin_holiday(self):
        engine = create_engine("sqlite://")
        Base.metadata.create_all(engine)
        db = Session(engine)
        now = datetime(2026, 11, 6, 15, 0)
        items = countdowns.list_countdowns(db, 1, now)
        self.assertEqual(len(items), 1)
        row = items[0]
        self.assertTrue(row["builtin"])
        self.assertEqual(row["kind"], "holiday")
        self.assertEqual(row["title"], "元旦")
        self.assertEqual(row["next_date"], "2027-01-01")
        self.assertIn("共 3 天", row["rule_label"])
        db.close()
        engine.dispose()


if __name__ == "__main__":
    unittest.main()
