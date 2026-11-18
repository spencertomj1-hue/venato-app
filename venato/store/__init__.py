"""
Data layer for Venato: every SQL query lives here. No Streamlit code, so the
pages, the Claude tools and the tests all share the same logic.

All user data lives in the data folder (system.default_data_dir(): ~/Library/Application Support/Venato
on a Mac, %APPDATA%/Venato on Windows, ~/.local/share/Venato on Linux), or $VENATO_DATA_DIR, used for tests and the demo). The database is life.db
there (or $VENATO_DB). Backups, settings.json and the Outlook cache live there
too. Nothing user-specific is kept in the project folder.
"""

import sqlite3
import uuid
from datetime import date, datetime, timedelta

import pandas as pd

from venato import facade

from .database import (KEEP, _read, bump_version, data_dir, data_version, db, db_path, use_db_path)
from .settings import (DAY_END, DAY_START, MIN_DAY_HOURS, ai_enabled, day_hours, day_length, load_settings,
    save_settings, settings_path)
from .dates import (WEEK_START, _as_date, computer_zone_name, end_of_period, fmt_day, local_now, local_today,
    period_title, set_week_start, shift_period, stamp, start_of_period, tz, week_start_name, week_start_of,
    zone_name)
from .grid import (BLOCK_COLS, TRACKS, apply_block_ops, blocks_for, first_min, get_block_in, plan_paint,
    slot_count, slot_of, slot_time)
from .categories import (DEFAULT_CATEGORIES, DEFAULT_LABEL_MAP, DEFAULT_OUTLOOK_CATEGORY, groups,
    load_categories, load_label_map, outlook_category, remove_label_default, resolve_category, save_category,
    set_label_default)
from .outlook import (OUTLOOK_COLS, _as_block, _detach, _visible_outlook, detach_outlook, get_outlook,
    hide_outlook, outlook_between, outlook_details, outlook_overlaps, outlook_signature, replace_outlook)
from .timetable import (blocks_between, delete_block, get_block, move_block, paint, preview_paint,
    set_block_label, upsert_blocks)
from .days import (confirm_day, confirmed_days, correct, day_ended, day_started, day_status, free_runs,
    live_track, lock_day, lock_started, mark_confirmed, materialise_ops, retime, slots_gone, unconfirm_day,
    unconfirmed_days, unconfirmed_days_with_blocks)
from .journal import (append_journal, entries_between, get_entry, get_journal, journal_entries, save_entry,
    save_journal)
from .habits import (HABIT_PREFIX, add_habit, delete_habit, find_habit, get_habit_dates, get_habits,
    habit_progress, habit_targets, habit_ticks_between, rename_habit, set_habit_done, set_habit_target,
    streaks, week_ticks, weekly_streaks)
from .history import (_clean, _is_ticked, load_all_data, save_all_data)
from .deadline import (DEADLINE_COLS, add_deadline, countdown, deadlines, delete_deadline, get_deadline,
    set_deadline_done, update_deadline)
from .todos import (TODO_COLS, TODO_PERIODS, add_todo, carry_over, delete_todo, get_todo, load_todos,
    move_target, move_todo, reorder_todos, roll_todos, save_todos, set_todo_done, todos_for, todos_progress,
    update_todo)


# ---------------------------------------------------------------------------
# Connection + schema
# ---------------------------------------------------------------------------


