"""
Goals: measurable targets with a deadline ("Gym 12 sessions by 31 Dec"), the week's split of
goal hours, and the days marked "I'm away" (no free time for goals).

A goal runs from period_start (the day it was set) to `due` (its deadline), inclusive.
Progress is either a number the user updates (`progress`), or, when the goal is linked to a
habit, the number of days that habit was ticked in that span, or, when it's linked to a
timetable category or activity, the hours it got (goal_hours).
`period` is from when goals were a month's or a year's: kept (the column requires it)
as "monthly" for a goal due by the end of its first month, else "yearly".
"""

import sqlite3
import uuid
from datetime import timedelta

import pandas as pd

from .categories import outlook_category
from .database import KEEP, _read, db
from .dates import _as_date, end_of_period, local_today, stamp, start_of_period, week_start_of
from .days import confirmed_days
from .grid import slot_count, slot_of
from .history import _clean
from .outlook import outlook_between
from .timetable import blocks_between


GOAL_PERIODS = ("monthly", "yearly")


GOAL_COLS = "id, title, period, period_start, target, unit, progress, habit_id, ord, created_at, category_id, label, due"


def _period_for(start, due):
    """The legacy `period` tag for a goal running start..due."""
    return "monthly" if _as_date(due) <= end_of_period("monthly", start_of_period("monthly", start)) else "yearly"


def goal_title_due(due, today=None):
    """A deadline for people, in numbers: "by 31/12", "by 04/01/28" (the year when it isn't this one;
    order as set in Settings → Region)."""
    from venato import regional
    return f"by {regional.short_date(due, today)}"


def _num(x):
    """12.0 -> 12, so whole numbers read naturally."""
    return int(x) if float(x).is_integer() else float(x)


def _goal_matches(goal, category_id, label, event=False):
    """Does a block (or, with event=True, a calendar event's title) count towards an hours goal?
    Same category, and if the goal names an activity label: that label (any case; for an event,
    the label anywhere in its title)."""
    if not goal.get("category_id") or category_id != goal["category_id"]:
        return False
    want = (goal.get("label") or "").strip().lower()
    have = (label or "").strip().lower()
    return not want or (want in have if event else have == want)


def goal_hours(goal, first, last, track, data=None, window=None):
    """
    Hours of an hours goal's category (and label, if it has one) in one track between two days
    (inclusive). The Plan also counts visible timed calendar events in that category, which serve
    the goal; detached calendar events (blocks with ids "ol:...") are fixed time and never count.
    Every goal calculation (value, pace, budget, forecast) goes through here.

    data:   {"blocks": [...], "events": [...], "confirmed": {dates}} already read for a range covering
            first..last (blocks_between / outlook_between rows, confirmed_days), to save queries in loops.
    The Actual counts confirmed days only: an unconfirmed day's Plan is only assumed, so it isn't done.
    window: window(day) -> (lo, hi): count only slots lo..hi-1 of that day (default: the whole day).
    """
    if not goal.get("category_id"):
        return 0.0
    first, last = _as_date(first).isoformat(), _as_date(last).isoformat()
    if first > last:
        return 0.0
    if data is None:
        data = {"blocks": blocks_between(first, last, track),
                "events": outlook_between(first, last) if track == "plan" else []}

    if track == "actual":       # Actual counts only on days the user confirmed (see "One timeline")
        confirmed = data.get("confirmed")
        confirmed = set(confirmed_days(first, last)) if confirmed is None else confirmed
    else:
        confirmed = None

    def slots(day, s, e):
        lo, hi = window(day) if window else (0, slot_count())
        return max(0, min(e, hi, slot_count()) - max(s, lo, 0))

    total = 0
    for b in data["blocks"]:
        if (b["track"] == track and first <= b["date"] <= last and not str(b["id"]).startswith("ol:")
                and (confirmed is None or b["date"] in confirmed)
                and _goal_matches(goal, b["category_id"], b["label"])):
            total += slots(b["date"], slot_of(b["start"]), slot_of(b["end"]))
    events = [ev for ev in data.get("events") or []
              if track in ("plan", "live") and not ev["all_day"] and ev["start"] and first <= ev["date"] <= last]
    if events:
        cat = data.get("outlook_category") or outlook_category("")     # (a Ctx already looked it up once)
        for ev in events:
            if _goal_matches(goal, cat, ev["title"], event=True):
                total += slots(ev["date"], slot_of(ev["start"]), slot_of(ev["end"]))
    return total / 2


