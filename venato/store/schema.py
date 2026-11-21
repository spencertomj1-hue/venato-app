"""
The database schema: init_db() creates the tables if they don't exist yet (no categories: a new
install starts blank), and brings an older database up to date (the one-off migrations below it).
Run once at startup (app.py); safe to run again.
"""

import sqlite3
from datetime import datetime

from .database import data_dir, db, db_path
from .dates import end_of_period, local_today, stamp
from .grid import slot_count, slot_time


def init_db():
    """Create tables if they don't exist yet, and bring an older database up to date. A new database has no categories."""
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
                to_change  TEXT,
                kept       TEXT                       -- last week's "to change": yes / partly / no
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
        _add_column(conn, "weekly_reviews", "kept", "TEXT")       # did they do last week's "to change"? yes/partly/no
        # Done / not done, marked on a timetable block or calendar event (kept for analysis, even if the
        # block changes or goes: a snapshot of what it was). id: the block's id, or "outlook:<uid>".
        conn.execute("""CREATE TABLE IF NOT EXISTS tt_status (
                            id TEXT PRIMARY KEY, date TEXT NOT NULL, start TEXT, "end" TEXT, label TEXT,
                            category_id TEXT, status TEXT NOT NULL CHECK (status IN ('done', 'missed')),
                            at TEXT NOT NULL)""")
        _word_rules_to_label_map(conn)
        # To-dos: a due day, how long it takes and one of the user's own to-do categories (todo_groups).
        _add_column(conn, "todos", "due", "TEXT")
        _add_column(conn, "todos", "minutes", "INTEGER")
        _add_column(conn, "todos", "group_id", "TEXT")
        conn.execute("""CREATE TABLE IF NOT EXISTS todo_groups (
                            id TEXT PRIMARY KEY, name TEXT NOT NULL UNIQUE COLLATE NOCASE,
                            colour TEXT NOT NULL, ord INTEGER NOT NULL DEFAULT 0)""")
        _goals_become_todo_groups(conn)
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
            -- To-dos the journal made from "quoted" / ^marked^ text, so re-saving never adds them twice
            CREATE TABLE IF NOT EXISTS journal_todos (
                date   TEXT NOT NULL,          -- the journal page
                period TEXT NOT NULL,          -- daily / weekly
                title  TEXT NOT NULL COLLATE NOCASE,
                PRIMARY KEY (date, period, title)
            );
            -- Day trackers: the user's own numbers for each day (their list is in settings.json)
            CREATE TABLE IF NOT EXISTS day_values (
                date    TEXT NOT NULL,
                tracker TEXT NOT NULL,         -- the tracker's id
                value   REAL NOT NULL,
                PRIMARY KEY (date, tracker)
            );
            """
        )
        _deadlines_from_feeds(conn)
        _scores_out_of_ten(conn)
        _day_status_table(conn)
        _forget_future_status(conn)


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


def _deadlines_from_feeds(conn):
    """Deadlines and timetable events linked to a module (Grades), and deadlines imported from Canvas.
    Only adds columns and tables: existing rows keep their values (the new columns start NULL)."""
    _add_column(conn, "deadlines", "module_id", "TEXT")         # gr_modules.id (cleared when the module goes)
    _add_column(conn, "deadlines", "due_time", "TEXT")          # "HH:MM", NULL = any time that day
    _add_column(conn, "deadlines", "source", "TEXT")            # NULL = typed in; "canvas" = imported
    _add_column(conn, "deadlines", "uid", "TEXT")               # the feed's stable id (Canvas UID)
    _add_column(conn, "deadlines", "course_id", "TEXT")         # the Canvas course (gr_canvas_courses)
    # The last title / date the feed gave: a sync changes the deadline only when the feed changes,
    # so a title or date the student edited stays until Canvas itself changes it.
    _add_column(conn, "deadlines", "source_title", "TEXT")
    _add_column(conn, "deadlines", "source_due", "TEXT")
    _add_column(conn, "deadlines", "source_due_time", "TEXT")
    conn.execute("CREATE UNIQUE INDEX IF NOT EXISTS deadlines_uid ON deadlines (uid) WHERE uid IS NOT NULL")
    # Imported deadlines the student deleted: a sync never brings them back.
    conn.execute("CREATE TABLE IF NOT EXISTS deadlines_hidden (uid TEXT PRIMARY KEY)")
    # A deadline's plan is an hours goal: deadline_id links it, closed hides it once the deadline is done.
    _add_column(conn, "goals", "deadline_id", "TEXT")
    _add_column(conn, "goals", "closed", "INTEGER NOT NULL DEFAULT 0")
    _add_column(conn, "tt_outlook", "module_code", "TEXT")      # the code the event names (feeds.event_code)
    _add_column(conn, "tt_outlook", "module_id", "TEXT")        # the module with that code, if there is one


def _word_rules_to_label_map(conn):
    """Another version of Venato kept word rules ('Rugby' -> Sports) in category_rules; since labels
    match activities as whole words, they become activity defaults (once, keeping any already set)."""
    if not conn.execute("SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'category_rules'").fetchone():
        return
    have = {r[0].lower() for r in conn.execute("SELECT label FROM tt_label_map")}
    for word, cid in conn.execute("SELECT word, category_id FROM category_rules").fetchall():
        if word and word.strip() and word.strip().lower() not in have:
            conn.execute("INSERT INTO tt_label_map VALUES (?, ?)", (word.strip(), cid))
            have.add(word.strip().lower())


def _goals_become_todo_groups(conn):
    """A goal (e.g. "Get a job") is also a to-do category: todo_groups.goal_id links the two. When the
    column is new, the goals still running get their category, once (one deleted later stays deleted)."""
    if "goal_id" in {row[1] for row in conn.execute("PRAGMA table_info(todo_groups)")}:
        return
    conn.execute("ALTER TABLE todo_groups ADD COLUMN goal_id TEXT")
    goals = {row[1] for row in conn.execute("PRAGMA table_info(goals)")}
    if "due" not in goals:
        return                                    # a database from before goals had deadlines: none to link
    plan = "AND deadline_id IS NULL AND closed = 0" if "deadline_id" in goals else ""
    from .dates import local_today
    rows = conn.execute(f"SELECT id, title FROM goals WHERE due >= ? {plan} ORDER BY ord",
                        (local_today().isoformat(),)).fetchall()
    from .todos import link_goal_group
    for goal_id, title in rows:
        link_goal_group(conn, goal_id, title)


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
