from datetime import date, datetime, timedelta
import unittest
from unittest.mock import patch

from backend.app.stocks import factors
from backend.app.timeutil import to_unix_seconds


TODAY = date(2026, 11, 26)
NOW = datetime(2026, 11, 26, 14, 0)
FINANCIAL = {
    "SECURITY_CODE": "000823", "REPORTDATE": "2026-09-30 00:00:00",
    "NOTICE_DATE": "2026-10-28 00:00:00", "YSTZ": 15.2, "SJLTZ": 97.5,
    "PARENT_NETPROFIT": 352000000, "WEIGHTAVG_ROE": 6.66,
    "BOARD_NAME": "元件", "BOARD_CODE": "BK0459",
}


def history(rising=True):
    return [(str(TODAY - timedelta(days=80 - index)),
             100 * (1.002 if rising else 0.998) ** index) for index in range(80)]


def market(status="neutral"):
    return {"status": status, "trade_date": str(TODAY), "mean_change_pct": 1.0, "label": "大盘震荡"}


def sector(**changes):
    result = {"f57": "BK0459", "f58": "元件", "f170": 2.0, "f86": to_unix_seconds(NOW)}
    result.update(changes)
    return result


class FundamentalsTests(unittest.TestCase):
    def test_financials_do_not_use_future_or_same_day_disclosures(self):
        future = dict(FINANCIAL, REPORTDATE="2026-12-31", NOTICE_DATE="2027-01-20", YSTZ=999)
        same_day = dict(FINANCIAL, NOTICE_DATE=str(TODAY), YSTZ=888)
        result = factors.fundamentals([future, same_day, FINANCIAL], TODAY)
        self.assertEqual(result["revenue_yoy_pct"], 15.2)
        self.assertEqual(result["status"], "pass")
        self.assertEqual(factors.fundamentals([future, same_day], TODAY)["status"], "unknown")

    def test_latest_report_is_selected_and_missing_is_not_zero(self):
        older = dict(FINANCIAL, REPORTDATE="2026-06-30", NOTICE_DATE="2026-08-01")
        result = factors.fundamentals([older, dict(FINANCIAL, YSTZ=None)], TODAY)
        self.assertEqual(result["report_date"], "2026-09-30")
        self.assertIsNone(result["revenue_yoy_pct"])
        self.assertEqual(result["status"], "unknown")

    def test_loss_negative_growth_and_stale_reports_do_not_pass(self):
        for changes in ({"PARENT_NETPROFIT": -1}, {"WEIGHTAVG_ROE": 0}, {"YSTZ": -1}, {"SJLTZ": -1}):
            with self.subTest(changes=changes):
                self.assertEqual(factors.fundamentals([dict(FINANCIAL, **changes)], TODAY)["status"], "risk")
        old = dict(FINANCIAL, REPORTDATE="2025-12-31", NOTICE_DATE="2026-04-01")
        self.assertEqual(factors.fundamentals([old], TODAY)["status"], "unknown")

    def test_adapter_uses_verified_report_schema_and_checks_security(self):
        payload = {"success": True, "result": {"data": [FINANCIAL, dict(FINANCIAL, SECURITY_CODE="600519")]}}
        with patch.object(factors, "_cache", {}), patch.object(factors, "_get", return_value=payload) as get:
            self.assertEqual(factors.financial_rows("000823"), [FINANCIAL])
            self.assertEqual(factors.financial_rows("000823"), [FINANCIAL])
            get.assert_called_once()
            self.assertEqual(get.call_args.args[1]["reportName"], "RPT_LICO_FN_CPD")

    def test_source_failure_is_unknown_and_cached_briefly(self):
        with patch.object(factors, "_cache", {}), patch.object(factors, "_get", return_value={"success": False}) as get:
            self.assertEqual(factors.financial_rows("000823"), [])
            self.assertEqual(factors.financial_rows("000823"), [])
            get.assert_called_once()