def init_db():
    """Create tables if they don't exist yet, and seed the timetable key."""
    db_path().parent.mkdir(parents=True, exist_ok=True)
    with db() as conn:
        _goals_became_todos(conn)
        conn.executescript(
            """
            -- One row per day
            CREATE TABLE IF NOT EXISTS entries (
                date   TEXT PRIMARY KEY,   -- ISO format, e.g. 2026-10-29
                mood   INTEGER,            -- 1-10
                sleep  REAL,               -- hours
                energy INTEGER,            -- 1-10
                notes  TEXT,
                water  REAL                -- litres drunk
            );

            -- The list of habits you track
            CREATE TABLE IF NOT EXISTS habits (
                id   INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT UNIQUE NOT NULL
            );

            -- A row here means "habit was done on this date"
            CREATE TABLE IF NOT EXISTS habit_log (
                habit_id INTEGER NOT NULL REFERENCES habits(id) ON DELETE CASCADE,
                date     TEXT NOT NULL,
                PRIMARY KEY (habit_id, date)
            );

            -- Timetable
            CREATE TABLE IF NOT EXISTS tt_categories (
                id          TEXT PRIMARY KEY,
                name        TEXT NOT NULL,
                colour      TEXT NOT NULL,     -- "#RRGGBB"
                text_colour TEXT,              -- NULL = pick black/white automatically
                grp         TEXT NOT NULL,     -- group heading in the key, e.g. "Life"
                ord         INTEGER NOT NULL   -- position in the key
            );

            CREATE TABLE IF NOT EXISTS tt_entries (
                id          TEXT PRIMARY KEY,
                date        TEXT NOT NULL,     -- day the row belongs to (after-midnight slots too)
                track       TEXT NOT NULL CHECK (track IN ('plan', 'actual')),
                start       TEXT NOT NULL,     -- "HH:mm", 30-min aligned
                "end"       TEXT NOT NULL,     -- "HH:mm", exclusive; may be "01:00"
                label       TEXT NOT NULL,
                category_id TEXT,
                details     TEXT               -- optional description (e.g. kept from an Outlook event)
            );
            CREATE INDEX IF NOT EXISTS tt_entries_day ON tt_entries (date, track);

            CREATE TABLE IF NOT EXISTS tt_label_map (
                label       TEXT PRIMARY KEY,
                category_id TEXT NOT NULL
            );

            -- Events imported (read only) from the Outlook calendar. Fully replaced on
            -- each sync and kept apart from tt_entries, so the user's own blocks are never touched.
            CREATE TABLE IF NOT EXISTS tt_outlook (
                uid      TEXT PRIMARY KEY,   -- event UID + occurrence + grid day
                date     TEXT NOT NULL,      -- timetable day (after-midnight slots belong to the day before)
                start    TEXT,               -- "HH:mm" snapped to the grid; NULL for all-day events
                "end"    TEXT,
                title    TEXT NOT NULL,
                location TEXT,
                all_day  INTEGER NOT NULL DEFAULT 0,
                exact    TEXT,               -- the real times, e.g. "09:10–09:50"
                description TEXT             -- short text from the event's notes
            );
            CREATE INDEX IF NOT EXISTS tt_outlook_day ON tt_outlook (date);

            -- Outlook occurrences the user removed or turned into their own block.
            -- Kept across syncs (uids are stable per occurrence), so they stay gone.
            CREATE TABLE IF NOT EXISTS tt_outlook_hidden (uid TEXT PRIMARY KEY);

            -- To-dos for a day, week or month
            CREATE TABLE IF NOT EXISTS todos (
                id           TEXT PRIMARY KEY,
                title        TEXT NOT NULL,
                notes        TEXT,
                period       TEXT NOT NULL CHECK (period IN ('daily', 'weekly', 'monthly', 'yearly')),
                period_start TEXT NOT NULL,              -- the day / Monday / 1st of the month
                done         INTEGER NOT NULL DEFAULT 0,
                done_at      TEXT,                       -- ISO timestamp, NULL while unticked
                "repeat"     INTEGER NOT NULL DEFAULT 0, -- 1 = a fresh copy every new period
                ord          INTEGER NOT NULL DEFAULT 0, -- position in its list
                created_at   TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS todos_period ON todos (period, period_start);

            -- The last period each kind of repeating to-do was copied into (see roll_todos).
            CREATE TABLE IF NOT EXISTS todo_rollover (period TEXT PRIMARY KEY, period_start TEXT NOT NULL);

            -- Goals: measurable targets for a month or a year, e.g. "Gym 12 sessions"
            CREATE TABLE IF NOT EXISTS goals (
                id           TEXT PRIMARY KEY,
                title        TEXT NOT NULL,
                period       TEXT NOT NULL CHECK (period IN ('monthly', 'yearly')),
                period_start TEXT NOT NULL,              -- the 1st of the month / 1 Jan
                target       REAL NOT NULL,
                unit         TEXT,                       -- e.g. "sessions", "km"; NULL = just a number
                progress     REAL NOT NULL DEFAULT 0,    -- updated by hand (unused while linked to a habit)
                habit_id     INTEGER REFERENCES habits(id) ON DELETE SET NULL,   -- counts that habit's ticks
                ord          INTEGER NOT NULL DEFAULT 0,
                created_at   TEXT NOT NULL
            );

            -- Weekly reviews: one row per reviewed week (its first day), with the user's reflections
            CREATE TABLE IF NOT EXISTS weekly_reviews (
                week_start TEXT PRIMARY KEY,               -- YYYY-MM-DD
                seen_at    TEXT,
                went_well  TEXT,
                to_change  TEXT
            );

            -- Deadlines: something due on a date (an assignment, an application, a bill)
            CREATE TABLE IF NOT EXISTS deadlines (
                id         TEXT PRIMARY KEY,
                title      TEXT NOT NULL,
                due        TEXT NOT NULL,                -- YYYY-MM-DD
                notes      TEXT,
                done       INTEGER NOT NULL DEFAULT 0,
                done_at    TEXT,
                created_at TEXT NOT NULL
            );
            """
        )
        # Each block's own tables (venato/blocks/*), then their later changes.
        from venato import blocks
        conn.executescript(blocks.schema_sql())
        for migrate in blocks.migrations():
            migrate(conn)
        # Columns added after the first release.
        _add_column(conn, "tt_entries", "details", "TEXT")
        _add_column(conn, "entries", "water", "REAL")
        _add_column(conn, "habits", "per_week", "INTEGER")          # NULL = every day; else N times a week
        _journal_became_notes(conn)
        _add_column(conn, "tt_outlook", "description", "TEXT")
        _add_column(conn, "entries", "productivity", "INTEGER")    # 1-10, self-rated
        # Goals that count timetable hours: Actual time in a category (and optionally one activity label).
        _add_column(conn, "goals", "category_id", "TEXT REFERENCES tt_categories(id) ON DELETE SET NULL")
        _add_column(conn, "goals", "label", "TEXT")
        _goals_get_deadlines(conn)
        conn.executescript(
            """
            -- The hours the user chose to give each goal in a week, when goals compete for time
            CREATE TABLE IF NOT EXISTS goal_week (
                goal_id    TEXT NOT NULL REFERENCES goals(id) ON DELETE CASCADE,
                week_start TEXT NOT NULL,                -- YYYY-MM-DD, the week's first day
                hours      REAL NOT NULL,
                PRIMARY KEY (goal_id, week_start)
            );
            -- All-day calendar events the user marked "I'm away" (that day has no free time).
            -- Kept across syncs, like tt_outlook_hidden.
            CREATE TABLE IF NOT EXISTS tt_outlook_away (uid TEXT PRIMARY KEY);
            -- Days the user marked "I'm away" by hand (no calendar event needed): no free time for goals.
            CREATE TABLE IF NOT EXISTS away_days (date TEXT PRIMARY KEY);
            """
        )
        _scores_out_of_ten(conn)
        _day_status_table(conn)
        _forget_future_status(conn)
        if conn.execute("SELECT COUNT(*) FROM tt_categories").fetchone()[0] == 0:
            conn.executemany(
                "INSERT INTO tt_categories VALUES (?, ?, ?, ?, ?, ?)",
                [(cid, name, col, txt, grp, i) for i, (cid, name, col, txt, grp) in enumerate(DEFAULT_CATEGORIES)],
            )
        if conn.execute("SELECT COUNT(*) FROM tt_label_map").fetchone()[0] == 0:
            conn.executemany("INSERT INTO tt_label_map VALUES (?, ?)", DEFAULT_LABEL_MAP.items())


