"""
Stats for the Review page: daily-log averages, habit completion and timetable hours per category,
over the last N days or all time.
"""

from datetime import date, timedelta

from .categories import load_categories
from .database import db
from .dates import local_today
from .days import confirmed_days
from .grid import slot_of
from .habits import get_habits, habit_targets
from .journal import entries_between
from .timetable import blocks_between


def period_start(days, today=None):
    """First day of a period of `days` days ending today; None = since the first record."""
    today = today or local_today()
    if days:
        return today - timedelta(days=days - 1)
    with db() as conn:
        first = conn.execute(
            "SELECT MIN(d) FROM (SELECT MIN(date) d FROM entries UNION SELECT MIN(date) FROM habit_log"
            " UNION SELECT MIN(date) FROM tt_entries)"
        ).fetchone()[0]
    return date.fromisoformat(first) if first else today


def get_stats(days=None, today=None):
    """
    Summary for the last `days` days (None = all time): averages, habit
    completion %, and timetable hours per category for plan and actual.
    """
    today = today or local_today()
    start = period_start(days, today)
    first, last = start.isoformat(), today.isoformat()
    num_days = (today - start).days + 1

    entries = entries_between(first, last)

    def avg(col):
        vals = [v for v in entries[col] if v is not None] if len(entries) else []
        return round(sum(vals) / len(vals), 2) if vals else None

    with db() as conn:
        counts = dict(conn.execute(
            "SELECT habit_id, COUNT(*) FROM habit_log WHERE date BETWEEN ? AND ? GROUP BY habit_id",
            (first, last),
        ).fetchall())
    targets = habit_targets()      # a 3-times-a-week habit is 100% at 3 ticks a week
    habits = {name: round(min(100.0, 100 * counts.get(hid, 0) / (num_days * targets[hid] / 7 if hid in targets else num_days)), 1)
              for hid, name in get_habits()}

    cats = load_categories()
    names = dict(zip(cats["id"], cats["name"]))
    hours = {"plan": {}, "actual": {}}
    confirmed = set(confirmed_days(first, last))     # Plan vs Actual only on days the user confirmed
    for b in blocks_between(first, last):
        if b["date"] not in confirmed:
            continue
        name = names.get(b["category_id"], "Uncategorised")
        h = (slot_of(b["end"]) - slot_of(b["start"])) / 2
        hours[b["track"]][name] = hours[b["track"]].get(name, 0) + h

    return {
        "start": first, "end": last, "days": num_days,
        "days_logged": len(entries),
        "avg_mood": avg("mood"), "avg_sleep": avg("sleep"), "avg_energy": avg("energy"),
        "avg_productivity": avg("productivity"),
        "avg_water": avg("water"),
        "habit_completion_pct": habits,
        "timetable_hours": hours,
        "days_confirmed": len(confirmed),
    }
