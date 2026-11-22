"""Frontdesk's Kolkata business-hours calendar."""

from datetime import datetime, time, timedelta
from zoneinfo import ZoneInfo

ZONE = ZoneInfo("Asia/Kolkata")
OPEN = time(9, 30)
CLOSE = time(18, 30)
WORKDAY = timedelta(hours=9)
WORKWEEK = 5 * WORKDAY
REPLY_TARGET = {
    "urgent": timedelta(hours=2),
    "medium": WORKDAY / 2,
    "low": WORKDAY,
}


class BusinessCalendar:
    def __init__(self, holidays=()):
        self.holidays = frozenset(holidays)

    def hours_on(self, day):
        if day.weekday() >= 5 or day in self.holidays:
            return None
        return datetime.combine(day, OPEN, ZONE), datetime.combine(day, CLOSE, ZONE)

    def deadline(self, start, budget):
        if budget < timedelta():
            raise ValueError("Business-time budget must be nonnegative")
        cursor = start.astimezone(ZONE)
        while True:
            hours = self.hours_on(cursor.date())
            if hours:
                opening, closing = hours
                if cursor < closing:
                    cursor = max(cursor, opening)
                    available = closing - cursor
                    if budget <= available:
                        return cursor + budget
                    budget -= available
            cursor = datetime.combine(cursor.date() + timedelta(days=1), OPEN, ZONE)

    def elapsed(self, start, end):
        start, end = start.astimezone(ZONE), end.astimezone(ZONE)
        total = timedelta()
        day = start.date()
        while day <= end.date():
            hours = self.hours_on(day)
            if hours:
                opening, closing = hours
                total += max(timedelta(), min(closing, end) - max(opening, start))
            day += timedelta(days=1)
        return total

    def resolution_budget(self, priority, start):
        if priority == "urgent":
            first_working_instant = self.deadline(start, timedelta())
            return datetime.combine(first_working_instant.date(), CLOSE, ZONE) - first_working_instant
        return {"medium": 3 * WORKDAY, "low": WORKWEEK}[priority]