def _goals_became_todos(conn):
    """
    Early versions called the to-do lists "goals". If this database has that old
    table, back it up, rename it (and its rollover table) to todos, and drop the
    yearly to-dos, which no longer exist. The new goals table is then created fresh.
    """
    columns = {row[1] for row in conn.execute("PRAGMA table_info(goals)")}
    if "done" not in columns:
        return
    backups = data_dir() / "backups"
    backups.mkdir(parents=True, exist_ok=True)
    copy = sqlite3.connect(backups / f"life-{datetime.now():%Y-%m-%d-%H%M%S}-before-todos.db")
    conn.backup(copy)
    copy.close()
    conn.execute("ALTER TABLE goals RENAME TO todos")
    conn.execute("DROP INDEX IF EXISTS goals_period")
    if conn.execute("SELECT 1 FROM sqlite_master WHERE name = 'goal_rollover'").fetchone():
        conn.execute("ALTER TABLE goal_rollover RENAME TO todo_rollover")
        conn.execute("DELETE FROM todo_rollover WHERE period = 'yearly'")
    conn.execute("DELETE FROM todos WHERE period = 'yearly'")


def _day_status_table(conn):
    """
    tt_day_status: which timetable days are locked / confirmed (see "Plan locked" below).
    Made the first time this version runs. Existing days with any Actual block are marked
    confirmed (their Actual is already the truth); nothing else changes.
    """
    if conn.execute("SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'tt_day_status'").fetchone():
        return
    conn.execute(
        """CREATE TABLE tt_day_status (
               date         TEXT PRIMARY KEY,   -- a timetable day
               confirmed_at TEXT,               -- when the user confirmed it (NULL = not yet)
               upto         TEXT                -- Actual is the truth for this day's slots before this time
           )""")
    full = slot_time(slot_count())
    conn.execute("INSERT INTO tt_day_status SELECT DISTINCT date, ?, ? FROM tt_entries "
                 "WHERE track = 'actual' AND date < ?", (stamp(), full, local_today().isoformat()))


