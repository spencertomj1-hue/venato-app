"""
Data layer for Venato: every SQL query lives here. No Streamlit code, so the
pages, the Claude tools and the tests all share the same logic.

All user data lives in the data folder (system.default_data_dir(): ~/Library/Application Support/Venato
on a Mac, %APPDATA%/Venato on Windows, ~/.local/share/Venato on Linux), or $VENATO_DATA_DIR, used for tests and the demo). The database is life.db
there (or $VENATO_DB). Backups, settings.json and the Outlook cache live there
too. Nothing user-specific is kept in the project folder.
"""

import sqlite3
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
from .goals import (GOAL_COLS, GOAL_PERIODS, _goal_matches, _num, add_goal, add_goal_progress, away_days,
    away_uids, calendar_horizon, counted_between, delete_goal, get_goal, goal_hours, goal_title_due,
    goal_week_hours, goals_active, goals_in, goals_open, goals_overlapping, goals_past, habit_has_goal,
    load_goals, reorder_goals, save_goals, set_away, set_away_day, set_goal_progress, set_goal_week_hours,
    update_goal)
from .review import (get_review, reviews, save_review)


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
