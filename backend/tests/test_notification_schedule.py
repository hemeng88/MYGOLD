import unittest
from unittest.mock import MagicMock, patch

from backend.app import scheduler


class NotificationScheduleTests(unittest.TestCase):
    def test_configured_openclaw_does_not_register_notifications(self):
        fake_scheduler = MagicMock(running=False)
        with patch.object(scheduler, "scheduler", fake_scheduler), patch.multiple(
            scheduler.settings,
            openclaw_webhook_url="https://example.com/hooks/agent",
            openclaw_webhook_token="test-token",
            openclaw_target="test-recipient",
            openclaw_report_username="test-user",
            portfolio_report_hour=16,
            portfolio_report_minute=10,
        ):
            scheduler.start_scheduler()

        job_ids = [call.kwargs["id"] for call in fake_scheduler.add_job.call_args_list]
        self.assertCountEqual(job_ids, [
            "fund-quotes", "fund-navs", "fund-holdings", "fund-rankings",
            "mainboard-quotes", "mainboard-klines", "mainboard-bootstrap",
            "stock-close-archive", "stock-scan", "stock-history-bootstrap",
        ])
        fake_scheduler.start.assert_called_once_with()