class ContextTests(unittest.TestCase):
    @patch.object(factors, "now_local", return_value=NOW)
    def test_market_uses_both_index_trend_and_whole_market_breadth(self, _now):
        rows = [{"change_pct": 1}] * 60 + [{"change_pct": -1}] * 40
        result = factors.market_context(rows, {"sh000300": history()}, str(TODAY), True)
        self.assertEqual(result["status"], "favorable")
        self.assertEqual(result["advance_pct"], 60)
        falling = factors.market_context(rows, {"sh000300": history(False)}, str(TODAY), True)
        self.assertEqual(falling["status"], "weak")
        narrow = factors.market_context([{"change_pct": -1}] * 100, {"sh000300": history()}, str(TODAY), True)
        self.assertEqual(narrow["status"], "weak")
        incomplete = factors.market_context(rows, {"sh000300": history()}, str(TODAY), False)
        self.assertEqual(incomplete["status"], "unknown")
        old_date = factors.market_context(rows, {"sh000300": history()}, "2026-11-25", True)
        self.assertEqual(old_date["status"], "unknown")

    @patch.object(factors, "should_poll_quotes", return_value=True)
    @patch.object(factors, "now_local", return_value=NOW)
    def test_industry_requires_relative_strength_and_fresh_matching_data(self, _now, _poll):
        profile = {"f127": "元件"}
        result = factors.industry_context(profile, {}, sector(), market())
        self.assertEqual(result["status"], "pass")
        self.assertEqual(result["relative_pct"], 1.0)
        weak = factors.industry_context(profile, {}, sector(f170=0.5), market())
        self.assertEqual(weak["status"], "weak")
        for data in (sector(f58="银行"), sector(f86=0), sector(f86=to_unix_seconds(NOW - timedelta(hours=1))),
                     sector(f86=to_unix_seconds(NOW + timedelta(minutes=1))), sector(f170="-")):
            with self.subTest(data=data):
                self.assertEqual(factors.industry_context(profile, {}, data, market())["status"], "unknown")

    @patch.object(factors, "now_local", return_value=NOW)
    @patch.object(factors, "should_poll_quotes", return_value=True)
    def test_enrichment_cannot_override_technical_or_missing_evidence(self, _poll, _now):
        rows = [{"code": "000823", "priority_eligible": True}, {"code": "000001", "priority_eligible": False}]
        def loader(secid):
            return sector() if secid == "90.BK0459" else {"f127": "元件", "f198": "BK0459"}
        with patch.object(factors, "market_context", return_value=market()), \
                patch.object(factors, "financial_rows", return_value=[FINANCIAL]), patch.object(factors, "quote", side_effect=loader) as get:
            result = factors.enrich(rows, [], {}, str(TODAY), True)
        self.assertTrue(rows[0]["priority_eligible"])
        self.assertFalse(rows[1]["priority_eligible"])
        self.assertEqual(result["priority_count"], 1)
        self.assertEqual(sum(call.args[0] == "90.BK0459" for call in get.call_args_list), 1)
        with patch.object(factors, "market_context", return_value=market()), patch.object(factors, "_parallel", return_value={}):
            result = factors.enrich(rows, [], {}, str(TODAY), True)
        self.assertFalse(any(row["priority_eligible"] for row in rows))
        self.assertEqual(result["passed"], 0)
        self.assertTrue(rows[0]["factors"]["blockers"])

    def test_quote_identity_mismatch_is_not_accepted(self):
        with patch.object(factors, "_cache", {}), patch.object(factors, "_get", return_value={"data": {"f57": "600519"}}):
            self.assertEqual(factors.quote("0.000823"), {})

    @patch.object(factors, "now_local", return_value=NOW)
    def test_peer_fallback_requires_coverage_and_excludes_candidate_itself(self, _now):
        members = [dict(SECURITY_CODE=str(index).zfill(6), BOARD_NAME="元件", NOTICE_DATE="2026-10-28")
                   for index in range(8)]
        rows = [{"code": row["SECURITY_CODE"], "change_pct": 2} for row in members]
        rows[0]["change_pct"] = 99
        financial = {"industry_name": "元件"}
        result = factors.peer_context(financial, members, rows, market(), "000000")
        self.assertEqual(result["status"], "pass")
        self.assertEqual(result["sample_count"], 7)
        self.assertEqual(result["change_pct"], 2)
        self.assertEqual(result["relative_pct"], 1)
        self.assertIn("备用", result["method"])
        insufficient = factors.peer_context(financial, members, rows[:6], market(), "000000")
        self.assertEqual(insufficient["sample_count"], 5)
        self.assertEqual(insufficient["status"], "unknown")
        self.assertIsNone(insufficient["relative_pct"])
        unknown_market = factors.peer_context(financial, members, rows, market("unknown"), "000000")
        self.assertEqual(unknown_market["status"], "unknown")

    def test_peer_membership_must_be_complete_and_for_same_industry(self):
        for result in ({"pages": 2, "count": 1, "data": []},
                       {"pages": 1, "count": 2, "data": [{"BOARD_CODE": "BK0459"}]},
                       {"pages": 1, "count": 1, "data": [{"BOARD_CODE": "BK0001"}]}):
            with self.subTest(result=result), patch.object(factors, "_cache", {}), \
                    patch.object(factors, "_get", return_value={"success": True, "result": result}):
                self.assertEqual(factors.industry_members("BK0459"), [])

    @patch.object(factors, "now_local", return_value=NOW)
    def test_enrichment_uses_peer_fallback_when_index_is_unavailable(self, _now):
        members = [dict(SECURITY_CODE=str(index).zfill(6), BOARD_NAME="元件", NOTICE_DATE="2026-10-28")
                   for index in range(10)]
        market_items = [{"code": row["SECURITY_CODE"], "change_pct": 2} for row in members]
        rows = [{"code": "000823", "priority_eligible": True}]
        with patch.object(factors, "market_context", return_value=market()), \
                patch.object(factors, "financial_rows", return_value=[FINANCIAL]), \
                patch.object(factors, "quote", return_value={}), \
                patch.object(factors, "industry_members", return_value=members):
            result = factors.enrich(rows, market_items, {}, str(TODAY), True)
        self.assertEqual(result["passed"], 1)
        self.assertTrue(rows[0]["priority_eligible"])
        self.assertEqual(rows[0]["factors"]["industry"]["sample_count"], 10)