def _with_value(conn, row):
    """
    A goal row plus `value` (its current progress), `kind` ("hours", "habit" or "count"),
    `habit` (the linked habit's name, or None) and `category` (the counted category's name, or None).
    """
    g = dict(row)
    g["target"], g["progress"] = _num(g["target"]), _num(g["progress"])
    g["habit"] = g["category"] = None
    g["value"] = g["progress"]
    g["kind"] = "count"
    end = g["due"]
    if g["habit_id"] is not None:
        name = conn.execute("SELECT name FROM habits WHERE id = ?", (g["habit_id"],)).fetchone()
        g["habit"] = name[0] if name else None
        g["kind"] = "habit"
        g["value"] = conn.execute(
            "SELECT COUNT(*) FROM habit_log WHERE habit_id = ? AND date BETWEEN ? AND ?",
            (g["habit_id"], g["period_start"], end),
        ).fetchone()[0]
    elif g.get("category_id"):
        name = conn.execute("SELECT name FROM tt_categories WHERE id = ?", (g["category_id"],)).fetchone()
        if name:                                   # (a category that's gone: back to the hand-kept number)
            g["category"] = name[0]
            g["kind"] = "hours"
            g["value"] = _num(goal_hours(g, g["period_start"], end, "actual"))
    return g


def counted_between(first, last, habit_id=None, category_id=None, label=None):
    """What a habit or hours goal would count between two days (inclusive): the habit's ticks, or
    confirmed Actual hours of the category (and label). None for a goal kept by hand."""
    first, last = _as_date(first).isoformat(), _as_date(last).isoformat()
    if habit_id is not None:
        with db() as conn:
            return conn.execute("SELECT COUNT(*) FROM habit_log WHERE habit_id = ? AND date BETWEEN ? AND ?",
                                (habit_id, first, last)).fetchone()[0]
    if category_id:
        return _num(goal_hours({"category_id": category_id, "label": label}, first, last, "actual"))
    return None


def goals_in(period, start):
    """The goals tagged `period` (see above) set in the month or year containing `start`, in list order,
    each with its current `value`."""
    first = start_of_period(period, start)
    return _goals_where("period = ? AND period_start BETWEEN ? AND ?",
                        (period, first.isoformat(), end_of_period(period, first).isoformat()), order="ord, created_at")


def _goals_where(where, params, order="ord, due, created_at"):
    with db() as conn:
        conn.row_factory = sqlite3.Row
        rows = conn.execute(f"SELECT {GOAL_COLS} FROM goals WHERE {where} ORDER BY {order}", params).fetchall()
        return [_with_value(conn, r) for r in rows]


def goals_overlapping(first, last):
    """Every goal whose span (set .. deadline) overlaps first..last (dates), in list order."""
    return _goals_where("period_start <= ? AND due >= ?", (_as_date(last).isoformat(), _as_date(first).isoformat()))


def goals_active(day=None):
    """Goals running on `day` (default today): set on or before it, due on or after it. In list order."""
    return goals_overlapping(day or local_today(), day or local_today())


def goals_open(day=None):
    """Goals not past their deadline on `day` (default today), including ones that start later. In list order."""
    return _goals_where("due >= ?", (_as_date(day or local_today()).isoformat(),))


def habit_has_goal(habit_id, day=None):
    """Does a goal not past its deadline count this habit's ticks? (Ticking it then moves that goal.)"""
    with db() as conn:
        return conn.execute("SELECT 1 FROM goals WHERE habit_id = ? AND due >= ? LIMIT 1",
                            (habit_id, _as_date(day or local_today()).isoformat())).fetchone() is not None


def goals_past(day=None):
    """Goals whose deadline was before `day` (default today), the latest deadline first."""
    return _goals_where("due < ?", (_as_date(day or local_today()).isoformat(),), order="due DESC, ord, created_at")


def get_goal(goal_id):
    with db() as conn:
        conn.row_factory = sqlite3.Row
        row = conn.execute(f"SELECT {GOAL_COLS} FROM goals WHERE id = ?", (goal_id,)).fetchone()
        return _with_value(conn, row) if row else None


def _check_target(target):
    target = float(target)
    if target <= 0:
        raise ValueError("A goal's target must be more than 0.")
    return target


def _check_tracking(conn, habit_id, category_id):
    """A goal counts a habit's ticks or timetable hours, never both; the category must exist."""
    if habit_id is not None and category_id:
        raise ValueError("A goal counts either a habit's ticks or timetable hours, not both.")
    if category_id and not conn.execute("SELECT 1 FROM tt_categories WHERE id = ?", (category_id,)).fetchone():
        raise ValueError(f"There's no category {category_id}.")


