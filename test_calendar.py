import unittest
from datetime import date, datetime, timedelta

from business_calendar import BusinessCalendar, ZONE


class BusinessCalendarTests(unittest.TestCase):
    def setUp(self):
        self.friday = datetime(2026, 11, 20, 18, tzinfo=ZONE)
        self.calendar = BusinessCalendar([date(2026, 11, 23)])

    def test_weekend_and_holiday(self):
        self.assertEqual(
            self.calendar.deadline(self.friday, timedelta(hours=2)),
            datetime(2026, 11, 24, 11, tzinfo=ZONE),
        )

    def test_elapsed_time_excludes_weekend(self):
        sunday = datetime(2026, 11, 22, 10, tzinfo=ZONE)
        self.assertEqual(self.calendar.elapsed(self.friday, sunday), timedelta(minutes=30))

    def test_urgent_target_uses_first_working_day(self):
        self.assertEqual(self.calendar.resolution_budget("urgent", self.friday), timedelta(minutes=30))
        self.assertEqual(
            self.calendar.resolution_budget("urgent", self.friday + timedelta(hours=1)),
            timedelta(hours=9),
        )

    def test_pause_extends_resolution_by_business_time(self):
        pause_end = datetime(2026, 11, 24, 10, 30, tzinfo=ZONE)
        paused = self.calendar.elapsed(self.friday, pause_end)
        self.assertEqual(paused, timedelta(minutes=90))
        self.assertEqual(
            self.calendar.deadline(self.friday, timedelta(hours=2) + paused),
            datetime(2026, 11, 24, 12, 30, tzinfo=ZONE),
        )
