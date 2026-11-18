"""
Dates and times: the time zone, "now" and "today", weeks, and periods.

Time zone: settings.json "timezone" (an IANA name like "America/New_York"), else the computer's
own. Every "now" and "today" in Venato goes through here.

Periods: each to-do and goal belongs to one period (a day, week or month), identified by its
first day (period_start); the period maths here is shared by both.
"""

from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

from .database import db
from .settings import load_settings, save_settings


def computer_zone_name():
    """The computer's time zone, e.g. "Europe/London" (UTC if it can't be found)."""
    try:
        import tzlocal
        return tzlocal.get_localzone_name() or "UTC"
    except Exception:       # no tzlocal, or an odd system setup
        return "UTC"


def zone_name():
    """The time zone Venato uses: the one chosen in Settings, else the computer's."""
    chosen = load_settings().get("timezone")
    if chosen:
        try:
            ZoneInfo(chosen)
            return chosen
        except (ValueError, KeyError, OSError):
            pass
    return computer_zone_name()


def tz():
    return ZoneInfo(zone_name())


# Weeks start on Monday, or Sunday if chosen (settings.json "week_start"; Settings -> Region).
WEEK_START = {"Monday": 0, "Sunday": 6}


def week_start_name():
    name = load_settings().get("week_start")
    return name if name in WEEK_START else "Monday"


def week_start_of(day):
    """The first day (Monday or Sunday) of the week containing `day`."""
    day = _as_date(day)
    return day - timedelta(days=(day.weekday() - WEEK_START[week_start_name()]) % 7)


def set_week_start(name):
    """Change the first day of the week, moving weekly to-dos to the new weeks' first days
    (Monday -> the Sunday before it; Sunday -> the Monday after it)."""
    if name not in WEEK_START or name == week_start_name():
        return
    shift = "-1 day" if name == "Sunday" else "+1 day"
    with db() as conn:
        conn.execute(f"UPDATE todos SET period_start = date(period_start, '{shift}') WHERE period = 'weekly'")
        conn.execute(f"UPDATE todo_rollover SET period_start = date(period_start, '{shift}') WHERE period = 'weekly'")
        conn.execute(f"UPDATE goal_week SET week_start = date(week_start, '{shift}')")
    save_settings(week_start=name)


def local_now():
    """Now, as a plain (naive) date and time in the user's time zone."""
    return datetime.now(tz()).replace(tzinfo=None)


def local_today():
    return datetime.now(tz()).date()


def stamp():
    """A timestamp for created_at / done_at columns (with its UTC offset)."""
    return datetime.now(tz()).isoformat(timespec="seconds")


def _as_date(day):
    return day if isinstance(day, date) else date.fromisoformat(str(day))


def fmt_day(day, fmt="%a %-d %b"):
    """strftime that also understands "%" + "-d" (the day without a leading zero), which
    Windows' strftime doesn't. E.g. 'Sat 7 Nov'."""
    day = _as_date(day)
    return day.strftime(fmt.replace("%-d", str(day.day)))


def start_of_period(period, day):
    """First day of the period containing `day`: the day, its Monday, the 1st, or 1 Jan."""
    day = _as_date(day)
    if period == "daily":
        return day
    if period == "weekly":
        return week_start_of(day)
    if period == "monthly":
        return day.replace(day=1)
    if period == "yearly":
        return day.replace(month=1, day=1)
    raise ValueError(f"Unknown todo period: {period}")


def shift_period(period, start, n):
    """The start of the period n periods after (or before, n < 0) the one starting at `start`."""
    start = start_of_period(period, start)
    if period == "daily":
        return start + timedelta(days=n)
    if period == "weekly":
        return start + timedelta(weeks=n)
    if period == "monthly":
        months = start.year * 12 + start.month - 1 + n
        return date(months // 12, months % 12 + 1, 1)
    return start.replace(year=start.year + n)


def end_of_period(period, start):
    """Last day of the period starting at `start`."""
    return shift_period(period, start, 1) - timedelta(days=1)


def _short(d, year=False):
    return f"{d.day} {d:%b}" + (f" {d.year}" if year else "")


def period_title(period, start, today=None):
    """
    A period's name relative to today: "Today", "Fri 30 Oct", "This week: 26 Oct to 1 Nov",
    "Last week: ...", "19 to 25 Oct", "November 2026", "2026".
    """
    today = today or local_today()
    start = start_of_period(period, start)
    if period == "daily":
        named = {0: "Today", -1: "Yesterday", 1: "Tomorrow"}.get((start - today).days)
        return named or f"{start:%a} {start.day} {start:%b}" + (f" {start.year}" if start.year != today.year else "")
    if period == "weekly":
        end = end_of_period(period, start)
        other_year = end.year != today.year
        span = (f"{start.day} to {_short(end, other_year)}" if start.month == end.month
                else f"{_short(start, start.year != end.year)} to {_short(end, other_year)}")
        weeks = (start - start_of_period("weekly", today)).days // 7
        named = {0: "This week", -1: "Last week", 1: "Next week"}.get(weeks)
        return f"{named}: {span}" if named else span
    if period == "monthly":
        return f"{start:%B %Y}"
    return str(start.year)