def add_goal(title, period, day, target, unit=None, habit_id=None, goal_id=None, category_id=None, label=None,
             due=None):
    """Add a goal; returns it. With `due`, it runs from `day` (default today) to that deadline; without,
    `period` makes it the month's or year's containing `day` (due on its last day). category_id (and
    optionally an activity label) makes it count the Actual hours of that category instead of a hand-kept number."""
    title = str(title).strip()
    if not title:
        raise ValueError("A goal needs a title.")
    if due is not None:
        start = _as_date(day or local_today())
        due = _as_date(due)
        if due < start:
            raise ValueError("A goal's deadline can't be before the day it's set.")
        period, start, due = _period_for(start, due), start.isoformat(), due.isoformat()
    else:
        if period not in GOAL_PERIODS:
            raise ValueError(f"Goals are monthly or yearly, not {period}.")
        start = start_of_period(period, day).isoformat()
        due = end_of_period(period, start).isoformat()
    goal_id = goal_id or uuid.uuid4().hex
    label = (label or "").strip() or None if category_id else None
    with db() as conn:
        _check_tracking(conn, habit_id, category_id)
        conn.execute(
            f"INSERT OR IGNORE INTO goals ({GOAL_COLS}) VALUES (?, ?, ?, ?, ?, ?, 0, ?, "
            "(SELECT COALESCE(MAX(ord) + 1, 0) FROM goals), ?, ?, ?, ?)",
            (goal_id, title, period, start, _check_target(target), (unit or "").strip() or None, habit_id,
             stamp(), category_id or None, label, due),
        )
    return get_goal(goal_id)


def update_goal(goal_id, title=KEEP, target=KEEP, unit=KEEP, habit_id=KEEP, category_id=KEEP, label=KEEP,
                due=KEEP, start=KEEP):
    """Change a goal's title, target, unit, deadline, start (the day it counts from: earlier to count
    progress you'd already made), linked habit or counted category (None unlinks them).
    Linking a habit unlinks the category and the other way round."""
    fields = {}
    if due is not KEEP or start is not KEEP:
        with db() as conn:
            row = conn.execute("SELECT period_start, due FROM goals WHERE id = ?", (goal_id,)).fetchone()
        if row:
            s = _as_date(row[0] if start is KEEP else start)
            d = _as_date(row[1] if due is KEEP else due)
            if d < s:
                raise ValueError("A goal's deadline can't be before the day it counts from.")
            fields["period_start"], fields["due"], fields["period"] = s.isoformat(), d.isoformat(), _period_for(s, d)
    if title is not KEEP:
        fields["title"] = str(title).strip()
        if not fields["title"]:
            raise ValueError("A goal needs a title.")
    if target is not KEEP:
        fields["target"] = _check_target(target)
    if unit is not KEEP:
        fields["unit"] = (unit or "").strip() or None
    if habit_id is not KEEP:
        fields["habit_id"] = habit_id
        if habit_id is not None and category_id is KEEP:
            fields["category_id"] = fields["label"] = None
    if category_id is not KEEP:
        fields["category_id"] = category_id or None
        if category_id:
            if habit_id is KEEP:
                fields["habit_id"] = None
        else:
            fields["label"] = None
    if label is not KEEP and fields.get("category_id", True):
        fields["label"] = (label or "").strip() or None
    if fields:
        with db() as conn:
            if "habit_id" in fields or "category_id" in fields:
                old = conn.execute("SELECT habit_id, category_id FROM goals WHERE id = ?", (goal_id,)).fetchone()
                if old:
                    _check_tracking(conn, fields.get("habit_id", old[0]), fields.get("category_id", old[1]))
            conn.execute(f"UPDATE goals SET {', '.join(f'{k} = ?' for k in fields)} WHERE id = ?",
                         (*fields.values(), goal_id))


def set_goal_progress(goal_id, value):
    """Set a goal's hand-updated progress (never below 0)."""
    with db() as conn:
        conn.execute("UPDATE goals SET progress = MAX(0, ?) WHERE id = ?", (float(value), goal_id))


def add_goal_progress(goal_id, amount):
    """Add to (or, with a negative amount, take from) a goal's hand-updated progress."""
    with db() as conn:
        conn.execute("UPDATE goals SET progress = MAX(0, progress + ?) WHERE id = ?", (float(amount), goal_id))


def delete_goal(goal_id):
    with db() as conn:
        conn.execute("DELETE FROM goals WHERE id = ?", (goal_id,))


def reorder_goals(ids):
    with db() as conn:
        conn.executemany("UPDATE goals SET ord = ? WHERE id = ?", [(i, gid) for i, gid in enumerate(ids)])


def goal_week_hours(week_start):
    """{goal id: hours} the user chose for each goal in the week containing `week_start` (empty = automatic)."""
    with db() as conn:
        return {gid: h for gid, h in conn.execute("SELECT goal_id, hours FROM goal_week WHERE week_start = ?",
                                                   (week_start_of(week_start).isoformat(),))}