def _forget_future_status(conn):
    """
    A day that hasn't started can't be confirmed or part-done. The first version of tt_day_status
    marked every day with an Actual block confirmed, future ones too (repeating blocks, a hand-filled
    week ahead): drop those, so they start unconfirmed when they come.
    """
    conn.execute("DELETE FROM tt_day_status WHERE date > ?", (local_today().isoformat(),))


def _goals_get_deadlines(conn):
    """Goals have a deadline (`due`) instead of being a month's or a year's: an older goal's is the
    last day of its month or year."""
    _add_column(conn, "goals", "due", "TEXT")
    rows = conn.execute("SELECT id, period, period_start FROM goals WHERE due IS NULL").fetchall()
    conn.executemany("UPDATE goals SET due = ? WHERE id = ?",
                     [(end_of_period(p, start).isoformat(), gid) for gid, p, start in rows])


def _add_column(conn, table, column, kind):
    """Add a column to an existing table if an older database doesn't have it yet."""
    if column not in {row[1] for row in conn.execute(f"PRAGMA table_info({table})")}:
        conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {kind}")


def _scores_out_of_ten(conn):
    """Mood and energy used to be out of 5: double them, once, so old days match the new 1-10 scale."""
    conn.execute("CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT)")
    if conn.execute("SELECT 1 FROM meta WHERE key = 'scores_out_of_10'").fetchone():
        return
    conn.execute("UPDATE entries SET mood = mood * 2 WHERE mood IS NOT NULL")
    conn.execute("UPDATE entries SET energy = energy * 2 WHERE energy IS NOT NULL")
    conn.execute("INSERT INTO meta (key, value) VALUES ('scores_out_of_10', '1')")


def _journal_became_notes(conn):
    """Databases from when the journal had its own table: fold each entry into that day's notes."""
    if not conn.execute("SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'journal'").fetchone():
        return
    for day, text in conn.execute("SELECT date, text FROM journal ORDER BY date").fetchall():
        row = conn.execute("SELECT notes FROM entries WHERE date = ?", (day,)).fetchone()
        old = (row[0] or "").strip() if row else ""
        new = text if not old or text.strip() in old else f"{old}\n\n{text}"
        conn.execute("INSERT INTO entries (date, notes) VALUES (?, ?) "
                     "ON CONFLICT(date) DO UPDATE SET notes = excluded.notes", (day, new))
    conn.execute("DROP TABLE journal")


# ---------------------------------------------------------------------------
# Goals: measurable targets with a deadline ("Gym 12 sessions by 31 Dec").
#
# A goal runs from period_start (the day it was set) to `due` (its deadline), inclusive.
# Progress is either a number the user updates (`progress`), or, when the goal
# is linked to a habit, the number of days that habit was ticked in that span.
# `period` is from when goals were a month's or a year's: kept (the column requires it)
# as "monthly" for a goal due by the end of its first month, else "yearly".
# ---------------------------------------------------------------------------

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


# --- Weekly reviews ---

def get_review(week_start):
    """The saved review row for a week ({} if none)."""
    with db() as conn:
        row = conn.execute("SELECT week_start, seen_at, went_well, to_change FROM weekly_reviews WHERE week_start = ?",
                           (_as_date(week_start).isoformat(),)).fetchone()
    return dict(zip(("week_start", "seen_at", "went_well", "to_change"), row)) if row else {}


