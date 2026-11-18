"""
Habits: ticked off per day, optionally with a target of so many days a week, and their streaks.
"""

from datetime import date, timedelta

from .database import db
from .dates import local_today, week_start_of


# Habits appear as extra columns in the History table and CSV, named "habit: <name>".
HABIT_PREFIX = "habit: "


def get_habits():
    """Return a list of (id, name) tuples, sorted by name."""
    with db() as conn:
        return conn.execute("SELECT id, name FROM habits ORDER BY name").fetchall()


def find_habit(name):
    """Case-insensitive lookup; returns (id, name) or None."""
    with db() as conn:
        return conn.execute(
            "SELECT id, name FROM habits WHERE lower(name) = lower(?)", (name.strip(),)
        ).fetchone()


def add_habit(name, per_week=None):
    with db() as conn:
        conn.execute("INSERT OR IGNORE INTO habits (name) VALUES (?)", (name,))
        if per_week:
            conn.execute("UPDATE habits SET per_week = ? WHERE name = ?", (_check_per_week(per_week), name))


def _check_per_week(n):
    n = int(n)
    if not 1 <= n <= 7:
        raise ValueError("A weekly target is 1 to 7 times a week.")
    return n


def habit_targets():
    """{habit id: times a week} for habits with a weekly target (the rest are every day)."""
    with db() as conn:
        return dict(conn.execute("SELECT id, per_week FROM habits WHERE per_week IS NOT NULL").fetchall())


def set_habit_target(habit_id, per_week):
    """N times a week, or None for every day."""
    with db() as conn:
        conn.execute("UPDATE habits SET per_week = ? WHERE id = ?",
                     (_check_per_week(per_week) if per_week else None, habit_id))


def week_ticks(done_dates, day):
    """How many times it was ticked in the week containing `day`."""
    first = week_start_of(day)
    return sum((first + timedelta(days=i)).isoformat() in done_dates for i in range(7))


def weekly_streaks(done_dates, per_week, today=None):
    """(current, best) runs of weeks that hit the target. This week counts once it's hit;
    until then the streak runs to last week, so it doesn't break before the week is over."""
    today = today or local_today()
    this_monday = week_start_of(today)                      # (the first day of the week: Monday or Sunday)
    mondays = sorted({week_start_of(d) for d in map(date.fromisoformat, done_dates)})
    hit = {m for m in mondays if week_ticks(done_dates, m) >= per_week}
    best = run = 0
    prev = None
    for m in sorted(hit):
        run = run + 1 if prev and m - prev == timedelta(weeks=1) else 1
        best, prev = max(best, run), m
    week = this_monday if this_monday in hit else this_monday - timedelta(weeks=1)
    current = 0
    while week in hit:
        current, week = current + 1, week - timedelta(weeks=1)
    return current, best


def habit_progress(habit_id, done_dates, today=None):
    """One line about a habit's progress: '3-day streak · best 9' or '2 of 3 this week · 4-week streak'."""
    today = today or local_today()
    per_week = habit_targets().get(habit_id)
    if per_week:
        current, best = weekly_streaks(done_dates, per_week, today)
        return (f"{week_ticks(done_dates, today)} of {per_week} this week · {current}-week streak · best {best}",
                current, per_week)
    current, best = streaks(done_dates, today)
    return f"{current}-day streak · best {best}", current, None


def rename_habit(habit_id, name):
    name = str(name or "").strip()
    if not name:
        raise ValueError("The habit needs a name.")
    with db() as conn:
        clash = conn.execute("SELECT 1 FROM habits WHERE name = ? COLLATE NOCASE AND id != ?", (name, habit_id)).fetchone()
        if clash:
            raise ValueError(f"There's already a habit called '{name}'.")
        conn.execute("UPDATE habits SET name = ? WHERE id = ?", (name, habit_id))


def delete_habit(habit_id):
    # Its habit_log rows are removed too, thanks to ON DELETE CASCADE.
    with db() as conn:
        conn.execute("DELETE FROM habits WHERE id = ?", (habit_id,))


def get_habit_dates(habit_id):
    """Return the set of ISO dates on which a habit was done."""
    with db() as conn:
        rows = conn.execute("SELECT date FROM habit_log WHERE habit_id = ?", (habit_id,))
        return {r[0] for r in rows}


def set_habit_done(conn, habit_id, day, done):
    """Tick or untick a habit for a date (uses an open connection)."""
    if done:
        conn.execute("INSERT OR IGNORE INTO habit_log VALUES (?, ?)", (habit_id, day))
    else:
        conn.execute("DELETE FROM habit_log WHERE habit_id = ? AND date = ?", (habit_id, day))


def habit_ticks_between(first, last):
    """{date: [habit names ticked]} between two ISO dates (inclusive)."""
    with db() as conn:
        rows = conn.execute(
            """SELECT l.date, h.name FROM habit_log l JOIN habits h ON h.id = l.habit_id
               WHERE l.date BETWEEN ? AND ? ORDER BY l.date, h.name""",
            (first, last),
        ).fetchall()
    ticks = {}
    for day, name in rows:
        ticks.setdefault(day, []).append(name)
    return ticks


def streaks(done_dates, today=None):
    """Return (current_streak, best_streak) from a set of ISO date strings."""
    # Best streak: longest run of consecutive days.
    best = run = 0
    prev = None
    for d in sorted(date.fromisoformat(x) for x in done_dates):
        run = run + 1 if prev and d - prev == timedelta(days=1) else 1
        best = max(best, run)
        prev = d

    # Current streak: count back from today. If today isn't ticked yet,
    # start from yesterday so the streak doesn't "break" before the day is over.
    current = 0
    day = today or local_today()
    if day.isoformat() not in done_dates:
        day -= timedelta(days=1)
    while day.isoformat() in done_dates:
        current += 1
        day -= timedelta(days=1)
    return current, best