def set_goal_week_hours(week_start, split):
    """Save the week's split of hours between goals ({goal id: hours}); an empty split goes back to automatic."""
    week = week_start_of(week_start).isoformat()
    with db() as conn:
        conn.execute("DELETE FROM goal_week WHERE week_start = ?", (week,))
        conn.executemany("INSERT INTO goal_week VALUES (?, ?, ?)",
                         [(gid, week, max(0.0, float(h))) for gid, h in split.items()])


def away_uids():
    """All-day calendar events the user marked "I'm away"."""
    with db() as conn:
        return {r[0] for r in conn.execute("SELECT uid FROM tt_outlook_away")}


def set_away(uid, away):
    """Mark an all-day calendar event as "I'm away" (that day has no free time for goals), or not."""
    with db() as conn:
        if away:
            conn.execute("INSERT OR IGNORE INTO tt_outlook_away VALUES (?)", (uid,))
        else:
            conn.execute("DELETE FROM tt_outlook_away WHERE uid = ?", (uid,))


def away_days():
    """Days (ISO dates) the user marked "I'm away" by hand."""
    with db() as conn:
        return {r[0] for r in conn.execute("SELECT date FROM away_days")}


def set_away_day(day, away):
    """Mark a day as "I'm away" (no free time for goals that day), or not."""
    with db() as conn:
        if away:
            conn.execute("INSERT OR IGNORE INTO away_days VALUES (?)", (_as_date(day).isoformat(),))
        else:
            conn.execute("DELETE FROM away_days WHERE date = ?", (_as_date(day).isoformat(),))


def calendar_horizon():
    """The last day calendar sync reaches (8 weeks ahead), or None with no calendar events at all."""
    with db() as conn:
        last = conn.execute("SELECT MAX(date) FROM tt_outlook").fetchone()[0]
    return local_today() + timedelta(weeks=8) if last else None


def load_goals():
    """Every goal, for export (the linked habit by name, so the CSV makes sense on its own)."""
    return _read(f"""SELECT g.id, g.title, g.period, g.period_start, g.due, g.target, g.unit, g.progress,
                            h.name AS habit, c.name AS category, g.label, g.ord, g.created_at
                     FROM goals g LEFT JOIN habits h ON h.id = g.habit_id
                     LEFT JOIN tt_categories c ON c.id = g.category_id
                     ORDER BY g.due, g.ord""")


def save_goals(df, replace=False):
    """
    Import goals (the export's columns; title, target and either `due` (a deadline) or `period` are required).
    A habit name that doesn't exist is ignored (the goal is then updated by hand).
    Rows with an existing id update that goal; replace=True wipes all goals first. Returns the count.
    """
    count = 0
    with db() as conn:
        if replace:
            conn.execute("DELETE FROM goals")
        habits = {name.lower(): hid for hid, name in conn.execute("SELECT id, name FROM habits")}
        cats = {name.lower(): cid for cid, name in conn.execute("SELECT id, name FROM tt_categories")}
        for row in df.to_dict("records"):
            title = _clean(row.get("title"), str)
            period = (_clean(row.get("period"), str) or "").strip().lower()
            target = _clean(row.get("target"), float)
            due = _clean(row.get("due"), str)
            due = pd.to_datetime(due).date() if due else None
            if not title or (due is None and period not in GOAL_PERIODS) or not target or target <= 0:
                continue
            day = _clean(row.get("period_start"), str)
            day = pd.to_datetime(day).date() if day else local_today()
            if due is None:
                start = start_of_period(period, day)
                due = end_of_period(period, start)
            else:
                start = min(day, due)
                period = _period_for(start, due)
            start, due = start.isoformat(), due.isoformat()
            habit = _clean(row.get("habit"), str)
            habit_id = habits.get(habit.strip().lower()) if habit else None
            category = _clean(row.get("category"), str)
            category_id = cats.get(category.strip().lower()) if category and habit_id is None else None
            ord_ = _clean(row.get("ord"), int)
            conn.execute(
                f"INSERT OR REPLACE INTO goals ({GOAL_COLS}) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (_clean(row.get("id"), str) or uuid.uuid4().hex, title.strip(), period, start, target,
                 _clean(row.get("unit"), str), max(0.0, _clean(row.get("progress"), float) or 0.0),
                 habit_id, count if ord_ is None else ord_,
                 _clean(row.get("created_at"), str) or stamp(), category_id,
                 (_clean(row.get("label"), str) or None) if category_id else None, due),
            )
            count += 1
    return count