def save_review(week_start, went_well=KEEP, to_change=KEEP, seen=False):
    """Create or update a week's review: mark it seen and/or save the reflections."""
    week = _as_date(week_start).isoformat()
    with db() as conn:
        conn.execute("INSERT OR IGNORE INTO weekly_reviews (week_start) VALUES (?)", (week,))
        if seen:
            conn.execute("UPDATE weekly_reviews SET seen_at = COALESCE(seen_at, ?) WHERE week_start = ?", (stamp(), week))
        for col, value in (("went_well", went_well), ("to_change", to_change)):
            if value is not KEEP:
                conn.execute(f"UPDATE weekly_reviews SET {col} = ? WHERE week_start = ?",
                             ((value or "").strip() or None, week))


def reviews():
    """Weeks that have a review, newest first: [{week_start, seen_at, went_well, to_change}]."""
    with db() as conn:
        rows = conn.execute("SELECT week_start, seen_at, went_well, to_change FROM weekly_reviews "
                            "ORDER BY week_start DESC").fetchall()
    return [dict(zip(("week_start", "seen_at", "went_well", "to_change"), r)) for r in rows]


# ---------------------------------------------------------------------------
# Stats
# ---------------------------------------------------------------------------

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


# ---------------------------------------------------------------------------
# Search: one box for everything (Home)
# ---------------------------------------------------------------------------

# kind -> (SQL giving (id, title, detail, date, extra), the `haystack` that must contain every word, and
# optionally the order: "name" (by title) or "date" (newest first, the default). Blocks add their own kinds.
_SEARCH = {
    "To-do": ("SELECT id, title, notes, period_start, period FROM todos", "title || ' ' || COALESCE(notes, '')"),
    "Goal": ("SELECT id, title, unit, period_start, period FROM goals", "title"),
    "Deadline": ("SELECT id, title, notes, due, done FROM deadlines", "title || ' ' || COALESCE(notes, '')"),
    "Timetable": ("SELECT id, label, details, date, track || ' ' || start || '-' || \"end\" FROM tt_entries",
                  "label || ' ' || COALESCE(details, '')"),
    "Outlook": ("SELECT uid, title, location, date, start FROM tt_outlook",
                "title || ' ' || COALESCE(location, '') || ' ' || COALESCE(description, '')"),
    "Review": ("SELECT week_start, 'Weekly review', COALESCE(went_well, '') || ' ' || COALESCE(to_change, ''), "
               "week_start, NULL FROM weekly_reviews", "COALESCE(went_well, '') || ' ' || COALESCE(to_change, '')"),
}

_SEARCH_OWNER = {"To-do": "goals", "Goal": "goals", "Deadline": "goals",
                 "Timetable": "timetable", "Outlook": "timetable", "Review": "stats"}


def search(query, per_kind=8):
    """Everything matching all the words in `query` (any case), as
    [{kind, id, title, detail, date, extra}], newest first within each kind."""
    words = str(query or "").split()
    if not words:
        return []
    from venato import blocks
    out = []
    with db() as conn:
        on = set(blocks.chosen_keys())
        built_in = {k: v for k, v in _SEARCH.items() if _SEARCH_OWNER[k] in on}   # only the switched-on blocks' kinds
        for kind, (select, haystack, *order) in {**built_in, **blocks.search_kinds()}.items():
            where = " AND ".join(f"{haystack} LIKE ? ESCAPE '\\'" for _ in words)
            params = ["%" + w.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%" for w in words]
            order = " ORDER BY 2" if order == ["name"] else " ORDER BY 4 DESC"
            rows = conn.execute(f"{select} WHERE {where}{order} LIMIT {int(per_kind)}", params).fetchall()
            out += [{"kind": kind, "id": r[0], "title": r[1], "detail": r[2], "date": r[3], "extra": r[4]} for r in rows]
    return out


# store.SLOTS / FIRST_MIN / DATA_DIR / DB_PATH: read fresh on every access (see venato/facade.py).
facade.install(__name__, live={
    "DATA_DIR": (data_dir, None),
    "DB_PATH": (db_path, use_db_path),
    "SLOTS": (slot_count, None),
    "FIRST_MIN": (first_min, None),
})
