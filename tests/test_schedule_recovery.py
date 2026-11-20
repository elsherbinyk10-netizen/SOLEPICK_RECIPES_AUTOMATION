import datetime
import unittest
from zoneinfo import ZoneInfo

import recipe_worker


CAIRO = ZoneInfo("Africa/Cairo")


class ScheduleRecoveryTests(unittest.TestCase):
    def test_regular_cairo_windows_remain_approved_in_winter(self):
        now = datetime.datetime(2026, 11, 20, 9, 0, tzinfo=CAIRO)
        for hour in (9, 10, 11, 12):
            cron = f"0 {hour - 2} * * *"
            with self.subTest(cairo_hour=hour):
                self.assertTrue(recipe_worker.should_run_scheduled_event(cron, now))

    def test_thirteenth_hour_recovery_is_approved_in_winter(self):
        now = datetime.datetime(2026, 11, 20, 13, 0, tzinfo=CAIRO)
        self.assertTrue(recipe_worker.should_run_scheduled_event("0 11 * * *", now))

    def test_thirteenth_hour_recovery_is_approved_in_summer(self):
        now = datetime.datetime(2026, 7, 20, 13, 0, tzinfo=CAIRO)
        self.assertTrue(recipe_worker.should_run_scheduled_event("0 10 * * *", now))

    def test_unapproved_later_cron_is_rejected(self):
        now = datetime.datetime(2026, 11, 20, 14, 0, tzinfo=CAIRO)
        self.assertFalse(recipe_worker.should_run_scheduled_event("0 12 * * *", now))


if __name__ == "__main__":
    unittest.main()
