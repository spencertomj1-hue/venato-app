"""
Data layer for Venato: every SQL query lives here. No Streamlit code, so the
pages, the Claude tools and the tests all share the same logic.

All user data lives in the data folder (system.default_data_dir(): ~/Library/Application Support/Venato
on a Mac, %APPDATA%/Venato on Windows, ~/.local/share/Venato on Linux), or $VENATO_DATA_DIR, used for tests and the demo). The database is life.db
there (or $VENATO_DB). Backups, settings.json and the Outlook cache live there
too. Nothing user-specific is kept in the project folder.
"""

import json
import os
import re
import sqlite3
import uuid
from contextlib import contextmanager
from datetime import date, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import pandas as pd

from venato import system

DATA_DIR = system.data_dir()          # (copies an old Arete data folder across the first time)
DB_PATH = Path(system.env("DB") or DATA_DIR / "life.db")

# Habits appear as extra columns in the History table and CSV, named "habit: <name>".
HABIT_PREFIX = "habit: "

# Timetable: quarter-hour slots from day_start to day_end (default 07:00 to 01:00 the next day,
# 72 slots). Set in Settings -> Region; _apply_day_hours() keeps SLOTS and FIRST_MIN in step.
SLOT_MIN = 15
DAY_START, DAY_END = 7, 1           # defaults (hours); an end at or before the start is the next morning
SLOTS = 18 * 60 // SLOT_MIN
FIRST_MIN = 7 * 60
TRACKS = ("plan", "actual")

# The categories a new install starts with: generic, and editable under the timetable or by asking Claude.
# (id, name, colour, text colour, group) in key order.
DEFAULT_CATEGORIES = [
    ("sleep", "Sleep", "#D0D0D0", None, "Life"),
    ("meals", "Meals", "#F7C7AC", None, "Life"),
    ("exercise", "Exercise", "#FFC000", None, "Life"),
    ("social", "Social", "#D86DCD", None, "Life"),
    ("rest", "Rest", "#E49EDD", None, "Life"),
    ("reading", "Reading", "#7030A0", "#FFFFFF", "Life"),
    ("commute", "Commute", "#FFF7B8", None, "Life"),
    ("chores", "Chores", "#92D050", None, "Life"),
    ("distracted", "Distracted", "#FF0000", None, "Life"),
    ("classes", "Classes", "#00B0F0", None, "Work"),
    ("study", "Study", "#00B050", None, "Work"),
    ("work", "Work", "#83CCEB", None, "Work"),
    ("projects", "Projects", "#DAF2D0", None, "Work"),
]

# Outlook events use this category unless settings.json says otherwise ("outlook_category").
DEFAULT_OUTLOOK_CATEGORY = "classes"

# Network groups (they colour people in the Network web); editable on the Network page.
DEFAULT_NET_GROUPS = [
    ("family", "Family", "#E5484D"),
    ("friends", "Friends", "#F5A524"),
    ("uni", "Uni", "#3E8EF7"),
    ("work", "Work", "#30A46C"),
    ("mentors", "Mentors", "#8E4EC6"),
    ("other", "Other", "#8B8D98"),
]

# Typing one of these activities picks its category automatically.
DEFAULT_LABEL_MAP = {
    "Sleep": "sleep", "Breakfast": "meals", "Lunch": "meals", "Dinner": "meals",
    "Gym": "exercise", "Run": "exercise", "Lecture": "classes", "Seminar": "classes",
    "Homework": "study", "Revision": "study", "Commute": "commute",
}


# ---------------------------------------------------------------------------
# Connection + schema
# ---------------------------------------------------------------------------

@contextmanager
def db():
    """Open a connection, commit on success, and always close it."""
    conn = sqlite3.connect(DB_PATH)
    conn.execute("PRAGMA foreign_keys = ON")  # needed for ON DELETE CASCADE
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def init_db():
    """Create tables if they don't exist yet, and seed the timetable key."""
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
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
                start       TEXT NOT NULL,     -- "HH:mm", on a quarter hour
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

            -- Start Working: one row per unit of work (an email sent, a networking contact, a public post),
            -- counted towards the level it was done in.
            CREATE TABLE IF NOT EXISTS work_log (
                id    TEXT PRIMARY KEY,
                track TEXT NOT NULL,                     -- a bar's key (the user's own: settings work_bars)
                level INTEGER NOT NULL,
                at    TEXT NOT NULL
            );
            -- Start Working's session list: what the user said needs doing today, in order. Each
            -- item can be linked to a to-do and/or a bar; ticking it ticks those too.
            CREATE TABLE IF NOT EXISTS work_session (
                id      TEXT PRIMARY KEY,
                day     TEXT NOT NULL,
                ord     INTEGER NOT NULL,
                title   TEXT NOT NULL,
                done    INTEGER NOT NULL DEFAULT 0,
                todo_id TEXT,                            -- a to-do it ticks off
                track   TEXT,                            -- a bar it adds to
                amount  INTEGER NOT NULL DEFAULT 1       -- how many it adds (e.g. "send 5 emails")
            );
            -- Start Working's plan: every task gets a decision (me / delegate / drop), to force delegation.
            CREATE TABLE IF NOT EXISTS work_plan (
                id       TEXT PRIMARY KEY,
                title    TEXT NOT NULL,
                decision TEXT,                           -- NULL (not decided yet), 'me', 'delegate' or 'drop'
                who      TEXT,                           -- who it's delegated to
                done     INTEGER NOT NULL DEFAULT 0,
                created  TEXT NOT NULL,
                decided  TEXT
            );
            -- The Start Working pot: +5 for each level completed, minus what's spent.
            CREATE TABLE IF NOT EXISTS work_wallet (
                id     TEXT PRIMARY KEY,
                at     TEXT NOT NULL,
                amount REAL NOT NULL,                    -- positive = earned, negative = spent
                kind   TEXT NOT NULL,                    -- 'earned', or the key of the pot it was spent on
                note   TEXT
            );

            -- The user's own to-do categories (e.g. "At home repairs"), separate from the timetable's.
            CREATE TABLE IF NOT EXISTS todo_groups (
                id     TEXT PRIMARY KEY,
                name   TEXT NOT NULL UNIQUE COLLATE NOCASE,
                colour TEXT NOT NULL,
                ord    INTEGER NOT NULL DEFAULT 0
            );

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

            -- Network: people you know, the groups that colour them, and who knows whom
            CREATE TABLE IF NOT EXISTS net_groups (
                id     TEXT PRIMARY KEY,
                name   TEXT NOT NULL UNIQUE COLLATE NOCASE,
                colour TEXT NOT NULL,                    -- "#RRGGBB"
                ord    INTEGER NOT NULL,
                parent_id TEXT                           -- the group it sits inside; NULL = top level
            );
            CREATE TABLE IF NOT EXISTS net_people (
                id          TEXT PRIMARY KEY,
                name        TEXT NOT NULL,
                description TEXT,                        -- who they are, how you know them
                works_for   TEXT,                        -- company, university, team...
                group_id    TEXT REFERENCES net_groups(id) ON DELETE SET NULL,
                created_at  TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS net_links (       -- undirected: always stored with a < b
                a      TEXT NOT NULL REFERENCES net_people(id) ON DELETE CASCADE,
                b      TEXT NOT NULL REFERENCES net_people(id) ON DELETE CASCADE,
                reason TEXT,                             -- how they know each other
                PRIMARY KEY (a, b),
                CHECK (a < b)
            );

            -- Training: a plan (e.g. 8 weeks to a half marathon) and its sessions
            CREATE TABLE IF NOT EXISTS training_plans (
                id         TEXT PRIMARY KEY,
                name       TEXT NOT NULL,
                start_date TEXT NOT NULL,
                race_date  TEXT NOT NULL,
                created_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS training_sessions (
                id          TEXT PRIMARY KEY,
                plan_id     TEXT NOT NULL REFERENCES training_plans(id) ON DELETE CASCADE,
                week        INTEGER NOT NULL,
                date        TEXT NOT NULL,
                kind        TEXT NOT NULL,      -- easy, long, tempo, intervals, race_pace, strength, shakeout, race
                title       TEXT NOT NULL,
                distance_km REAL,               -- planned; NULL for strength
                details     TEXT,
                done        INTEGER NOT NULL DEFAULT 0,
                actual_km   REAL,               -- what was really run (NULL = as planned)
                notes       TEXT,
                done_at     TEXT,
                ord         INTEGER NOT NULL DEFAULT 0
            );
            CREATE INDEX IF NOT EXISTS training_sessions_day ON training_sessions (date);

            -- Joint calendar (joint.py): busy times from the user's and their partner's calendars.
            -- Fully replaced per person on every refresh. Titles only for events marked "!".
            CREATE TABLE IF NOT EXISTS joint_events (
                who       TEXT NOT NULL CHECK (who IN ('me', 'partner')),
                uid       TEXT NOT NULL,
                date      TEXT NOT NULL,
                start_min INTEGER,            -- minutes after midnight; NULL if all-day
                end_min   INTEGER,            -- exclusive, up to 1440
                title     TEXT,               -- NULL = just blocked-out time
                all_day   INTEGER NOT NULL DEFAULT 0,
                PRIMARY KEY (who, uid)
            );
            CREATE INDEX IF NOT EXISTS joint_events_day ON joint_events (date);

            -- Gym log: sessions and their exercises (weight, sets, reps)
            CREATE TABLE IF NOT EXISTS gym_sessions (
                id         TEXT PRIMARY KEY,
                date       TEXT NOT NULL,
                title      TEXT NOT NULL,
                notes      TEXT,
                created_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS gym_exercises (
                id         INTEGER PRIMARY KEY AUTOINCREMENT,
                session_id TEXT NOT NULL REFERENCES gym_sessions(id) ON DELETE CASCADE,
                ord        INTEGER NOT NULL DEFAULT 0,
                exercise   TEXT NOT NULL,
                sets       INTEGER,
                reps       INTEGER,
                weight_kg  REAL
            );
            CREATE INDEX IF NOT EXISTS gym_sessions_day ON gym_sessions (date);

            -- Strava activities (strava.py), read only
            CREATE TABLE IF NOT EXISTS strava_activities (
                id          TEXT PRIMARY KEY,
                date        TEXT NOT NULL,
                start       TEXT,
                name        TEXT,
                sport       TEXT,              -- Strava's sport_type, e.g. Run, TrailRun, Ride
                distance_km REAL,
                moving_min  REAL,
                elevation_m REAL,
                avg_hr      REAL,
                session_id  TEXT               -- the training session it ticked off, if any
            );
            CREATE INDEX IF NOT EXISTS strava_day ON strava_activities (date);

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

            -- Times the user saw or spoke to someone ("had coffee, talked about X")
            CREATE TABLE IF NOT EXISTS net_interactions (
                id         TEXT PRIMARY KEY,
                person_id  TEXT NOT NULL REFERENCES net_people(id) ON DELETE CASCADE,
                date       TEXT NOT NULL,                -- YYYY-MM-DD
                note       TEXT NOT NULL,
                created_at TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS net_interactions_person ON net_interactions (person_id, date);

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

            -- Applications: jobs, internships, courses... one row each, with where it's up to
            CREATE TABLE IF NOT EXISTS applications (
                id          TEXT PRIMARY KEY,
                industry    TEXT,
                company     TEXT,
                route       TEXT,                        -- e.g. Graduate scheme, Internship, Spring week
                description TEXT,
                contact     TEXT,                        -- contact / lead
                deadline    TEXT,                        -- YYYY-MM-DD, or NULL
                status      TEXT NOT NULL,
                notes       TEXT,
                created_at  TEXT NOT NULL,
                updated_at  TEXT NOT NULL
            );
            """
        )
        # Each block's own tables (venato/blocks/*), then their later changes.
        from venato import blocks
        conn.executescript(blocks.schema_sql())
        for migrate in blocks.migrations():
            migrate(conn)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS category_rules (
                id          INTEGER PRIMARY KEY,
                word        TEXT NOT NULL UNIQUE COLLATE NOCASE,
                category_id TEXT NOT NULL
            )""")
        conn.execute("""
            CREATE TABLE IF NOT EXISTS event_status (
                id   TEXT PRIMARY KEY,      -- a block's id, or "ol:<uid>" for an Outlook event
                done INTEGER NOT NULL       -- 1 = done (green), 0 = not done (black)
            )""")
        # Columns added after the first release.
        _add_column(conn, "tt_entries", "details", "TEXT")
        _add_column(conn, "entries", "water", "REAL")
        _add_column(conn, "habits", "per_week", "INTEGER")          # NULL = every day; else N times a week
        _journal_became_notes(conn)
        _add_column(conn, "tt_outlook", "description", "TEXT")
        _add_column(conn, "tt_outlook", "teams", "INTEGER NOT NULL DEFAULT 0")
        _add_column(conn, "net_groups", "parent_id", "TEXT")
        _add_column(conn, "goals", "kind", "TEXT NOT NULL DEFAULT 'target'")   # 'target' (a number) or 'simple' (done / not yet)
        _add_column(conn, "goals", "done_at", "TEXT")
        _add_column(conn, "training_sessions", "block_id", "TEXT")             # its block on the timetable, if any
        # 1 = the user took it off the timetable (deleted its block), so it isn't put back automatically
        _add_column(conn, "training_sessions", "off_timetable", "INTEGER NOT NULL DEFAULT 0")
        _add_column(conn, "todos", "off_timetable", "INTEGER NOT NULL DEFAULT 0")
        _add_column(conn, "todos", "due", "TEXT")              # done by this day (NULL: the end of its list's period)
        _add_column(conn, "todos", "place", "TEXT")            # 'home', 'laptop' or NULL (anywhere)
        _add_column(conn, "todos", "category_id", "TEXT")      # timetable category (NULL: the To-dos one)
        _add_column(conn, "todos", "minutes", "INTEGER")       # how long it should take (NULL: 30)
        _add_column(conn, "todos", "group_id", "TEXT")
        _add_column(conn, "goals", "category", "TEXT")         # a goal category's name (colours in settings)         # the user's to-do category (todo_groups), NULL: none                          # when a simple goal was achieved
        _add_column(conn, "entries", "productivity", "INTEGER")    # 1-10, self-rated
        _scores_out_of_ten(conn)
        if use_presets() and conn.execute("SELECT COUNT(*) FROM tt_categories").fetchone()[0] == 0:
            conn.executemany(
                "INSERT INTO tt_categories VALUES (?, ?, ?, ?, ?, ?)",
                [(cid, name, col, txt, grp, i) for i, (cid, name, col, txt, grp) in enumerate(DEFAULT_CATEGORIES)],
            )
        if use_presets() and conn.execute("SELECT COUNT(*) FROM tt_label_map").fetchone()[0] == 0:
            conn.executemany("INSERT INTO tt_label_map VALUES (?, ?)", DEFAULT_LABEL_MAP.items())
        if use_presets() and conn.execute("SELECT COUNT(*) FROM net_groups").fetchone()[0] == 0:
            conn.executemany("INSERT INTO net_groups (id, name, colour, ord) VALUES (?, ?, ?, ?)",
                             [(gid, name, colour, i) for i, (gid, name, colour) in enumerate(DEFAULT_NET_GROUPS)])



# ---------------------------------------------------------------------------
# Settings (settings.json in the data folder)
# ---------------------------------------------------------------------------

def use_presets():
    """
    Whether a new install starts with example lists: timetable categories, activity defaults,
    network groups, and the blocks' starter lists. Off: everything starts empty and is the user's
    own. settings.json "presets": true (or $VENATO_PRESETS=1, as the tests use) turns them on.
    """
    return system.env("PRESETS") == "1" or bool(load_settings().get("presets"))


def settings_path():
    return DATA_DIR / "settings.json"


def load_settings():
    try:
        return json.loads(settings_path().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def ai_enabled():
    """Is the optional Claude assistant switched on? (Off on new installs unless chosen in setup;
    on for installs from before the switch existed.)"""
    return bool(load_settings().get("ai_enabled", True))


# ---------------------------------------------------------------------------
# Time zone: settings.json "timezone" (an IANA name like "America/New_York"),
# else the computer's own. Every "now" and "today" in Venato goes through here.
# ---------------------------------------------------------------------------

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
    save_settings(week_start=name)


def local_now():
    """Now, as a plain (naive) date and time in the user's time zone."""
    return datetime.now(tz()).replace(tzinfo=None)


def local_today():
    return datetime.now(tz()).date()


def stamp():
    """A timestamp for created_at / done_at columns (with its UTC offset)."""
    return datetime.now(tz()).isoformat(timespec="seconds")


def save_settings(**changes):
    settings = {**load_settings(), **changes}
    settings_path().parent.mkdir(parents=True, exist_ok=True)
    settings_path().write_text(json.dumps(settings, indent=2), encoding="utf-8")
    if {"day_start", "day_end"} & set(changes):
        _apply_day_hours()
    return settings


def day_hours():
    """(start hour, end hour) of a timetable day; an end at or before the start is the next morning."""
    s = load_settings()
    start, end = s.get("day_start", DAY_START), s.get("day_end", DAY_END)
    ok = lambda h: isinstance(h, int) and 0 <= h <= 23
    return (start, end) if ok(start) and ok(end) and day_length(start, end) >= MIN_DAY_HOURS else (DAY_START, DAY_END)


MIN_DAY_HOURS = 6


def day_length(start, end):
    """Hours in a timetable day from start to end (wrapping past midnight; equal = a full 24 hours)."""
    return (end - start) % 24 or 24


def _apply_day_hours():
    global SLOTS, FIRST_MIN
    start, end = day_hours()
    FIRST_MIN, SLOTS = start * 60, 60 // SLOT_MIN * day_length(start, end)


def _goals_became_todos(conn):
    """
    Early versions called the to-do lists "goals". If this database has that old
    table, back it up, rename it (and its rollover table) to todos, and drop the
    yearly to-dos, which no longer exist. The new goals table is then created fresh.
    """
    columns = {row[1] for row in conn.execute("PRAGMA table_info(goals)")}
    if "done" not in columns:
        return
    backups = DATA_DIR / "backups"
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


def _add_column(conn, table, column, kind):
    """Add a column to an existing table if an older database doesn't have it yet."""
    if column not in {row[1] for row in conn.execute(f"PRAGMA table_info({table})")}:
        conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {kind}")


def _read(sql, params=()):
    """Run a query into a DataFrame, with SQL NULLs as None (NaN isn't valid JSON)."""
    with db() as conn:
        df = pd.read_sql(sql, conn, params=params)
    return df.astype(object).where(df.notna(), None)


# ---------------------------------------------------------------------------
# Daily entries
# ---------------------------------------------------------------------------

def get_entry(day):
    """Return the entry for an ISO date as a dict, or an empty dict."""
    with db() as conn:
        conn.row_factory = sqlite3.Row
        row = conn.execute("SELECT * FROM entries WHERE date = ?", (day,)).fetchone()
    return dict(row) if row else {}


KEEP = object()   # e.g. save_entry(water=KEEP), update_goal: leave this field as it is


def _scores_out_of_ten(conn):
    """Mood and energy used to be out of 5: double them, once, so old days match the new 1-10 scale."""
    conn.execute("CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT)")
    if conn.execute("SELECT 1 FROM meta WHERE key = 'scores_out_of_10'").fetchone():
        return
    conn.execute("UPDATE entries SET mood = mood * 2 WHERE mood IS NOT NULL")
    conn.execute("UPDATE entries SET energy = energy * 2 WHERE energy IS NOT NULL")
    conn.execute("INSERT INTO meta (key, value) VALUES ('scores_out_of_10', '1')")


def save_entry(conn, day, mood, sleep, energy, notes, water=KEEP, productivity=KEEP):
    """Insert or update the entry for a date (uses an open connection). Mood, energy and
    productivity are 1-10."""
    cols = {"mood": mood, "sleep": sleep, "energy": energy, "notes": notes}
    if water is not KEEP:
        cols["water"] = water
    if productivity is not KEEP:
        cols["productivity"] = productivity
    conn.execute(
        f"INSERT INTO entries (date, {', '.join(cols)}) VALUES (?{', ?' * len(cols)}) "
        f"ON CONFLICT(date) DO UPDATE SET {', '.join(f'{c} = excluded.{c}' for c in cols)}",
        (day, *cols.values()),
    )


ENTRY_FIELDS = {"mood": (1, 10), "energy": (1, 10), "sleep": (0, 24)}
DECIMAL_FIELDS = ("sleep",)


def set_entry_field(day, field, value):
    """Set one ENTRY_FIELDS value for a day, keeping the rest of its entry (and its journal page)."""
    lo, hi = ENTRY_FIELDS[field]
    value = None if value is None else max(lo, min(hi, float(value) if field in DECIMAL_FIELDS else int(value)))
    with db() as conn:
        conn.execute(f"INSERT INTO entries (date, {field}) VALUES (?, ?) "
                     f"ON CONFLICT(date) DO UPDATE SET {field} = excluded.{field}", (str(day), value))


# ---------------------------------------------------------------------------
# Day trackers: numbers the user chose to log each day (e.g. "Reading, hours, 0.5" or
# "Coffee, cups, 1"). Their list is in settings.json ("day_trackers": [{id, name, unit, step}]),
# so nothing about them is in the code; the values are in day_values.
# ---------------------------------------------------------------------------

def day_trackers():
    return [dict(t) for t in load_settings().get("day_trackers", [])]


def find_day_tracker(ref):
    """A tracker by id or name (any case), or None."""
    ref = str(ref or "").strip().lower()
    return next((t for t in day_trackers() if t["id"] == ref or t["name"].lower() == ref), None)


def add_day_tracker(name, unit="", step=1):
    """Add a tracker; returns it. Raises ValueError for a missing or taken name, or a bad step."""
    name, unit = str(name or "").strip(), str(unit or "").strip()
    if not name:
        raise ValueError("A tracker needs a name.")
    if find_day_tracker(name):
        raise ValueError(f"There's already a tracker called '{name}'.")
    step = float(step or 1)
    if step <= 0:
        raise ValueError("The step must be more than 0.")
    tracker = {"id": uuid.uuid4().hex[:10], "name": name, "unit": unit, "step": step}
    save_settings(day_trackers=day_trackers() + [tracker])
    return tracker


def update_day_tracker(tracker_id, **changes):
    trackers = day_trackers()
    for t in trackers:
        if t["id"] == tracker_id:
            if "name" in changes:
                name = str(changes["name"] or "").strip()
                if not name:
                    raise ValueError("A tracker needs a name.")
                if any(o["id"] != tracker_id and o["name"].lower() == name.lower() for o in trackers):
                    raise ValueError(f"There's already a tracker called '{name}'.")
                t["name"] = name
            if "unit" in changes:
                t["unit"] = str(changes["unit"] or "").strip()
            if "step" in changes and float(changes["step"] or 0) > 0:
                t["step"] = float(changes["step"])
    save_settings(day_trackers=trackers)


def delete_day_tracker(tracker_id):
    """Remove a tracker and everything logged for it."""
    save_settings(day_trackers=[t for t in day_trackers() if t["id"] != tracker_id])
    with db() as conn:
        conn.execute("DELETE FROM day_values WHERE tracker = ?", (tracker_id,))


def set_day_value(day, tracker_id, value):
    """Set a tracker's number for a day (0 or more); None clears it."""
    with db() as conn:
        if value is None:
            conn.execute("DELETE FROM day_values WHERE date = ? AND tracker = ?", (str(day), tracker_id))
        else:
            conn.execute("INSERT OR REPLACE INTO day_values VALUES (?, ?, ?)",
                         (str(day), tracker_id, max(0.0, min(float(value), 100000.0))))


def day_values(day):
    """{tracker id: value} logged for a day."""
    with db() as conn:
        return dict(conn.execute("SELECT tracker, value FROM day_values WHERE date = ?", (str(day),)).fetchall())


def day_values_between(first, last):
    """[(date, tracker id, value)] between two ISO dates (inclusive), oldest first."""
    with db() as conn:
        return conn.execute("SELECT date, tracker, value FROM day_values WHERE date BETWEEN ? AND ? ORDER BY date",
                            (str(first), str(last))).fetchall()


def entries_between(first, last):
    """Daily entries between two ISO dates (inclusive), oldest first."""
    return _read("SELECT * FROM entries WHERE date BETWEEN ? AND ? ORDER BY date", (first, last))


# ---------------------------------------------------------------------------
# Journal: a day's notes are its journal entry (entries.notes)
# ---------------------------------------------------------------------------

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


def get_journal(day):
    """A day's notes / journal entry ('' if none)."""
    with db() as conn:
        row = conn.execute("SELECT notes FROM entries WHERE date = ?", (_as_date(day).isoformat(),)).fetchone()
    return (row[0] or "") if row else ""


def save_journal(day, text):
    """Set a day's notes / journal entry, leaving mood, sleep etc. alone; blank text clears it."""
    day, text = _as_date(day).isoformat(), str(text or "").strip() or None
    with db() as conn:
        conn.execute("INSERT INTO entries (date, notes) VALUES (?, ?) "
                     "ON CONFLICT(date) DO UPDATE SET notes = excluded.notes", (day, text))
        conn.execute("DELETE FROM entries WHERE date = ? AND mood IS NULL AND sleep IS NULL "
                     "AND energy IS NULL AND notes IS NULL AND water IS NULL AND productivity IS NULL", (day,))


def append_journal(day, text):
    """Add a paragraph to the end of a day's journal; returns the whole entry."""
    text = str(text or "").strip()
    if not text:
        raise ValueError("Nothing to write.")
    old = get_journal(day)
    new = f"{old}\n\n{text}" if old else text
    save_journal(day, new)
    return new


def journal_entries(query=None, first=None, last=None, limit=None):
    """[{date, text}] newest first; `query` matches words anywhere (any case), dates are inclusive."""
    sql, params = "SELECT date, notes FROM entries WHERE TRIM(COALESCE(notes, '')) != ''", []
    for word in str(query or "").split():
        sql += " AND notes LIKE ? ESCAPE '\\'"
        params.append("%" + word.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%")
    if first:
        sql += " AND date >= ?"; params.append(_as_date(first).isoformat())
    if last:
        sql += " AND date <= ?"; params.append(_as_date(last).isoformat())
    sql += " ORDER BY date DESC" + (f" LIMIT {int(limit)}" if limit else "")
    with db() as conn:
        return [{"date": d, "text": t} for d, t in conn.execute(sql, params)]


# ---------------------------------------------------------------------------
# Deadlines
# ---------------------------------------------------------------------------

DEADLINE_COLS = "id, title, due, notes, done, done_at, created_at"


def _deadline(row):
    return dict(zip(DEADLINE_COLS.split(", "), row)) | {"done": bool(row[4])}


def add_deadline(title, due, notes=None):
    """Add a deadline; returns its id."""
    title = str(title or "").strip()
    if not title:
        raise ValueError("Say what's due.")
    did = uuid.uuid4().hex
    with db() as conn:
        conn.execute(f"INSERT INTO deadlines ({DEADLINE_COLS}) VALUES (?, ?, ?, ?, 0, NULL, ?)",
                     (did, title, _as_date(due).isoformat(), (notes or "").strip() or None,
                      stamp()))
    return did


def get_deadline(did):
    with db() as conn:
        row = conn.execute(f"SELECT {DEADLINE_COLS} FROM deadlines WHERE id = ?", (did,)).fetchone()
    return _deadline(row) if row else None


def deadlines(include_done=False):
    """Deadlines, soonest first (open ones; with include_done, the done ones too)."""
    sql = f"SELECT {DEADLINE_COLS} FROM deadlines" + ("" if include_done else " WHERE done = 0")
    with db() as conn:
        return [_deadline(r) for r in conn.execute(sql + " ORDER BY due, created_at")]


def update_deadline(did, title=KEEP, due=KEEP, notes=KEEP):
    fields = {}
    if title is not KEEP:
        if not str(title or "").strip():
            raise ValueError("Say what's due.")
        fields["title"] = str(title).strip()
    if due is not KEEP:
        fields["due"] = _as_date(due).isoformat()
    if notes is not KEEP:
        fields["notes"] = (notes or "").strip() or None
    if fields:
        with db() as conn:
            conn.execute(f"UPDATE deadlines SET {', '.join(f'{k} = ?' for k in fields)} WHERE id = ?",
                         (*fields.values(), did))


def set_deadline_done(did, done):
    with db() as conn:
        conn.execute("UPDATE deadlines SET done = ?, done_at = ? WHERE id = ?",
                      (int(bool(done)), stamp() if done else None, did))


def delete_deadline(did):
    with db() as conn:
        conn.execute("DELETE FROM deadlines WHERE id = ?", (did,))


# ---------------------------------------------------------------------------
# Applications (the Applications page)
# ---------------------------------------------------------------------------

APP_STATUSES = ["To apply", "Applied", "Online test", "Interview", "Assessment centre",
                "Offer", "Accepted", "Rejected", "Withdrawn"]
APP_TEXT = ("industry", "company", "route", "description", "contact", "notes")
APP_COLS = "id, " + ", ".join(APP_TEXT[:5]) + ", deadline, status, notes, created_at, updated_at"


def _application_fields(fields):
    """Tidy user input: stripped text (blank -> None), a real date or None, a known status."""
    out = {}
    for k, v in fields.items():
        if k in APP_TEXT:
            out[k] = (str(v).strip() if v is not None and str(v) not in ("nan", "NaT", "None") else "") or None
        elif k == "deadline":
            out[k] = _as_date(str(v)[:10]).isoformat() if v not in (None, "") and str(v) not in ("nan", "NaT", "None") else None
        elif k == "status":
            if v not in APP_STATUSES:
                raise ValueError(f"Status must be one of: {', '.join(APP_STATUSES)}.")
            out[k] = v
        else:
            raise ValueError(f"Unknown application field: {k}")
    return out


def add_application(status="To apply", **fields):
    """Add an application; returns its id. Fields: industry, company, route, description,
    contact, deadline, notes."""
    row = _application_fields({"status": status or "To apply", **fields})
    if not any(row.get(k) for k in ("company", "industry", "route", "description")):
        raise ValueError("Say at least the company (or what it's for).")
    aid, now = uuid.uuid4().hex, stamp()
    cols = ["id", *row, "created_at", "updated_at"]
    with db() as conn:
        conn.execute(f"INSERT INTO applications ({', '.join(cols)}) VALUES ({', '.join('?' * len(cols))})",
                     (aid, *row.values(), now, now))
    return aid


def applications():
    """Every application: soonest deadline first (no deadline last), then newest."""
    with db() as conn:
        rows = conn.execute(f"SELECT {APP_COLS} FROM applications "
                            "ORDER BY deadline IS NULL, deadline, created_at DESC").fetchall()
    return [dict(zip(APP_COLS.split(", "), r)) for r in rows]


def get_application(aid):
    with db() as conn:
        row = conn.execute(f"SELECT {APP_COLS} FROM applications WHERE id = ?", (aid,)).fetchone()
    return dict(zip(APP_COLS.split(", "), row)) if row else None


def update_application(aid, **fields):
    row = _application_fields(fields)
    if row:
        with db() as conn:
            conn.execute(f"UPDATE applications SET {', '.join(f'{k} = ?' for k in row)}, updated_at = ? WHERE id = ?",
                         (*row.values(), stamp(), aid))


def delete_application(aid):
    with db() as conn:
        conn.execute("DELETE FROM applications WHERE id = ?", (aid,))


def countdown(due, today=None):
    """'Today', 'Tomorrow', 'in 5 days', 'Yesterday' or '3 days overdue'."""
    n = (_as_date(due) - (today or local_today())).days
    if n == 0:
        return "Today"
    if n == 1:
        return "Tomorrow"
    if n == -1:
        return "1 day overdue"
    return f"in {n} days" if n > 0 else f"{-n} days overdue"


# ---------------------------------------------------------------------------
# Habits
# ---------------------------------------------------------------------------

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


# ---------------------------------------------------------------------------
# Whole-dataset helpers (used by History and Export/Import)
#
# Everything is represented as one "wide" table: one row per date with
# mood/sleep/energy/productivity/notes plus a True/False column per habit.
# ---------------------------------------------------------------------------

def load_all_data():
    """Return all entries and habit ticks as one DataFrame, newest first."""
    with db() as conn:
        entries = pd.read_sql("SELECT * FROM entries", conn)
        logs = pd.read_sql(
            "SELECT h.name, l.date FROM habit_log l JOIN habits h ON h.id = l.habit_id", conn
        )
    habit_names = [name for _, name in get_habits()]

    # Every date that has an entry or at least one habit tick.
    all_dates = sorted(set(entries["date"]) | set(logs["date"]), reverse=True)
    df = entries.set_index("date").reindex(all_dates)
    for name in habit_names:
        done = set(logs.loc[logs["name"] == name, "date"])
        df[HABIT_PREFIX + name] = df.index.isin(done)

    df.index.name = "date"
    df = df.reset_index()
    df["date"] = pd.to_datetime(df["date"]).dt.date
    return df


def _clean(value, cast):
    """Turn blanks/NaN into None, otherwise cast to a plain Python type."""
    if value is None or pd.isna(value) or str(value).strip() == "":
        return None
    return cast(value)


def _score(value):
    """A 1-10 score from a CSV / table cell (rounded, kept in range)."""
    return max(1, min(10, int(round(float(value)))))


def _is_ticked(value):
    """Interpret a CSV/table cell as a habit tick."""
    if value is None or pd.isna(value):
        return False
    return str(value).strip().lower() in {"1", "1.0", "true", "yes", "y", "x"}


def save_all_data(df, replace=False):
    """
    Write a wide DataFrame back to the database.
    replace=True wipes existing data first; otherwise rows are merged by date.
    """
    habit_cols = [c for c in df.columns if c.startswith(HABIT_PREFIX)]
    # A CSV exported before scores went out of 10 has no productivity column: its mood and
    # energy are out of 5 (if none is above 5), so they're doubled.
    old_scale = "productivity" not in df.columns and all(
        pd.to_numeric(df[c], errors="coerce").dropna().le(5).all() for c in ("mood", "energy") if c in df.columns)
    with db() as conn:
        if replace:
            conn.execute("DELETE FROM entries")
            conn.execute("DELETE FROM habits")  # also clears habit_log (cascade)

        # Make sure every habit column has a habit, then look up the ids.
        for col in habit_cols:
            conn.execute("INSERT OR IGNORE INTO habits (name) VALUES (?)", (col[len(HABIT_PREFIX):],))
        habit_ids = dict(conn.execute("SELECT name, id FROM habits").fetchall())

        for row in df.to_dict("records"):
            if row.get("date") is None or pd.isna(row.get("date")):
                continue  # skip blank rows (e.g. an empty row added in the editor)
            day = pd.to_datetime(row["date"]).date().isoformat()

            mood = _clean(row.get("mood"), _score)
            sleep = _clean(row.get("sleep"), float)
            energy = _clean(row.get("energy"), _score)
            if old_scale:
                mood, energy = (None if v is None else v * 2 for v in (mood, energy))
            notes = _clean(row.get("notes"), str)
            water = _clean(row.get("water"), float) if "water" in df.columns else KEEP
            prod = _clean(row.get("productivity"), _score) if "productivity" in df.columns else KEEP
            if any(v not in (None, KEEP) for v in (mood, sleep, energy, notes, water, prod)):
                save_entry(conn, day, mood, sleep, energy, notes, water, prod)

            for col in habit_cols:
                set_habit_done(conn, habit_ids[col[len(HABIT_PREFIX):]], day, _is_ticked(row[col]))


# ---------------------------------------------------------------------------
# Timetable: categories and label map
# ---------------------------------------------------------------------------

def load_categories():
    return _read("SELECT * FROM tt_categories ORDER BY grp, ord")


def groups():
    """Category groups in the order they first appear in the key, e.g. ["Life", "Work"]."""
    with db() as conn:
        rows = conn.execute("SELECT grp FROM tt_categories ORDER BY rowid").fetchall()
    return list(dict.fromkeys(r[0] for r in rows))


def load_label_map():
    return _read("SELECT * FROM tt_label_map ORDER BY label")


def save_category(cid, name, colour, grp, text_colour=None):
    """Create or update one category (keeps its place in the key)."""
    with db() as conn:
        exists = conn.execute("SELECT ord FROM tt_categories WHERE id = ?", (cid,)).fetchone()
        if exists:
            conn.execute("UPDATE tt_categories SET name = ?, colour = ?, grp = ?, text_colour = ? WHERE id = ?",
                         (name, colour.upper(), grp, text_colour, cid))
        else:
            order = conn.execute("SELECT COALESCE(MAX(ord), -1) + 1 FROM tt_categories WHERE grp = ?", (grp,)).fetchone()[0]
            conn.execute("INSERT INTO tt_categories VALUES (?, ?, ?, ?, ?, ?)",
                         (cid, name, colour.upper(), text_colour, grp, order))


def category_usage(category_id):
    """(timetable blocks, activity defaults) that use a category."""
    with db() as conn:
        blocks = conn.execute("SELECT COUNT(*) FROM tt_entries WHERE category_id = ?", (category_id,)).fetchone()[0]
        labels = conn.execute("SELECT COUNT(*) FROM tt_label_map WHERE category_id = ?", (category_id,)).fetchone()[0]
    return blocks, labels


def merge_categories(source_id, target_id):
    """
    Fold one category into another: its blocks and activity defaults move to the
    target (and Outlook events, if they used it), then it leaves the key.
    """
    if source_id == target_id:
        raise ValueError("A category can't be merged into itself.")
    with db() as conn:
        conn.execute("UPDATE tt_entries SET category_id = ? WHERE category_id = ?", (target_id, source_id))
        conn.execute("UPDATE tt_label_map SET category_id = ? WHERE category_id = ?", (target_id, source_id))
        conn.execute("UPDATE category_rules SET category_id = ? WHERE category_id = ?", (target_id, source_id))
        conn.execute("DELETE FROM tt_categories WHERE id = ?", (source_id,))
    settings = load_settings()
    if settings.get("outlook_category") == source_id:
        save_settings(outlook_category=target_id)
    # Remembered so a built-in category (Teams, To-dos) doesn't come back after being deleted.
    replaced = {k: target_id if v == source_id else v for k, v in settings.get("replaced_categories", {}).items()}
    replaced.pop(target_id, None)
    save_settings(replaced_categories={**replaced, source_id: target_id})


def category_by_name(name, create=False):
    """A category's id by name (any case); with create, a new one (in the next colour) if there's none."""
    name = str(name or "").strip()
    cats = load_categories()
    for cid, n in zip(cats["id"], cats["name"]):
        if n.lower() == name.lower():
            return cid
    if not create or not name:
        return None
    return add_category(name, GOAL_CATEGORY_COLOURS[len(cats) % len(GOAL_CATEGORY_COLOURS)])


def add_category(name, colour, grp=None):
    """Create a category; returns its id. Raises ValueError if the name is blank or taken."""
    name = name.strip()
    cats = load_categories()
    if not name:
        raise ValueError("Give the category a name.")
    if name.lower() in {n.lower() for n in cats["name"]}:
        raise ValueError(f"There's already a category called '{name}'.")
    base = re.sub(r"[^a-z0-9]+", "_", name.lower()).strip("_") or "category"
    cid, n = base, 2
    while cid in set(cats["id"]):
        cid, n = f"{base}_{n}", n + 1
    save_category(cid, name, colour, grp or (groups() or ["Categories"])[0])
    return cid


def _builtin_category(spec):
    """A category the app relies on: made when first needed, or what replaced it if the user deleted it."""
    cid, name, colour, grp = spec
    ids = get_category_ids()
    if cid in ids:
        return cid
    replacement = load_settings().get("replaced_categories", {}).get(cid)
    if replacement in ids:
        return replacement
    existing = groups()
    save_category(cid, name, colour, grp if grp in existing or not existing else existing[-1])
    return cid


def load_rules():
    """Keyword rules as [{id, word, category_id}], longest word first so the most specific wins."""
    with db() as conn:
        rows = conn.execute("SELECT id, word, category_id FROM category_rules ORDER BY LENGTH(word) DESC, word").fetchall()
    return [dict(zip(("id", "word", "category_id"), r)) for r in rows]


def _has_word(text, word):
    """Whole words, any case: 'run' matches 'Morning run' but not 'brunch'. (mapLabel in the grid mirrors this.)"""
    return re.search(rf"(?<!\w){re.escape(word)}(?!\w)", text or "", re.IGNORECASE) is not None


def rule_category(text):
    """The category the rules give an event called `text`, or None."""
    return next((r["category_id"] for r in load_rules() if _has_word(text, r["word"])), None)


def add_rule(word, category_id, apply_existing=False):
    """
    Events containing `word` go in this category (a rule for the same word is replaced).
    With apply_existing, events already on the timetable follow it too. Returns how many changed.
    """
    word = word.strip()
    if not word:
        raise ValueError("Type the word to look for.")
    with db() as conn:
        conn.execute("INSERT INTO category_rules (word, category_id) VALUES (?, ?) "
                     "ON CONFLICT(word) DO UPDATE SET category_id = excluded.category_id", (word, category_id))
    if not apply_existing:
        return 0
    with db() as conn:
        rows = conn.execute("SELECT id, label FROM tt_entries WHERE category_id != ?", (category_id,)).fetchall()
    ids = [(category_id, bid) for bid, label in rows if rule_category(label) == category_id]
    with db() as conn:
        conn.executemany("UPDATE tt_entries SET category_id = ? WHERE id = ?", ids)
    return len(ids)


def delete_rule(rule_id):
    with db() as conn:
        conn.execute("DELETE FROM category_rules WHERE id = ?", (rule_id,))


def set_label_default(label, category_id):
    """Make an activity label default to a category."""
    with db() as conn:
        conn.execute("DELETE FROM tt_label_map WHERE lower(label) = lower(?)", (label,))
        conn.execute("INSERT INTO tt_label_map VALUES (?, ?)", (label.strip(), category_id))


def remove_label_default(label):
    """Forget an activity label's default category."""
    with db() as conn:
        conn.execute("DELETE FROM tt_label_map WHERE lower(label) = lower(?)", (label,))


def resolve_category(label=None, category=None):
    """
    Pick a category id. `category` may be an id or a name (any case); otherwise
    the label goes through the keyword rules, the label map, then category names.
    Returns None when nothing matches.
    """
    cats = load_categories()
    by_name = {n.lower(): i for i, n in zip(cats["id"], cats["name"])}
    if category:
        key = category.strip()
        if key in set(cats["id"]):
            return key
        return by_name.get(key.lower())
    if label:
        rule = rule_category(label)
        if rule:
            return rule
        lm = load_label_map()
        for lbl, cid in zip(lm["label"], lm["category_id"]):
            if lbl.lower() == label.strip().lower():
                return cid
        return by_name.get(label.strip().lower())
    return None


# ---------------------------------------------------------------------------
# Timetable: slots and painting rules
#
# These rules are the source of truth. The grid's JS (timetable_component.js,
# paintRange) mirrors them only to show edits instantly; what gets saved is
# always computed here.
# ---------------------------------------------------------------------------

def slot_time(i):
    """Slot index (0..SLOTS) -> "HH:mm". Slot SLOTS is the end of the last slot (01:00 by default)."""
    m = (FIRST_MIN + SLOT_MIN * i) % 1440
    return f"{m // 60:02d}:{m % 60:02d}"


def slot_of(t):
    """"HH:mm" -> slot index. Times before the day's start (07:00 by default) are after midnight."""
    h, m = map(int, t.split(":"))
    mins = h * 60 + m
    if mins < FIRST_MIN:
        mins += 1440
    return round((mins - FIRST_MIN) / SLOT_MIN)


def plan_paint(existing, day, track, s, e, block, new_id=None):
    """
    Work out how to fill slots s..e-1 of one day/track.

    existing: that day/track's blocks (dicts with id, date, track, start, end,
              label, category_id).
    block:    {"label", "category_id"} to paint, or None to clear the slots.

    Overlapped blocks are trimmed or split; the new block merges with touching
    blocks that have the same label and category.

    Returns (ops, affected): ops are ("upsert", entry) / ("delete", id) tuples,
    affected are existing blocks with a different label/category that get
    trimmed, split or removed (i.e. data that would be overwritten).
    """
    ops, affected = [], []
    for en in existing:
        es, ee = slot_of(en["start"]), slot_of(en["end"])
        if ee <= s or es >= e:
            continue
        same = block and en["label"] == block["label"] and en["category_id"] == block["category_id"]
        if not same:
            affected.append(en)
        left, right = es < s, ee > e
        if left:
            ops.append(("upsert", {**en, "end": slot_time(s)}))
        if right:
            ops.append(("upsert", {**en, "id": uuid.uuid4().hex if left else en["id"], "start": slot_time(e)}))
        if not left and not right:
            ops.append(("delete", en["id"]))

    if block:
        # Look at the state after trimming to find blocks to merge with.
        after = {en["id"]: en for en in existing}
        for kind, val in ops:
            if kind == "upsert":
                after[val["id"]] = val
            else:
                after.pop(val, None)
        ns, ne = s, e
        for en in list(after.values()):
            if en["label"] != block["label"] or en["category_id"] != block["category_id"]:
                continue
            if slot_of(en["end"]) == ns:
                ns = slot_of(en["start"])
                ops.append(("delete", en["id"]))
            elif slot_of(en["start"]) == ne:
                ne = slot_of(en["end"])
                ops.append(("delete", en["id"]))
        ops.append(("upsert", {
            "id": new_id or uuid.uuid4().hex, "date": day, "track": track,
            "start": slot_time(ns), "end": slot_time(ne),
            "label": block["label"], "category_id": block["category_id"], "details": block.get("details"),
        }))
    return ops, affected


BLOCK_COLS = 'id, date, track, start, "end", label, category_id, details'


def blocks_for(conn, day, track):
    conn.row_factory = sqlite3.Row
    rows = conn.execute(
        f"SELECT {BLOCK_COLS} FROM tt_entries WHERE date = ? AND track = ?",
        (day, track),
    ).fetchall()
    conn.row_factory = None
    return [dict(r) for r in rows]


def apply_block_ops(conn, ops):
    for kind, val in ops:
        if kind == "delete":
            conn.execute("DELETE FROM tt_entries WHERE id = ?", (val,))
        else:
            conn.execute(
                f"INSERT OR REPLACE INTO tt_entries ({BLOCK_COLS}) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (val["id"], val["date"], val["track"], val["start"], val["end"], val["label"], val["category_id"],
                 val.get("details")),
            )


def preview_paint(day, track, s, e, block, exclude=None):
    """What painting would overwrite (Outlook events included), without changing anything."""
    with db() as conn:
        existing = [b for b in blocks_for(conn, day, track) if b["id"] != exclude]
        if track == "plan":
            existing += [_as_block(r) for r in _visible_outlook(conn, day, s, e)]
        return plan_paint(existing, day, track, s, e, block)[1]


def paint(day, track, s, e, block, new_id=None, conn=None):
    """
    Fill (or clear, when block is None) slots s..e-1. Outlook events in the way are
    first turned into the user's own blocks, so they're trimmed like any other.
    Returns the blocks it overwrote.
    """
    if conn is None:
        with db() as conn:
            return paint(day, track, s, e, block, new_id, conn)
    if track == "plan":
        for row in _visible_outlook(conn, day, s, e):
            _detach(conn, row)
    ops, affected = plan_paint(blocks_for(conn, day, track), day, track, s, e, block, new_id)
    apply_block_ops(conn, ops)
    return affected


def get_block(block_id):
    with db() as conn:
        conn.row_factory = sqlite3.Row
        row = conn.execute(
            f"SELECT {BLOCK_COLS} FROM tt_entries WHERE id = ?", (block_id,)
        ).fetchone()
    return dict(row) if row else None


def set_block_label(block_id, label, category_id, details=None):
    with db() as conn:
        conn.execute("UPDATE tt_entries SET label = ?, category_id = ?, details = ? WHERE id = ?",
                     (label, category_id, details, block_id))


def move_block(block_id, day, track, s, e):
    """Move and/or resize a block to slots s..e-1 of a day/track (dragging it in the grid).
    It keeps its id, label, category and details; whatever it lands on is trimmed, like painting."""
    with db() as conn:
        conn.row_factory = sqlite3.Row
        row = conn.execute(f"SELECT {BLOCK_COLS} FROM tt_entries WHERE id = ?", (block_id,)).fetchone()
        conn.row_factory = None
        if not row or not 0 <= s < e <= SLOTS:
            return None
        conn.execute("DELETE FROM tt_entries WHERE id = ?", (block_id,))
        paint(day, track, s, e, {"label": row["label"], "category_id": row["category_id"], "details": row["details"]},
              new_id=block_id, conn=conn)
    return dict(row)


def delete_block(block_id):
    with db() as conn:
        conn.execute("DELETE FROM tt_entries WHERE id = ?", (block_id,))


def blocks_between(first, last, track=None):
    """Timetable blocks between two ISO dates (inclusive), ordered by day/track/time."""
    sql = f"SELECT {BLOCK_COLS} FROM tt_entries WHERE date BETWEEN ? AND ?"
    params = [first, last]
    if track:
        sql += " AND track = ?"
        params.append(track)
    rows = _read(sql, params).to_dict("records")
    return sorted(rows, key=lambda r: (r["date"], r["track"], slot_of(r["start"])))


def upsert_blocks(blocks):
    """Save blocks sent by the grid (popover edits). Idempotent."""
    with db() as conn:
        apply_block_ops(conn, [("upsert", b) for b in blocks])


# ---------------------------------------------------------------------------
# Timetable: imported Outlook events
#
# Every sync puts all events on the timetable; the user can then remove an
# occurrence (hidden) or change it, which turns it into their own block
# ("detached": a tt_entries copy with id "ol:<uid>", and the occurrence hidden).
# Nothing is ever written back to Outlook.
# ---------------------------------------------------------------------------

def replace_outlook(rows):
    """Swap in a fresh set of Outlook events (dicts with the tt_outlook columns)."""
    with db() as conn:
        conn.execute("DELETE FROM tt_outlook")
        conn.executemany(
            'INSERT OR REPLACE INTO tt_outlook (uid, date, start, "end", title, location, all_day, exact, description, teams) '
            "VALUES (:uid, :date, :start, :end, :title, :location, :all_day, :exact, :description, :teams)",
            [{"description": None, "teams": 0, **r} for r in rows],
        )
    if any(r.get("teams") for r in rows):
        teams_category()          # made here, so it already exists when an event is shown or edited


def outlook_between(first, last):
    """Visible Outlook events between two ISO dates (inclusive), timed ones in time order."""
    rows = _read(f"SELECT {OUTLOOK_COLS} FROM tt_outlook WHERE date BETWEEN ? AND ? "
                 "AND uid NOT IN (SELECT uid FROM tt_outlook_hidden)", (first, last)).to_dict("records")
    return sorted(rows, key=lambda r: (r["date"], r["all_day"] == 0, slot_of(r["start"]) if r["start"] else -1))


OUTLOOK_COLS = 'uid, date, start, "end", title, location, all_day, exact, description, teams'


def _visible_outlook(conn, day, s=0, e=None):
    """Visible timed Outlook events on a timetable day overlapping slots s..e-1 (e: the day's end)."""
    e = SLOTS if e is None else e
    conn.row_factory = sqlite3.Row
    rows = conn.execute(
        f"SELECT {OUTLOOK_COLS} FROM tt_outlook WHERE date = ? AND all_day = 0 "
        "AND uid NOT IN (SELECT uid FROM tt_outlook_hidden)", (day,)).fetchall()
    conn.row_factory = None
    return [dict(r) for r in rows if slot_of(r["start"]) < e and slot_of(r["end"]) > s]


def outlook_details(row):
    """Location and description of an Outlook event as one short text."""
    parts = [f"Location: {row['location']}" if row.get("location") else None, row.get("description")]
    return "\n".join(p for p in parts if p) or None


def _as_block(row):
    """An Outlook event in the shape of one of the user's blocks (as it would be once detached)."""
    return {"id": f"ol:{row['uid']}", "date": row["date"], "track": "plan", "start": row["start"],
            "end": row["end"], "label": row["title"], "category_id": outlook_category(row["title"], row.get("teams")),
            "details": outlook_details(row)}


def _detach(conn, row):
    conn.execute("INSERT OR IGNORE INTO tt_outlook_hidden VALUES (?)", (row["uid"],))
    apply_block_ops(conn, [("upsert", _as_block(row))])
    return f"ol:{row['uid']}"


def get_outlook(uid):
    """One visible Outlook event, or None."""
    with db() as conn:
        conn.row_factory = sqlite3.Row
        row = conn.execute(f"SELECT {OUTLOOK_COLS} FROM tt_outlook WHERE uid = ? "
                           "AND uid NOT IN (SELECT uid FROM tt_outlook_hidden)", (uid,)).fetchone()
    return dict(row) if row else None


def hide_outlook(uid):
    """Remove an Outlook occurrence from the timetable (it stays in Outlook)."""
    with db() as conn:
        conn.execute("INSERT OR IGNORE INTO tt_outlook_hidden VALUES (?)", (uid,))


def detach_outlook(uid):
    """Turn an Outlook occurrence into the user's own block; returns its block id (or None)."""
    with db() as conn:
        conn.row_factory = sqlite3.Row
        row = conn.execute(f"SELECT {OUTLOOK_COLS} FROM tt_outlook WHERE uid = ?", (uid,)).fetchone()
        conn.row_factory = None
        if row is None or row["all_day"]:
            return None
        if get_block_in(conn, f"ol:{uid}"):
            return f"ol:{uid}"                       # already detached
        return _detach(conn, dict(row))


def get_block_in(conn, block_id):
    return conn.execute("SELECT 1 FROM tt_entries WHERE id = ?", (block_id,)).fetchone() is not None


def outlook_signature():
    """A cheap fingerprint of tt_outlook, to tell whether a sync changed anything."""
    with db() as conn:
        return conn.execute(
            'SELECT COUNT(*), TOTAL(LENGTH(uid || date || COALESCE(start, \'\') || COALESCE("end", \'\') || title)), '
            "GROUP_CONCAT(uid || COALESCE(start, '') || title, '|') FROM tt_outlook"
        ).fetchone()


# Microsoft Teams meetings from Outlook get their own colour.
TEAMS_CATEGORY = ("teams", "Teams meeting", "#FFD60A", "Work")


def teams_category():
    """The Teams-meeting category, created (yellow, under Work) the first time it's needed."""
    return _builtin_category(TEAMS_CATEGORY)


def outlook_category(title, teams=False):
    """
    Category for Outlook events: a keyword rule, the Teams category for Teams meetings, then
    settings.json "outlook_category" (set by asking Claude),
    else the default, else the first category.
    """
    rule = rule_category(title)
    if rule:
        return rule
    if teams:
        return teams_category()
    wanted = load_settings().get("outlook_category") or DEFAULT_OUTLOOK_CATEGORY
    ids = list(load_categories()["id"])
    return wanted if wanted in ids else (ids[0] if ids else wanted)


def free_runs(day, first=0, last=None):
    """
    Free stretches of a day's Plan between slots first..last-1, as [(start, end)]
    slot pairs: no block of the user's and no (visible, timed) Outlook event in them.
    """
    last = SLOTS if last is None else last
    busy = [False] * SLOTS
    for b in blocks_between(day, day, "plan"):
        for i in range(slot_of(b["start"]), min(slot_of(b["end"]), SLOTS)):
            busy[i] = True
    for ev in outlook_between(day, day):
        if not ev["all_day"]:
            for i in range(slot_of(ev["start"]), min(slot_of(ev["end"]), SLOTS)):
                busy[i] = True
    runs, start = [], None
    for i in range(first, last + 1):
        free = i < last and not busy[i]
        if free and start is None:
            start = i
        elif not free and start is not None:
            runs.append((start, i))
            start = None
    return runs


def outlook_overlaps(day, s, e):
    """Visible timed Outlook events on that timetable day covering any of slots s..e-1."""
    return [r for r in outlook_between(day, day)
            if not r["all_day"] and slot_of(r["start"]) < e and slot_of(r["end"]) > s]


# ---------------------------------------------------------------------------
# Periods, and to-dos for a day, a week (Monday to Sunday) or a month.
#
# Each to-do (and each goal, below) belongs to one period, identified by its
# first day (period_start); the period maths here is shared by both.
# Repeating to-dos get a fresh unticked copy when a new period starts (roll_todos).
# "Today" is the date in the user's time zone (local_today, see "Time zone" above).
# ---------------------------------------------------------------------------

TODO_PERIODS = ("daily", "weekly", "monthly")
# New to-dos in these lists repeat unless told otherwise: a weekly to-do comes back,
# unticked, every Monday (right-click → Repeat turns it off for one).
REPEAT_BY_DEFAULT = ("weekly",)
TODO_COLS = 'id, title, notes, period, period_start, done, done_at, "repeat", ord, created_at'
TODO_DETAILS = "due, place, category_id, minutes, group_id, off_timetable"   # set on the To-dos page
TODO_SELECT = f"{TODO_COLS}, {TODO_DETAILS}"
TODO_PLACES = ("home", "laptop")
TODO_MINUTES = 30                      # how long a to-do takes when the user didn't say


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


def _todo(row):
    g = dict(row)
    g["done"], g["repeat"] = bool(g["done"]), bool(g["repeat"])
    if "off_timetable" in g:
        g["in_diary"] = not g.pop("off_timetable")
    return g


def todo_due(todo):
    """The day a to-do should be done by: its own date, else the last day of its list's period."""
    if todo.get("due"):
        return date.fromisoformat(todo["due"])
    return end_of_period(todo["period"], date.fromisoformat(todo["period_start"]))


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


def todos_for(period, start):
    """The to-dos of one period, in list order."""
    start = start_of_period(period, start).isoformat()
    with db() as conn:
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            f"SELECT {TODO_SELECT} FROM todos WHERE period = ? AND period_start = ? ORDER BY ord, created_at",
            (period, start),
        ).fetchall()
    return [_todo(r) for r in rows]


def get_todo(todo_id):
    with db() as conn:
        conn.row_factory = sqlite3.Row
        row = conn.execute(f"SELECT {TODO_SELECT} FROM todos WHERE id = ?", (todo_id,)).fetchone()
    return _todo(row) if row else None


def _next_ord(conn, period, start):
    return conn.execute("SELECT COALESCE(MAX(ord) + 1, 0) FROM todos WHERE period = ? AND period_start = ?",
                        (period, start)).fetchone()[0]


def _insert_todo(conn, title, period, start, notes=None, repeat=False, todo_id=None):
    """Add a to-do at the end of its list. Idempotent for a given id (the to-do list replays ops)."""
    todo_id = todo_id or uuid.uuid4().hex
    conn.execute(
        f"INSERT OR IGNORE INTO todos ({TODO_COLS}) VALUES (?, ?, ?, ?, ?, 0, NULL, ?, ?, ?)",
        (todo_id, title, notes, period, start, int(bool(repeat)), _next_ord(conn, period, start),
         stamp()),
    )
    return todo_id


def add_todo(title, period, day, notes=None, repeat=False, todo_id=None, **details):
    """Add a to-do to the period containing `day` (details: due, place, category_id, minutes, in_diary); returns it."""
    title = str(title).strip()
    if not title:
        raise ValueError("A todo needs a title.")
    start = start_of_period(period, day).isoformat()
    with db() as conn:
        todo_id = _insert_todo(conn, title, period, start, notes or None, repeat, todo_id)
    if details:
        update_todo(todo_id, **details)
    return get_todo(todo_id)


def list_for_due(due, today=None):
    """The list a to-do due on `due` belongs in: today's if it's due today or earlier, else this week's."""
    today = today or local_today()
    return "daily" if due is not None and _as_date(due) <= today else "weekly"


def add_detailed_todo(title, due=None, group_id=None, minutes=None, in_diary=True, notes=None):
    """A to-do from the To-dos page: it goes in today's or this week's list, by when it's due."""
    today = local_today()
    return add_todo(title, list_for_due(due, today), today, notes=notes, due=due, group_id=group_id,
                    minutes=minutes, in_diary=in_diary)


TODO_GROUP_COLOURS = ("#60A5FA", "#F472B6", "#34D399", "#FBBF24", "#A78BFA", "#F87171", "#2DD4BF", "#FB923C")


def todo_groups():
    """The user's to-do categories in order: [{id, name, colour}]."""
    with db() as conn:
        rows = conn.execute("SELECT id, name, colour FROM todo_groups ORDER BY ord, name").fetchall()
    return [{"id": r[0], "name": r[1], "colour": r[2]} for r in rows]


def add_todo_group(name, colour=None):
    """Add a to-do category (or return the one already called that); returns it."""
    name = str(name).strip()
    if not name:
        raise ValueError("A category needs a name.")
    with db() as conn:
        row = conn.execute("SELECT id FROM todo_groups WHERE name = ?", (name,)).fetchone()
        if row:
            group_id = row[0]
        else:
            count = conn.execute("SELECT COUNT(*) FROM todo_groups").fetchone()[0]
            group_id = uuid.uuid4().hex[:8]
            conn.execute("INSERT INTO todo_groups VALUES (?, ?, ?, ?)",
                         (group_id, name, colour or TODO_GROUP_COLOURS[count % len(TODO_GROUP_COLOURS)], count))
    return next(g for g in todo_groups() if g["id"] == group_id)


def update_todo_group(group_id, name=None, colour=None):
    with db() as conn:
        if name is not None and str(name).strip():
            conn.execute("UPDATE todo_groups SET name = ? WHERE id = ?", (str(name).strip(), group_id))
        if colour:
            conn.execute("UPDATE todo_groups SET colour = ? WHERE id = ?", (colour, group_id))


def delete_todo_group(group_id):
    """Delete a to-do category; its to-dos stay, with no category."""
    with db() as conn:
        conn.execute("UPDATE todos SET group_id = NULL WHERE group_id = ?", (group_id,))
        conn.execute("DELETE FROM todo_groups WHERE id = ?", (group_id,))


def all_open_todos(today=None):
    """Every unticked to-do in today's and this week's lists, most urgent first (by due day, then list order)."""
    today = today or local_today()
    bring_forward_todos(today)
    todos = todos_for("daily", today) + todos_for("weekly", today)
    return sorted((t for t in todos if not t["done"]), key=lambda t: (todo_due(t), t["period"], t["ord"]))


def done_todos(today=None):
    """Ticked to-dos from today's and this week's lists, most recently ticked first."""
    today = today or local_today()
    todos = todos_for("daily", today) + todos_for("weekly", today)
    return sorted((t for t in todos if t["done"]), key=lambda t: t["done_at"] or "", reverse=True)


TODO_BLOCK, TRAINING_BLOCK = "td:", "tr:"     # ids of blocks Venato puts on the timetable for them
HOME_TODO_PERIODS = ("daily", "weekly")        # the lists on Home (monthly to-dos are no longer used)


def set_todo_done(todo_id, done):
    """Tick or untick a to-do (done_at records when it was ticked). Ticking takes it off the timetable."""
    with db() as conn:
        if done:
            conn.execute("DELETE FROM tt_entries WHERE id = ?", (TODO_BLOCK + todo_id,))
        conn.execute(
            "UPDATE todos SET done = ?, done_at = CASE WHEN ? THEN COALESCE(done_at, ?) END WHERE id = ?",
            (int(bool(done)), int(bool(done)), stamp(), todo_id),
        )


def update_todo(todo_id, **changes):
    """
    Change a to-do's title, notes, repeat flag, or details (due, group_id, minutes, in_diary). Changing when, how long or the category frees its timetable slot, so it's placed
    again; taking it out of the diary removes its block.
    """
    if "in_diary" in changes:
        changes["off_timetable"] = int(not changes.pop("in_diary"))
    if changes.get("due") is not None:
        changes["due"] = _as_date(changes["due"]).isoformat()
    if "place" in changes and changes["place"] not in TODO_PLACES:
        changes["place"] = None
    if "minutes" in changes:
        changes["minutes"] = int(changes["minutes"]) if changes["minutes"] else None
    replace = {"due", "category_id", "minutes", "off_timetable"} & set(changes)
    fields = {k: v for k, v in changes.items()
              if k in ("title", "notes", "repeat", "due", "place", "category_id", "minutes", "group_id", "off_timetable")}
    if "title" in fields:
        fields["title"] = str(fields["title"]).strip()
        if not fields["title"]:
            raise ValueError("A todo needs a title.")
    if "notes" in fields:
        fields["notes"] = (str(fields["notes"]).strip() if fields["notes"] is not None else "") or None
    if "repeat" in fields:
        fields["repeat"] = int(bool(fields["repeat"]))
    if not fields:
        return
    sets = ", ".join(f'"{k}" = ?' for k in fields)
    with db() as conn:
        conn.execute(f"UPDATE todos SET {sets} WHERE id = ?", (*fields.values(), todo_id))
        if replace:
            conn.execute("DELETE FROM tt_entries WHERE id = ?", (TODO_BLOCK + todo_id,))
        if fields.get("due"):
            # Due today or earlier: today's list; later: this week's.
            today = local_today()
            period = list_for_due(fields["due"], today)
            conn.execute("UPDATE todos SET period = ?, period_start = ? WHERE id = ? AND period IN ('daily', 'weekly')",
                         (period, start_of_period(period, today).isoformat(), todo_id))
        if "title" in fields:
            conn.execute("UPDATE tt_entries SET label = ? WHERE id = ?", (fields["title"], TODO_BLOCK + todo_id))


def move_target(todo, period, today=None):
    """
    Where a to-do lands when moved to another kind of period: the period containing
    today if its current period includes today, otherwise its own first day.
    """
    today = today or local_today()
    start = date.fromisoformat(todo["period_start"])
    anchor = today if start <= today <= end_of_period(todo["period"], start) else start
    return start_of_period(period, anchor)


def move_todo(todo_id, period, today=None):
    """Move a to-do to another kind of period (to the end of that list). Returns the new period start."""
    todo = get_todo(todo_id)
    if not todo:
        return None
    start = move_target(todo, period, today).isoformat()
    with db() as conn:
        conn.execute("UPDATE todos SET period = ?, period_start = ?, ord = ? WHERE id = ?",
                     (period, start, _next_ord(conn, period, start), todo_id))
        conn.execute("DELETE FROM tt_entries WHERE id = ?", (TODO_BLOCK + todo_id,))   # re-placed for its new list
    return start


def delete_todo(todo_id):
    with db() as conn:
        conn.execute("DELETE FROM todos WHERE id = ?", (todo_id,))
        conn.execute("DELETE FROM tt_entries WHERE id = ?", (TODO_BLOCK + todo_id,))


def reorder_todos(ids):
    """Put to-dos in this order (ids of one list, first to last)."""
    with db() as conn:
        conn.executemany("UPDATE todos SET ord = ? WHERE id = ?", [(i, gid) for i, gid in enumerate(ids)])


def _titles(conn, period, start):
    rows = conn.execute("SELECT lower(title) FROM todos WHERE period = ? AND period_start = ?", (period, start))
    return {r[0] for r in rows}


def roll_todos(today=None):
    """
    Give every repeating to-do an unticked copy in the current period, once per
    period (todo_rollover remembers the last one done, so a copy the user deletes
    stays deleted). A to-do repeats if the latest to-do with its title in an earlier
    period has repeat on. Titles already in the current period are never doubled.
    Returns how many copies were made.
    """
    today = today or local_today()
    made = 0
    with db() as conn:
        for period in TODO_PERIODS:
            start = start_of_period(period, today).isoformat()
            done = conn.execute("SELECT period_start FROM todo_rollover WHERE period = ?", (period,)).fetchone()
            if done and done[0] >= start:
                continue
            latest = {}
            for title, notes, repeat in conn.execute(
                'SELECT title, notes, "repeat" FROM todos WHERE period = ? AND period_start < ? '
                "ORDER BY period_start DESC, ord",
                (period, start),
            ):
                latest.setdefault(title.lower(), (title, notes, repeat))
            existing = _titles(conn, period, start)
            for key, (title, notes, repeat) in latest.items():
                if repeat and key not in existing:
                    _insert_todo(conn, title, period, start, notes, True)
                    made += 1
            conn.execute("INSERT OR REPLACE INTO todo_rollover VALUES (?, ?)", (period, start))
    return made


def carry_over(period, start):
    """Copy a period's unticked to-dos into the next period (skipping titles already there). Returns the count."""
    start = start_of_period(period, start).isoformat()
    nxt = shift_period(period, start, 1).isoformat()
    copied = 0
    with db() as conn:
        existing = _titles(conn, period, nxt)
        rows = conn.execute(
            'SELECT title, notes, "repeat" FROM todos WHERE period = ? AND period_start = ? AND done = 0 ORDER BY ord',
            (period, start),
        ).fetchall()
        for title, notes, repeat in rows:
            if title.lower() not in existing:
                _insert_todo(conn, title, period, nxt, notes, repeat)
                existing.add(title.lower())
                copied += 1
    return copied


def todos_progress(period, start):
    """(done, total) for one period."""
    todos = todos_for(period, start)
    return sum(g["done"] for g in todos), len(todos)


def load_todos():
    """Every to-do, for export: one row each, oldest period first."""
    return _read(f"SELECT {TODO_COLS} FROM todos ORDER BY period_start, period, ord")


def save_todos(df, replace=False):
    """
    Import to-dos (the export's columns; only title and period are required).
    Rows with an id that already exists update that to-do; replace=True wipes all to-dos first.
    Returns how many rows were imported.
    """
    count = 0
    with db() as conn:
        if replace:
            conn.execute("DELETE FROM todos")
            conn.execute("DELETE FROM todo_rollover")
        for row in df.to_dict("records"):
            title = _clean(row.get("title"), str)
            period = (_clean(row.get("period"), str) or "").strip().lower()
            if not title or period not in TODO_PERIODS:
                continue
            day = _clean(row.get("period_start"), str)
            start = start_of_period(period, pd.to_datetime(day).date() if day else local_today()).isoformat()
            done = _is_ticked(row.get("done"))
            ord_ = _clean(row.get("ord"), int)
            conn.execute(
                f"INSERT OR REPLACE INTO todos ({TODO_COLS}) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (_clean(row.get("id"), str) or uuid.uuid4().hex, title.strip(), _clean(row.get("notes"), str),
                 period, start, int(done), _clean(row.get("done_at"), str) if done else None,
                 int(_is_ticked(row.get("repeat"))),
                 _next_ord(conn, period, start) if ord_ is None else ord_,
                 _clean(row.get("created_at"), str) or stamp()),
            )
            count += 1
    return count


# ---------------------------------------------------------------------------
# Goals: measurable targets for a month or a year ("Gym 12 sessions").
#
# Progress is either a number the user updates (`progress`), or, when the goal
# is linked to a habit, the number of days that habit was ticked in the period.
# ---------------------------------------------------------------------------

GOAL_PERIODS = ("monthly", "yearly")
GOAL_COLS = "id, title, period, period_start, target, unit, progress, habit_id, ord, created_at"
GOAL_SELECT = GOAL_COLS + ", kind, done_at, category"
GOAL_KINDS = ("simple", "target")   # simple: something to achieve (done / not yet); target: reach a number


def _num(x):
    """12.0 -> 12, so whole numbers read naturally."""
    return int(x) if float(x).is_integer() else float(x)


def _with_value(conn, row):
    """A goal row plus `value` (its current progress) and `habit` (the linked habit's name, or None)."""
    g = dict(row)
    g["target"], g["progress"] = _num(g["target"]), _num(g["progress"])
    g["habit"] = None
    g["value"] = g["progress"]
    g["done"] = g["kind"] == "simple" and g["progress"] >= 1
    if g["habit_id"] is not None:
        name = conn.execute("SELECT name FROM habits WHERE id = ?", (g["habit_id"],)).fetchone()
        end = end_of_period(g["period"], g["period_start"]).isoformat()
        g["habit"] = name[0] if name else None
        g["value"] = conn.execute(
            "SELECT COUNT(*) FROM habit_log WHERE habit_id = ? AND date BETWEEN ? AND ?",
            (g["habit_id"], g["period_start"], end),
        ).fetchone()[0]
    return g


def goals_in(period, start):
    """The goals of one month or year, in list order, each with its current `value`."""
    start = start_of_period(period, start).isoformat()
    with db() as conn:
        conn.row_factory = sqlite3.Row
        rows = conn.execute(f"SELECT {GOAL_SELECT} FROM goals WHERE period = ? AND period_start = ? ORDER BY ord, created_at",
                            (period, start)).fetchall()
        return [_with_value(conn, r) for r in rows]


def get_goal(goal_id):
    with db() as conn:
        conn.row_factory = sqlite3.Row
        row = conn.execute(f"SELECT {GOAL_SELECT} FROM goals WHERE id = ?", (goal_id,)).fetchone()
        return _with_value(conn, row) if row else None


def _check_target(target):
    target = float(target)
    if target <= 0:
        raise ValueError("A goal's target must be more than 0.")
    return target


def add_goal(title, period, day, target=1, unit=None, habit_id=None, goal_id=None, kind="target"):
    """
    Add a goal to the month or year containing `day`; returns it.
    kind "simple": something to achieve ("Sub 19:30 5 km"), ticked off once (no target, unit or habit).
    """
    if kind not in GOAL_KINDS:
        raise ValueError(f"A goal's kind is simple or target, not {kind}.")
    if kind == "simple":
        target, unit, habit_id = 1, None, None
    title = str(title).strip()
    if not title:
        raise ValueError("A goal needs a title.")
    if period not in GOAL_PERIODS:
        raise ValueError(f"Goals are monthly or yearly, not {period}.")
    start = start_of_period(period, day).isoformat()
    goal_id = goal_id or uuid.uuid4().hex
    with db() as conn:
        conn.execute(
            f"INSERT OR IGNORE INTO goals ({GOAL_COLS}, kind) VALUES (?, ?, ?, ?, ?, ?, 0, ?, "
            "(SELECT COALESCE(MAX(ord) + 1, 0) FROM goals WHERE period = ? AND period_start = ?), ?, ?)",
            (goal_id, title, period, start, _check_target(target), (unit or "").strip() or None, habit_id,
             period, start, stamp(), kind),
        )
    return get_goal(goal_id)




def update_goal(goal_id, title=KEEP, target=KEEP, unit=KEEP, habit_id=KEEP, kind=KEEP):
    """Change a goal's title, target, unit, linked habit (habit_id=None unlinks it) or kind."""
    fields = {}
    if kind is not KEEP:
        if kind not in GOAL_KINDS:
            raise ValueError(f"A goal's kind is simple or target, not {kind}.")
        fields["kind"] = kind
        if kind == "simple":                      # a number goal becoming done / not yet
            target, unit, habit_id = 1, None, None
            fields["progress"], fields["done_at"] = 0, None
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
    if fields:
        with db() as conn:
            conn.execute(f"UPDATE goals SET {', '.join(f'{k} = ?' for k in fields)} WHERE id = ?",
                         (*fields.values(), goal_id))


def set_goal_done(goal_id, done=True):
    """Tick off (or untick) a simple goal."""
    with db() as conn:
        conn.execute("UPDATE goals SET progress = ?, done_at = ? WHERE id = ?",
                     (1 if done else 0, stamp() if done else None, goal_id))


def set_goal_progress(goal_id, value):
    """Set a goal's hand-updated progress (never below 0)."""
    with db() as conn:
        conn.execute("UPDATE goals SET progress = MAX(0, ?) WHERE id = ?", (float(value), goal_id))


GOAL_CATEGORY_COLOURS = ("#F97316", "#EC4899", "#22C55E", "#3B82F6", "#A855F7", "#EAB308", "#14B8A6", "#EF4444")


def goal_categories():
    """{name: colour} of the user's goal categories (e.g. Work, Side project), in the order they were made."""
    return dict(load_settings().get("goal_categories", {}))


def set_goal_category(goal_id, name):
    """Put a goal in a category (created, with the next colour, if it's new); None or '' takes it out."""
    name = (str(name).strip() if name else "") or None
    if name:
        cats = goal_categories()
        match = next((c for c in cats if c.lower() == name.lower()), None)
        if match:
            name = match
        else:
            cats[name] = GOAL_CATEGORY_COLOURS[len(cats) % len(GOAL_CATEGORY_COLOURS)]
            save_settings(goal_categories=cats)
    with db() as conn:
        conn.execute("UPDATE goals SET category = ? WHERE id = ?", (name, goal_id))


def set_goal_category_colour(name, colour):
    cats = goal_categories()
    if name in cats:
        cats[name] = colour
        save_settings(goal_categories=cats)


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


def load_goals():
    """Every goal, for export (the linked habit by name, so the CSV makes sense on its own)."""
    return _read(f"""SELECT g.id, g.title, g.period, g.period_start, g.target, g.unit, g.progress,
                            h.name AS habit, g.ord, g.created_at, g.kind, g.done_at, g.category
                     FROM goals g LEFT JOIN habits h ON h.id = g.habit_id
                     ORDER BY g.period_start, g.period, g.ord""")


def save_goals(df, replace=False):
    """
    Import goals (the export's columns; title, period and target are required).
    A habit name that doesn't exist is ignored (the goal is then updated by hand).
    Rows with an existing id update that goal; replace=True wipes all goals first. Returns the count.
    """
    count = 0
    with db() as conn:
        if replace:
            conn.execute("DELETE FROM goals")
        habits = {name.lower(): hid for hid, name in conn.execute("SELECT id, name FROM habits")}
        for row in df.to_dict("records"):
            title = _clean(row.get("title"), str)
            period = (_clean(row.get("period"), str) or "").strip().lower()
            kind = (_clean(row.get("kind"), str) or "target").strip().lower()
            kind = kind if kind in GOAL_KINDS else "target"
            target = 1.0 if kind == "simple" else _clean(row.get("target"), float)
            if not title or period not in GOAL_PERIODS or not target or target <= 0:
                continue
            day = _clean(row.get("period_start"), str)
            start = start_of_period(period, pd.to_datetime(day).date() if day else local_today()).isoformat()
            habit = _clean(row.get("habit"), str)
            ord_ = _clean(row.get("ord"), int)
            conn.execute(
                f"INSERT OR REPLACE INTO goals ({GOAL_SELECT}) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (_clean(row.get("id"), str) or uuid.uuid4().hex, title.strip(), period, start, target,
                 _clean(row.get("unit"), str), max(0.0, _clean(row.get("progress"), float) or 0.0),
                 habits.get(habit.strip().lower()) if habit else None, count if ord_ is None else ord_,
                 _clean(row.get("created_at"), str) or stamp(),
                 kind, _clean(row.get("done_at"), str), _clean(row.get("category"), str)),
            )
            count += 1
    return count


# ---------------------------------------------------------------------------
# Network: people, their groups (colours) and who knows whom.
#
# Links are undirected and stored once, with the smaller id first (net_links
# has CHECK (a < b)), so "A knows B" and "B knows A" are the same row.
# ---------------------------------------------------------------------------

PERSON_COLS = ("id", "name", "description", "works_for", "group_id", "created_at")


def net_groups():
    """[{id, name, colour, parent_id}] in order: each group's sub-groups follow it."""
    with db() as conn:
        rows = conn.execute("SELECT id, name, colour, parent_id FROM net_groups ORDER BY ord, name").fetchall()
    groups = [dict(zip(("id", "name", "colour", "parent_id"), r)) for r in rows]
    ids = {g["id"] for g in groups}
    out = []

    def walk(parent):
        for g in groups:
            if g["parent_id"] == parent or (parent is None and g["parent_id"] not in ids):
                out.append(g)
                walk(g["id"])
    walk(None)
    return out


def group_path(group_id, groups=None):
    """"Northfield › Physics Society" for a sub-group, or just the name."""
    by_id = {g["id"]: g for g in (groups or net_groups())}
    names, gid = [], group_id
    while gid in by_id and len(names) < 10:
        names.append(by_id[gid]["name"])
        gid = by_id[gid]["parent_id"]
    return " › ".join(reversed(names))


def _descendants(conn, group_id):
    """Ids of a group's sub-groups, their sub-groups, and so on."""
    found, todo = set(), [group_id]
    while todo:
        kids = [r[0] for r in conn.execute(
            f"SELECT id FROM net_groups WHERE parent_id IN ({','.join('?' * len(todo))})", todo)]
        todo = [k for k in kids if k not in found]
        found.update(todo)
    return found


def find_net_group(name):
    """A group's id by name (any case), or None. Group names are unique."""
    with db() as conn:
        row = conn.execute("SELECT id FROM net_groups WHERE name = ? COLLATE NOCASE", (str(name).strip(),)).fetchone()
    return row[0] if row else None


def add_net_group(name, colour=None, parent_id=None):
    """A new group (inside `parent_id`, if given). Sub-groups take their parent's colour unless given one."""
    name = str(name).strip()
    if not name:
        raise ValueError("A group needs a name.")
    gid = uuid.uuid4().hex[:8]
    with db() as conn:
        if not colour and parent_id:
            row = conn.execute("SELECT colour FROM net_groups WHERE id = ?", (parent_id,)).fetchone()
            colour = row[0] if row else None
        conn.execute("INSERT INTO net_groups (id, name, colour, ord, parent_id) "
                     "VALUES (?, ?, ?, (SELECT COALESCE(MAX(ord) + 1, 0) FROM net_groups), ?)",
                     (gid, name, (colour or "#8B8D98").upper(), parent_id))
    return gid


NO_CHANGE = object()   # update_net_group / update_person: leave this field as it is


def update_net_group(group_id, name=None, colour=None, parent_id=NO_CHANGE):
    """Rename, recolour or move a group (parent_id=None puts it at the top level)."""
    fields = {}
    if name is not None:
        fields["name"] = str(name).strip()
        if not fields["name"]:
            raise ValueError("A group needs a name.")
    if colour is not None:
        fields["colour"] = colour.upper()
    with db() as conn:
        if parent_id is not NO_CHANGE:
            if parent_id == group_id or parent_id in _descendants(conn, group_id):
                raise ValueError("A group can't sit inside itself or one of its own sub-groups.")
            fields["parent_id"] = parent_id
        if fields:
            conn.execute(f"UPDATE net_groups SET {', '.join(f'{k} = ?' for k in fields)} WHERE id = ?",
                         (*fields.values(), group_id))


def delete_net_group(group_id):
    """Remove a group. Its sub-groups and people move up to the group it was inside (or the top level)."""
    with db() as conn:
        row = conn.execute("SELECT parent_id FROM net_groups WHERE id = ?", (group_id,)).fetchone()
        if not row:
            return
        conn.execute("UPDATE net_groups SET parent_id = ? WHERE parent_id = ?", (row[0], group_id))
        conn.execute("UPDATE net_people SET group_id = ? WHERE group_id = ?", (row[0], group_id))
        conn.execute("DELETE FROM net_groups WHERE id = ?", (group_id,))


def net_people():
    """Everyone, by name."""
    with db() as conn:
        rows = conn.execute(f"SELECT {', '.join(PERSON_COLS)} FROM net_people ORDER BY name COLLATE NOCASE").fetchall()
    return [dict(zip(PERSON_COLS, r)) for r in rows]


def get_person(person_id):
    with db() as conn:
        row = conn.execute(f"SELECT {', '.join(PERSON_COLS)} FROM net_people WHERE id = ?", (person_id,)).fetchone()
    return dict(zip(PERSON_COLS, row)) if row else None


def find_people(name):
    """People whose name matches exactly (any case), else whose name contains `name`."""
    want = str(name).strip().lower()
    everyone = net_people()
    return [p for p in everyone if p["name"].lower() == want] or [p for p in everyone if want in p["name"].lower()]


def _person_fields(name=None, description=None, works_for=None):
    out = {}
    if name is not None:
        out["name"] = str(name).strip()
        if not out["name"]:
            raise ValueError("A person needs a name.")
    if description is not None:
        out["description"] = str(description).strip() or None
    if works_for is not None:
        out["works_for"] = str(works_for).strip() or None
    return out


def add_person(name, description=None, works_for=None, group_id=None, person_id=None):
    """Add someone to the network; returns them."""
    fields = _person_fields(name, description, works_for)
    person_id = person_id or uuid.uuid4().hex
    with db() as conn:
        conn.execute(f"INSERT INTO net_people ({', '.join(PERSON_COLS)}) VALUES (?, ?, ?, ?, ?, ?)",
                     (person_id, fields["name"], fields.get("description"), fields.get("works_for"), group_id,
                      stamp()))
    return get_person(person_id)


KEEP_GROUP = NO_CHANGE


def update_person(person_id, name=None, description=None, works_for=None, group_id=KEEP_GROUP):
    """Change any of name, description, works_for (None = leave as is; "" = clear) and group (None = no group)."""
    fields = _person_fields(name, description, works_for)
    if group_id is not KEEP_GROUP:
        fields["group_id"] = group_id
    if fields:
        with db() as conn:
            conn.execute(f"UPDATE net_people SET {', '.join(f'{k} = ?' for k in fields)} WHERE id = ?",
                         (*fields.values(), person_id))


def delete_person(person_id):
    """Remove someone (and their connections)."""
    with db() as conn:
        conn.execute("DELETE FROM net_people WHERE id = ?", (person_id,))


def _pair(a, b):
    if a == b:
        raise ValueError("Someone can't be connected to themselves.")
    return (a, b) if a < b else (b, a)


def link_people(a, b, reason=None):
    """Connect two people (or update why they're connected)."""
    a, b = _pair(a, b)
    with db() as conn:
        conn.execute("INSERT INTO net_links VALUES (?, ?, ?) ON CONFLICT(a, b) DO UPDATE SET reason = excluded.reason",
                     (a, b, (str(reason).strip() or None) if reason else None))


def unlink_people(a, b):
    a, b = _pair(a, b)
    with db() as conn:
        conn.execute("DELETE FROM net_links WHERE a = ? AND b = ?", (a, b))


def net_links():
    """[{a, b, reason}] for every connection."""
    with db() as conn:
        rows = conn.execute("SELECT a, b, reason FROM net_links").fetchall()
    return [{"a": a, "b": b, "reason": r} for a, b, r in rows]


def add_interaction(person_id, note, day):
    """Log a time the user saw or spoke to someone; returns its id."""
    note = str(note).strip()
    if not note:
        raise ValueError("Say what happened.")
    iid = uuid.uuid4().hex
    with db() as conn:
        conn.execute("INSERT INTO net_interactions VALUES (?, ?, ?, ?, ?)",
                     (iid, person_id, _as_date(day).isoformat(), note, stamp()))
    return iid


def interactions_of(person_id, limit=None):
    """[{id, date, note}] for one person, newest first."""
    with db() as conn:
        rows = conn.execute("SELECT id, date, note FROM net_interactions WHERE person_id = ? "
                            "ORDER BY date DESC, created_at DESC" + (f" LIMIT {int(limit)}" if limit else ""),
                            (person_id,)).fetchall()
    return [{"id": i, "date": d, "note": n} for i, d, n in rows]


def interactions_between(first, last):
    """[{date, note, person}] logged between two dates (inclusive), oldest first."""
    with db() as conn:
        rows = conn.execute(
            "SELECT i.date, i.note, p.name FROM net_interactions i JOIN net_people p ON p.id = i.person_id "
            "WHERE i.date BETWEEN ? AND ? ORDER BY i.date, i.created_at",
            (_as_date(first).isoformat(), _as_date(last).isoformat())).fetchall()
    return [{"date": d, "note": n, "person": p} for d, n, p in rows]


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


def last_interactions():
    """{person_id: date of the latest interaction}."""
    with db() as conn:
        return dict(conn.execute("SELECT person_id, MAX(date) FROM net_interactions GROUP BY person_id").fetchall())


def delete_interaction(interaction_id):
    with db() as conn:
        conn.execute("DELETE FROM net_interactions WHERE id = ?", (interaction_id,))


def connections_of(person_id):
    """[(other person, reason)] for one person, by name."""
    people = {p["id"]: p for p in net_people()}
    out = [(people[l["b"] if l["a"] == person_id else l["a"]], l["reason"])
           for l in net_links() if person_id in (l["a"], l["b"])]
    return sorted(out, key=lambda x: x[0]["name"].lower())


# ---------------------------------------------------------------------------
# Putting to-dos and training on the timetable (autoplan.py decides when)
# ---------------------------------------------------------------------------

TODO_CATEGORY = ("todos", "To-dos", "#B4C7E7", "Life")


def todo_category():
    """The category to-do blocks use, created the first time it's needed."""
    return _builtin_category(TODO_CATEGORY)


def get_category_ids():
    with db() as conn:
        return {r[0] for r in conn.execute("SELECT id FROM tt_categories")}


def slot_start(day, slot):
    """When a timetable slot starts, as a naive local datetime."""
    return datetime.fromisoformat(str(day)) + timedelta(minutes=FIRST_MIN + SLOT_MIN * slot)


def free_slot(day, lo, hi, length=1):
    """The first slot s in lo..hi-length where `length` slots are free of blocks and Outlook events, or None."""
    with db() as conn:
        taken = set()
        for b in blocks_for(conn, day, "plan"):
            taken |= set(range(slot_of(b["start"]), slot_of(b["end"])))
        for ev in _visible_outlook(conn, day):
            taken |= set(range(slot_of(ev["start"]), slot_of(ev["end"])))
    for s in range(max(lo, 0), min(hi, SLOTS) - length + 1):
        if not taken & set(range(s, s + length)):
            return s
    return None


TODO_PAST = "tdx:"       # "tdx:<todo id>:<date>:<start>": where a to-do was, marked done or not done


def _set_event_status(event_id, done):
    with db() as conn:
        if done is None:
            conn.execute("DELETE FROM event_status WHERE id = ?", (event_id,))
        else:
            conn.execute("INSERT OR REPLACE INTO event_status VALUES (?, ?)", (event_id, int(bool(done))))


def clear_event_status(event_id):
    _set_event_status(event_id, None)


def event_statuses():
    """{event id: True (done) / False (not done)}. A ticked training session counts as done, wherever it was ticked."""
    with db() as conn:
        statuses = {i: bool(d) for i, d in conn.execute("SELECT id, done FROM event_status")}
        statuses.update((r[0], True) for r in conn.execute(
            "SELECT block_id FROM training_sessions WHERE done = 1 AND block_id IS NOT NULL"))
    return statuses


def _mark_todo(block_id, done):
    """
    A to-do's slot went by. The slot stays on the timetable as a record of what happened: done
    ticks the to-do off; not done leaves it open, so it gets a new slot (autoplan.py).
    """
    block = get_block(block_id)
    if block is None or done is None:
        return
    todo_id = block_id[len(TODO_BLOCK):]
    past_id = f"{TODO_PAST}{todo_id}:{block['date']}:{block['start']}"
    delete_block(block_id)
    put_block({**block, "id": past_id})
    _set_event_status(past_id, done)
    if done:
        set_todo_done(todo_id, True)


def mark_event(event_id, done):
    """
    Mark an event whose time has passed: done True, not done False, or None to clear it.
    To-dos and training sessions are updated as well.
    """
    if event_id.startswith(TODO_BLOCK):
        _mark_todo(event_id, done)
        return
    if event_id.startswith(TODO_PAST):
        todo_id = event_id.split(":")[1]
        if get_todo(todo_id):
            set_todo_done(todo_id, bool(done))         # changing your mind: back on the list if it's not done
    elif event_id.startswith(TRAINING_BLOCK):
        with db() as conn:
            row = conn.execute("SELECT id FROM training_sessions WHERE block_id = ?", (event_id,)).fetchone()
        if row:
            update_session(row[0], done=bool(done))
        if done:
            done = None                                # the session itself now says it's done
    _set_event_status(event_id, done)


def slot_clash(block):
    """True if another block or a visible Outlook event overlaps this block."""
    s, e = slot_of(block["start"]), slot_of(block["end"])
    with db() as conn:
        others = [b for b in blocks_for(conn, block["date"], block["track"]) if b["id"] != block["id"]]
        return bool(_visible_outlook(conn, block["date"], s, e)) or             any(slot_of(b["start"]) < e and slot_of(b["end"]) > s for b in others)


def put_block(block):
    """Add or replace one block as it is (no trimming: callers pick free time)."""
    with db() as conn:
        apply_block_ops(conn, [("upsert", block)])


def open_todos(today):
    """Unticked to-dos in today's list and this week's, that the user hasn't taken off the timetable."""
    day, week = today.isoformat(), start_of_period("weekly", today).isoformat()
    with db() as conn:
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            f"SELECT {TODO_SELECT} FROM todos WHERE done = 0 AND off_timetable = 0 AND "
            "((period = 'daily' AND period_start = ?) OR (period = 'weekly' AND period_start = ?)) ORDER BY period, ord",
            (day, week)).fetchall()
    return [_todo(r) for r in rows]


def bring_forward_todos(today):
    """
    Unticked daily to-dos from earlier days move to today, and unticked weekly ones from earlier
    weeks to this week, so a to-do stays until it's done (unless that list already has the title).
    """
    moved = 0
    with db() as conn:
        for period in ("daily", "weekly"):
            start = start_of_period(period, today).isoformat()
            existing = _titles(conn, period, start)
            for tid, title in conn.execute("SELECT id, title FROM todos WHERE period = ? AND period_start < ? "
                                           "AND done = 0 ORDER BY period_start DESC, ord", (period, start)).fetchall():
                if title.lower() in existing:
                    continue
                conn.execute("UPDATE todos SET period_start = ?, ord = ? WHERE id = ?",
                             (start, _next_ord(conn, period, start), tid))
                existing.add(title.lower())
                moved += 1
    return moved


def clear_todo_blocks():
    """Take every to-do off the timetable (the ones waiting for a slot and the done / not done
    records). Returns how many blocks went."""
    with db() as conn:
        return conn.execute("DELETE FROM tt_entries WHERE id LIKE ? OR id LIKE ?",
                            (TODO_BLOCK + "%", TODO_PAST + "%")).rowcount


def taken_off_timetable(block_id):
    """The user deleted an Venato-made block from the timetable: don't put it back automatically."""
    if block_id.startswith(TODO_BLOCK):
        with db() as conn:
            conn.execute("UPDATE todos SET off_timetable = 1 WHERE id = ?", (block_id[len(TODO_BLOCK):],))
    elif block_id.startswith(TRAINING_BLOCK):
        with db() as conn:
            conn.execute("UPDATE training_sessions SET off_timetable = 1, block_id = NULL WHERE block_id = ?", (block_id,))


# ---------------------------------------------------------------------------
# Gym log
# ---------------------------------------------------------------------------

GYM_FIELDS = ("exercise", "sets", "reps", "weight_kg")


def _gym_rows(exercises):
    rows = []
    for i, x in enumerate(exercises):
        name = str(x.get("exercise") or "").strip()
        if not name:
            continue
        num = lambda v, cast: None if v is None or v == "" or (isinstance(v, float) and v != v) else cast(v)
        rows.append((i, name, num(x.get("sets"), int), num(x.get("reps"), int), num(x.get("weight_kg"), float)))
    return rows


def save_gym_session(day, title, exercises, notes=None, session_id=None):
    """Add (or, with session_id, replace) a gym session and its exercises. Returns its id."""
    title = str(title or "").strip() or "Gym"
    session_id = session_id or uuid.uuid4().hex
    with db() as conn:
        conn.execute("INSERT INTO gym_sessions VALUES (?, ?, ?, ?, ?) ON CONFLICT(id) DO UPDATE SET "
                     "date = excluded.date, title = excluded.title, notes = excluded.notes",
                     (session_id, str(day), title, (notes or "").strip() or None,
                      stamp()))
        conn.execute("DELETE FROM gym_exercises WHERE session_id = ?", (session_id,))
        conn.executemany("INSERT INTO gym_exercises (session_id, ord, exercise, sets, reps, weight_kg) "
                         "VALUES (?, ?, ?, ?, ?, ?)", [(session_id, *r) for r in _gym_rows(exercises)])
    return session_id


def gym_sessions(first=None, last=None, limit=None):
    """Gym sessions (newest first), each with its `exercises`."""
    sql, params = "SELECT id, date, title, notes FROM gym_sessions", []
    if first and last:
        sql, params = sql + " WHERE date BETWEEN ? AND ?", [first, last]
    sql += " ORDER BY date DESC, created_at DESC" + (f" LIMIT {int(limit)}" if limit else "")
    with db() as conn:
        sessions = [dict(zip(("id", "date", "title", "notes"), r)) for r in conn.execute(sql, params).fetchall()]
        for s in sessions:
            s["exercises"] = [dict(zip(GYM_FIELDS, r)) for r in conn.execute(
                "SELECT exercise, sets, reps, weight_kg FROM gym_exercises WHERE session_id = ? ORDER BY ord",
                (s["id"],)).fetchall()]
    return sessions


def delete_gym_session(session_id):
    with db() as conn:
        conn.execute("DELETE FROM gym_sessions WHERE id = ?", (session_id,))


def last_lift(exercise):
    """The most recent (sets, reps, weight_kg, date) logged for an exercise (any case), or None."""
    with db() as conn:
        row = conn.execute("SELECT e.sets, e.reps, e.weight_kg, s.date FROM gym_exercises e "
                           "JOIN gym_sessions s ON s.id = e.session_id WHERE lower(e.exercise) = lower(?) "
                           "ORDER BY s.date DESC, s.created_at DESC LIMIT 1", (str(exercise).strip(),)).fetchone()
    return row


# ---------------------------------------------------------------------------
# Journal (the daily log's notes)
# ---------------------------------------------------------------------------

def journal_todo_new(day, period, title):
    """Record that the journal made this to-do; False if it already had (so it isn't added again)."""
    with db() as conn:
        cur = conn.execute("INSERT OR IGNORE INTO journal_todos VALUES (?, ?, ?)", (str(day), period, title.strip()))
        return cur.rowcount == 1


# ---------------------------------------------------------------------------
# Strava (rows made by strava.py)
# ---------------------------------------------------------------------------

STRAVA_COLS = ("id", "date", "start", "name", "sport", "distance_km", "moving_min", "elevation_m", "avg_hr")


def save_strava(rows):
    """Add or update activities (keeping which training session each one ticked off)."""
    with db() as conn:
        for r in rows:
            conn.execute(
                f"INSERT INTO strava_activities ({', '.join(STRAVA_COLS)}) VALUES ({', '.join('?' * len(STRAVA_COLS))}) "
                "ON CONFLICT(id) DO UPDATE SET " + ", ".join(f"{c} = excluded.{c}" for c in STRAVA_COLS[1:]),
                tuple(r.get(c) for c in STRAVA_COLS))


def strava_activities(first=None, last=None, runs_only=False):
    sql = f"SELECT {', '.join(STRAVA_COLS)}, session_id FROM strava_activities WHERE 1 = 1"
    params = []
    if first and last:
        sql += " AND date BETWEEN ? AND ?"
        params += [first, last]
    if runs_only:
        sql += " AND sport IN ('Run', 'TrailRun', 'VirtualRun')"
    with db() as conn:
        rows = conn.execute(sql + " ORDER BY date, start", params).fetchall()
    return [dict(zip(STRAVA_COLS + ("session_id",), r)) for r in rows]


def strava_matched(activity_id, session_id=None):
    """With a session: record that this activity ticked it off. Without: whether it already did."""
    with db() as conn:
        if session_id:
            conn.execute("UPDATE strava_activities SET session_id = ? WHERE id = ?", (session_id, activity_id))
            return True
        row = conn.execute("SELECT session_id FROM strava_activities WHERE id = ?", (activity_id,)).fetchone()
    return bool(row and row[0])


def clear_strava():
    with db() as conn:
        conn.execute("DELETE FROM strava_activities")


def runs(first=None, last=None):
    """
    Every run, oldest first: Strava runs, plus training runs ticked off without a Strava run behind them.
    Each: {date, label, distance_km, source}.
    """
    out = []
    matched = set()
    for a in strava_activities(first, last, runs_only=True):
        out.append({"date": a["date"], "label": a["name"] or "Run", "distance_km": a["distance_km"], "source": "Strava"})
        if a["session_id"]:
            matched.add(a["session_id"])
    plan = active_plan()
    for s in (plan_sessions(plan["id"]) if plan else []):
        if not s["done"] or s["kind"] == "strength" or s["id"] in matched:
            continue
        if first and last and not first <= s["date"] <= last:
            continue
        km = s["actual_km"] if s["actual_km"] is not None else s["distance_km"]
        if km:
            out.append({"date": s["date"], "label": s["title"], "distance_km": km, "source": "Training plan"})
    return sorted(out, key=lambda r: r["date"])


def gym_volume():
    """Per exercise, kg moved each session (weight × sets × reps): [{exercise, date, title, volume}], oldest first."""
    with db() as conn:
        rows = conn.execute(
            "SELECT e.exercise, s.date, s.title, SUM(COALESCE(e.weight_kg, 0) * COALESCE(e.sets, 0) * COALESCE(e.reps, 0)) "
            "FROM gym_exercises e JOIN gym_sessions s ON s.id = e.session_id "
            "GROUP BY lower(e.exercise), s.id ORDER BY s.date, s.created_at").fetchall()
    return [{"exercise": x, "date": d, "title": t, "volume": v} for x, d, t, v in rows]


# ---------------------------------------------------------------------------
# Joint calendar (rows made by joint.py)
# ---------------------------------------------------------------------------

def replace_joint(who, rows):
    """Replace one person's events in the joint calendar."""
    with db() as conn:
        conn.execute("DELETE FROM joint_events WHERE who = ?", (who,))
        conn.executemany(
            "INSERT OR REPLACE INTO joint_events VALUES (?, ?, ?, ?, ?, ?, ?)",
            [(who, r["uid"], r["date"], r["start_min"], r["end_min"], r["title"], r["all_day"]) for r in rows])


def joint_between(first, last):
    """[{who, date, start_min, end_min, title, all_day}] between two ISO dates, in time order."""
    with db() as conn:
        rows = conn.execute("SELECT who, date, start_min, end_min, title, all_day FROM joint_events "
                            "WHERE date BETWEEN ? AND ? ORDER BY date, all_day DESC, start_min", (first, last)).fetchall()
    return [dict(zip(("who", "date", "start_min", "end_min", "title", "all_day"), r)) for r in rows]


# ---------------------------------------------------------------------------
# Training plan (the plan itself is generated by training.py)
# ---------------------------------------------------------------------------

SESSION_COLS = "id, plan_id, week, date, kind, title, distance_km, details, done, actual_km, notes, done_at, ord"
SESSION_SELECT = SESSION_COLS + ", block_id, off_timetable"


def _session(row):
    s = dict(zip(SESSION_SELECT.split(", "), row))
    s["done"] = bool(s["done"])
    return s


def create_plan(name, start_date, race_date, sessions):
    """Save a new plan and its sessions (replacing any earlier plan). Returns the plan's id."""
    plan_id = uuid.uuid4().hex
    with db() as conn:
        conn.execute("DELETE FROM training_plans")
        conn.execute("INSERT INTO training_plans VALUES (?, ?, ?, ?, ?)",
                     (plan_id, name, str(start_date), str(race_date), stamp()))
        conn.executemany(
            f"INSERT INTO training_sessions ({SESSION_COLS}) VALUES (?, ?, ?, ?, ?, ?, ?, ?, 0, NULL, NULL, NULL, ?)",
            [(uuid.uuid4().hex, plan_id, x["week"], x["date"], x["kind"], x["title"], x["distance_km"],
              x["details"], x["ord"]) for x in sessions])
    return plan_id


def active_plan():
    """The current plan as {id, name, start_date, race_date, created_at}, or None."""
    with db() as conn:
        row = conn.execute("SELECT id, name, start_date, race_date, created_at FROM training_plans "
                           "ORDER BY created_at DESC LIMIT 1").fetchone()
    return dict(zip(("id", "name", "start_date", "race_date", "created_at"), row)) if row else None


def plan_sessions(plan_id):
    with db() as conn:
        rows = conn.execute(f"SELECT {SESSION_SELECT} FROM training_sessions WHERE plan_id = ? "
                            "ORDER BY date, ord", (plan_id,)).fetchall()
    return [_session(r) for r in rows]


def get_session(session_id):
    with db() as conn:
        row = conn.execute(f"SELECT {SESSION_SELECT} FROM training_sessions WHERE id = ?", (session_id,)).fetchone()
    return _session(row) if row else None


def plan_week(start_date, day):
    """Which week of the plan a day falls in (weeks run Monday to Sunday, from the plan's first)."""
    first, d = date.fromisoformat(str(start_date)), date.fromisoformat(str(day))
    return max(1, (d - timedelta(days=d.weekday()) - (first - timedelta(days=first.weekday()))).days // 7 + 1)


def add_session(plan_id, day, kind, title, distance_km=None, details=None):
    """Add a session to a plan; returns its id."""
    session_id = uuid.uuid4().hex
    with db() as conn:
        start = conn.execute("SELECT start_date FROM training_plans WHERE id = ?", (plan_id,)).fetchone()[0]
        order = conn.execute("SELECT COALESCE(MAX(ord), -1) + 1 FROM training_sessions WHERE plan_id = ? AND date = ?",
                             (plan_id, str(day))).fetchone()[0]
        conn.execute(f"INSERT INTO training_sessions ({SESSION_COLS}) VALUES (?, ?, ?, ?, ?, ?, ?, ?, 0, NULL, NULL, NULL, ?)",
                     (session_id, plan_id, plan_week(start, day), str(day), kind, title, distance_km, details, order))
    return session_id


def delete_session(session_id):
    """Delete a session and its timetable block."""
    with db() as conn:
        conn.execute("DELETE FROM tt_entries WHERE id = (SELECT block_id FROM training_sessions WHERE id = ?)", (session_id,))
        conn.execute("DELETE FROM training_sessions WHERE id = ?", (session_id,))


def update_session(session_id, **changes):
    """Change any of: date, title, kind, distance_km, details, done, actual_km, notes."""
    allowed = {"date", "title", "kind", "distance_km", "details", "done", "actual_km", "notes"}
    changes = {k: v for k, v in changes.items() if k in allowed}
    if "done" in changes:
        changes["done"] = int(bool(changes["done"]))
        changes["done_at"] = stamp() if changes["done"] else None
    if not changes:
        return
    with db() as conn:
        conn.execute(f"UPDATE training_sessions SET {', '.join(f'{k} = ?' for k in changes)} WHERE id = ?",
                     (*changes.values(), session_id))
        if "done" in changes or "title" in changes:      # its timetable block shows a ✓ once done
            row = conn.execute("SELECT block_id, title, done FROM training_sessions WHERE id = ?", (session_id,)).fetchone()
            if row and row[0]:
                conn.execute("UPDATE tt_entries SET label = ? WHERE id = ?", (("✓ " if row[2] else "") + row[1], row[0]))
        if "date" in changes:                 # it moves to that week's list; if it's the race, the race date follows
            start = conn.execute("SELECT p.start_date FROM training_plans p JOIN training_sessions s ON s.plan_id = p.id "
                                 "WHERE s.id = ?", (session_id,)).fetchone()
            if start:
                conn.execute("UPDATE training_sessions SET week = ? WHERE id = ?",
                             (plan_week(start[0], changes["date"]), session_id))
            conn.execute("UPDATE training_plans SET race_date = ? WHERE id = "
                         "(SELECT plan_id FROM training_sessions WHERE id = ? AND kind = 'race')",
                         (changes["date"], session_id))


def delete_plan(plan_id):
    """Delete a plan, its sessions and their timetable blocks."""
    with db() as conn:
        conn.execute("DELETE FROM tt_entries WHERE id IN (SELECT block_id FROM training_sessions WHERE plan_id = ?)",
                     (plan_id,))
        conn.execute("DELETE FROM training_plans WHERE id = ?", (plan_id,))


def _free_start(conn, day, want, length):
    """
    The free start slot nearest to `want` (later first on a tie) where `length` slots are free of
    the user's blocks and Outlook events, so a training session never covers anything. It looks
    between 07:00 and 21:30 first, then the whole day. Falls back to `want`.
    """
    taken = set()
    for b in blocks_for(conn, day, "plan"):
        taken |= set(range(slot_of(b["start"]), slot_of(b["end"])))
    for ev in _visible_outlook(conn, day):
        taken |= set(range(slot_of(ev["start"]), slot_of(ev["end"])))
    last = SLOTS - length
    want = min(want, last)
    for latest_end in (slot_of("21:30"), SLOTS):
        options = [s for s in range(0, min(last, latest_end - length) + 1) if not taken & set(range(s, s + length))]
        if options:
            return min(options, key=lambda s: (abs(s - want), s < want))
    return want


def place_session(session_id, start_time, minutes, category_id, label, details=None):
    """
    Put a training session on the timetable (Plan) as a block, replacing its old block.
    It goes at `start_time` or the nearest free time that day. Returns the block.
    """
    s = get_session(session_id)
    length = max(1, -(-int(minutes) // SLOT_MIN))
    with db() as conn:
        if s["block_id"]:
            conn.execute("DELETE FROM tt_entries WHERE id = ?", (s["block_id"],))
        start = _free_start(conn, s["date"], slot_of(start_time), length)
        block = {"id": s["block_id"] or f"tr:{session_id}", "date": s["date"], "track": "plan",
                 "start": slot_time(start), "end": slot_time(min(start + length, SLOTS)),
                 "label": label, "category_id": category_id, "details": details}
        apply_block_ops(conn, [("upsert", block)])
        conn.execute("UPDATE training_sessions SET block_id = ?, off_timetable = 0 WHERE id = ?", (block["id"], session_id))
    return block


def session_moved(block_id, day):
    """The user dragged a training block to another day: move its session there too."""
    with db() as conn:
        row = conn.execute("SELECT id FROM training_sessions WHERE block_id = ?", (block_id,)).fetchone()
    if row:
        update_session(row[0], date=str(day))


def unplace_session(session_id):
    """Take a session's block off the timetable."""
    s = get_session(session_id)
    with db() as conn:
        if s and s["block_id"]:
            conn.execute("DELETE FROM tt_entries WHERE id = ?", (s["block_id"],))
        conn.execute("UPDATE training_sessions SET block_id = NULL, off_timetable = 1 WHERE id = ?", (session_id,))


def session_block(session):
    """The session's timetable block, or None (also if the user deleted it from the timetable)."""
    return get_block(session["block_id"]) if session.get("block_id") else None


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
    for b in blocks_between(first, last):
        name = names.get(b["category_id"], "Uncategorised")
        h = (slot_of(b["end"]) - slot_of(b["start"])) * SLOT_MIN / 60
        hours[b["track"]][name] = hours[b["track"]].get(name, 0) + h

    return {
        "start": first, "end": last, "days": num_days,
        "days_logged": len(entries),
        "avg_mood": avg("mood"), "avg_sleep": avg("sleep"), "avg_energy": avg("energy"),
        "avg_productivity": avg("productivity"),
        "avg_water": avg("water"),
        "habit_completion_pct": habits,
        "timetable_hours": hours,
    }

# ---------------------------------------------------------------------------
# Start Working: bars that race to each level's targets. When every level bar is full the
# level is done: the reward goes into the pot and the next level starts from zero. The pot
# is spent on whatever the user's pots are. A weekly bar starts again every Monday and
# doesn't count towards levels.
#
# Everything about the bars is the user's own, in settings.json (nothing is preset):
#   work_areas: [{id, name, colour}]          the page's sections, each in its colour
#   work_bars:  [{key, area, name, verb, weekly, base, step, words}]
#               base = level 1's target (a weekly bar: its target each week), step = added per level,
#               words = what links a session-list item to the bar ("email", "reach out")
#   work_pots:  [{key, name}]                  what the pot can be spent on
#   work_reward: money per level (default 5); work_questions: the delegation nudges
# ---------------------------------------------------------------------------

LEVEL_REWARD = 5.0                      # per level, unless the user sets their own


def _slug(text):
    return re.sub(r"[^a-z0-9]+", "_", str(text).lower()).strip("_") or "x"


def work_areas():
    return [dict(a) for a in load_settings().get("work_areas", [])]


def work_bars():
    """Every bar, in the user's order: [{key, area, name, verb, weekly, base, step, words}]."""
    out = []
    for b in load_settings().get("work_bars", []):
        out.append({"key": b["key"], "area": b.get("area"), "name": b.get("name") or b["key"],
                    "verb": b.get("verb") or b.get("name") or b["key"], "weekly": bool(b.get("weekly")),
                    "base": max(1, int(b.get("base") or 1)), "step": max(0, int(b.get("step") or 0)),
                    "words": [w.strip().lower() for w in b.get("words", []) if str(w).strip()]})
    return out


def work_bar(ref):
    """A bar by key or name (any case), or None."""
    ref = str(ref or "").strip().lower()
    return next((b for b in work_bars() if b["key"] == ref or b["name"].lower() == ref), None)


def level_tracks():
    return tuple(b["key"] for b in work_bars() if not b["weekly"])


def weekly_tracks():
    return tuple(b["key"] for b in work_bars() if b["weekly"])


def work_pots():
    return [dict(p) for p in load_settings().get("work_pots", [])]


def work_reward():
    return float(load_settings().get("work_reward", LEVEL_REWARD))


def work_questions():
    return [q for q in load_settings().get("work_questions", []) if str(q).strip()]


def save_work_setup(areas=None, bars=None, pots=None, reward=None, questions=None):
    """
    Save the user's Start Working setup (any part). Areas, bars and pots without a name are
    dropped; new ones get a key from their name. A bar's key never changes, so its counts stay.
    """
    changes = {}
    if areas is not None:
        clean, seen = [], set()
        for a in areas:
            name = str(a.get("name") or "").strip()
            if not name:
                continue
            aid = a.get("id") or _slug(name)
            while aid in seen:
                aid += "_2"
            seen.add(aid)
            clean.append({"id": aid, "name": name, "colour": str(a.get("colour") or "").strip() or
                          GOAL_CATEGORY_COLOURS[len(clean) % len(GOAL_CATEGORY_COLOURS)]})
        changes["work_areas"] = clean
    if bars is not None:
        clean, seen = [], set()
        for b in bars:
            name = str(b.get("name") or "").strip()
            if not name:
                continue
            key = b.get("key") or _slug(name)
            while key in seen:
                key += "_2"
            seen.add(key)
            words = b.get("words") or []
            if isinstance(words, str):
                words = words.split(",")
            clean.append({"key": key, "area": b.get("area"), "name": name,
                          "verb": str(b.get("verb") or "").strip() or name, "weekly": bool(b.get("weekly")),
                          "base": max(1, int(b.get("base") or 1)), "step": max(0, int(b.get("step") or 0)),
                          "words": [w.strip().lower() for w in words if str(w).strip()]})
        changes["work_bars"] = clean
    if pots is not None:
        clean, seen = [], set()
        for p in pots:
            name = str((p.get("name") if isinstance(p, dict) else p) or "").strip()
            if not name:
                continue
            key = (p.get("key") if isinstance(p, dict) else None) or _slug(name)
            if key not in seen:
                seen.add(key)
                clean.append({"key": key, "name": name})
        changes["work_pots"] = clean
    if reward is not None:
        changes["work_reward"] = max(0.0, round(float(reward), 2))
    if questions is not None:
        changes["work_questions"] = [str(q).strip() for q in questions if str(q).strip()]
    if changes:
        save_settings(**changes)


def work_level():
    return int(load_settings().get("work_level", 1))


def work_week_start(today=None):
    """This week's Monday (London) as an ISO date: weekly bars count from it."""
    today = today or local_today()
    return (today - timedelta(days=today.weekday())).isoformat()


def work_targets(level):
    """Each level bar's target at a level: level 1's, plus its step for each level after."""
    return {b["key"]: b["base"] + b["step"] * (level - 1) for b in work_bars() if not b["weekly"]}


def weekly_targets():
    return {b["key"]: b["base"] for b in work_bars() if b["weekly"]}


def _work_counts(conn, level):
    counts = dict.fromkeys(level_tracks(), 0)
    for track, n in conn.execute("SELECT track, COUNT(*) FROM work_log WHERE level = ? GROUP BY track", (level,)):
        if track in counts:
            counts[track] = n
    return counts


def _weekly_counts(conn):
    counts = dict.fromkeys(weekly_tracks(), 0)
    for track, n in conn.execute("SELECT track, COUNT(*) FROM work_log WHERE at >= ? GROUP BY track", (work_week_start(),)):
        if track in counts:
            counts[track] = n
    return counts


def work_balance(conn=None):
    if conn is None:
        with db() as conn:
            return work_balance(conn)
    return round(conn.execute("SELECT COALESCE(SUM(amount), 0) FROM work_wallet").fetchone()[0], 2)


def work_state():
    """Everything the Start Working page shows."""
    level = work_level()
    with db() as conn:
        counts = _work_counts(conn, level)
        weekly = _weekly_counts(conn)
        balance = work_balance(conn)
        wallet = [dict(zip(("at", "amount", "kind", "note"), r)) for r in conn.execute(
            "SELECT at, amount, kind, note FROM work_wallet ORDER BY at DESC LIMIT 12")]
        totals = dict.fromkeys(level_tracks() + weekly_tracks(), 0)
        for track, n in conn.execute("SELECT track, COUNT(*) FROM work_log GROUP BY track"):
            if track in totals:
                totals[track] = n
        spent = {k: -v for k, v in conn.execute(
            "SELECT kind, SUM(amount) FROM work_wallet WHERE amount < 0 GROUP BY kind")}
    pots = work_pots()
    return {"level": level, "targets": work_targets(level), "counts": counts, "totals": totals,
            "weekly": weekly, "weekly_targets": weekly_targets(),
            "balance": balance, "wallet": wallet, "reward": work_reward(), "pots": pots,
            "spent": {p["key"]: round(spent.get(p["key"], 0), 2) for p in pots}}


def work_tap(track, delta=1, op_id=None):
    """
    One more (delta=1) or one fewer (delta=-1) for a bar at the current level (or, for a
    weekly bar, this week). When every level bar reaches its target the level is completed.
    Returns the level completed, or None. Adding is idempotent for a given op_id.
    """
    bar = work_bar(track)
    if not bar:
        raise ValueError(f"Unknown bar: {track}")
    track = bar["key"]
    level = work_level()
    now = stamp()
    with db() as conn:
        if delta > 0:
            conn.execute("INSERT OR IGNORE INTO work_log VALUES (?, ?, ?, ?)",
                         (op_id or uuid.uuid4().hex, track, level, now))
        elif bar["weekly"]:
            conn.execute("DELETE FROM work_log WHERE id = (SELECT id FROM work_log WHERE track = ? AND at >= ? "
                         "ORDER BY at DESC LIMIT 1)", (track, work_week_start()))
        else:
            conn.execute("DELETE FROM work_log WHERE id = (SELECT id FROM work_log WHERE track = ? AND level = ? "
                         "ORDER BY at DESC LIMIT 1)", (track, level))
        targets = work_targets(level)
        if bar["weekly"] or not targets:
            return None
        counts = _work_counts(conn, level)
        if any(counts[t] < n for t, n in targets.items()):
            return None
        conn.execute("INSERT INTO work_wallet VALUES (?, ?, ?, 'earned', ?)",
                     (uuid.uuid4().hex, now, work_reward(), f"Level {level} complete"))
    save_settings(work_level=level + 1)
    return level


def work_spend(amount, pot, note=None):
    """Spend from the pot on one of the user's pots (by key)."""
    amount = round(float(amount), 2)
    if pot not in {p["key"] for p in work_pots()}:
        raise ValueError("That isn't one of your pots.")
    with db() as conn:
        if amount <= 0 or amount > work_balance(conn) + 1e-9:
            raise ValueError("You can't spend more than is in the pot.")
        conn.execute("INSERT INTO work_wallet VALUES (?, ?, ?, ?, ?)",
                     (uuid.uuid4().hex, stamp(), -amount, pot,
                      (str(note).strip() or None) if note else None))


# Start Working's session list: at the start of a session the user says (or types) what
# needs doing; it's split into items, each matched to an open to-do and/or a bar.

_ORDINALS = (r"first(?:ly)?|second(?:ly)?|third(?:ly)?|fourth(?:ly)?|fifth(?:ly)?|sixth(?:ly)?|"
             r"and then|then|after that|and also|finally|lastly|last of all|next(?=,)|also(?=,)")
_SPLIT = re.compile(rf"(?:\n|[.;!?](?:\s|$)|\s*\b(?:{_ORDINALS})\b[,:]?\s*|^\s*\d+[.)]\s*|\s\d+[.)]\s)",
                    re.I | re.M)
_FILLER = re.compile(r"^(?:(?:ok(?:ay)?|right|so|um+|uh+|and|yeah|well|i'm|i|we|need|needs|have|has|got|to|"
                     r"want|gotta|should|must|then|going to|gonna)\b[,\s]*)+", re.I)
_TRAILING = re.compile(r"(?:[,\s]+(?:and|then|so|also))+$", re.I)
_STOP = {"the", "a", "an", "to", "for", "and", "of", "on", "in", "my", "with", "about", "at", "up", "do", "get",
         "make", "send", "some", "it", "this", "that", "out", "re", "go", "done", "need", "be"}
_NUMBERS = {w: i for i, w in enumerate("zero one two three four five six seven eight nine ten eleven twelve "
                                       "thirteen fourteen fifteen sixteen seventeen eighteen nineteen twenty".split())}


def split_session_text(text):
    """'Firstly email Sam. Secondly, write the newsletter' -> ['Email Sam', 'Write the newsletter']."""
    items = []
    for part in _SPLIT.split(str(text or "")):
        part = _TRAILING.sub("", _FILLER.sub("", (part or "").strip(" ,-–•*"))).strip(" ,.-")
        if len(part) > 1:
            items.append(part[0].upper() + part[1:])
    return items


def _words(text):
    return {w for w in re.findall(r"[a-z0-9]+", text.lower()) if w not in _STOP and len(w) > 1}


def match_todo(title, todos):
    """The open to-do a session item is about (most words in common), or None."""
    from difflib import SequenceMatcher
    item, best, best_score = _words(title), None, 0.0
    for t in todos:
        words = _words(t["title"])
        if not words or not item:
            continue
        common = len(words & item)
        score = common / len(words)
        if not (score == 1 or (common >= 2 and score >= 0.6)):
            score = SequenceMatcher(None, title.lower(), t["title"].lower()).ratio()
            if score < 0.8:
                continue
        if score > best_score:
            best, best_score = t, score
    return best


def match_track(title):
    """
    (bar key, how many) a session item adds to, from the words the user gave each bar; or (None, 1).
    The longest matching word wins. With a bar whose words include "email", 'Send 5 emails' -> 5.
    """
    low = title.lower()
    best, best_word, words = None, "", []
    for b in work_bars():
        for w in b["words"]:
            if len(w) > len(best_word) and re.search(rf"(?<![a-z0-9]){re.escape(w)}(?:s|es)?(?![a-z0-9])", low):
                best, best_word, words = b["key"], w, b["words"]
    if not best:
        return None, 1
    # A number only counts right before what it counts: "send 5 emails", not "call Sam at 5".
    counted = "|".join(re.escape(w) for w in words)
    n = re.search(rf"\b(\d{{1,3}}|{'|'.join(_NUMBERS)})\s+(?:\w+\s+)?(?:{counted})", low)
    amount = (int(n.group(1)) if n.group(1).isdigit() else _NUMBERS[n.group(1)]) if n else 1
    return best, max(1, min(amount, 100))


WORK_SESSION_COLS = ("id", "day", "ord", "title", "done", "todo_id", "track", "amount")


def session_items(day=None):
    day = (day or local_today()).isoformat() if not isinstance(day, str) else day
    with db() as conn:
        rows = conn.execute(f"SELECT {', '.join(WORK_SESSION_COLS)} FROM work_session WHERE day = ? ORDER BY ord",
                            (day,)).fetchall()
    return [{**dict(zip(WORK_SESSION_COLS, r)), "done": bool(r[4])} for r in rows]


def add_session_items(titles, day=None, link=True):
    """Add items to today's session list, each matched to an open to-do and a bar. Returns them."""
    day = day or local_today()
    todos = all_open_todos(day) if link else []
    added = []
    with db() as conn:
        start = conn.execute("SELECT COALESCE(MAX(ord), -1) + 1 FROM work_session WHERE day = ?",
                             (day.isoformat(),)).fetchone()[0]
        for i, title in enumerate(t.strip() for t in titles if t and t.strip()):
            todo = match_todo(title, todos) if link else None
            track, amount = match_track(title) if link else (None, 1)
            item = {"id": uuid.uuid4().hex, "day": day.isoformat(), "ord": start + i, "title": title,
                    "done": False, "todo_id": todo["id"] if todo else None, "track": track, "amount": amount}
            conn.execute(f"INSERT INTO work_session VALUES ({', '.join('?' * len(WORK_SESSION_COLS))})",
                         tuple(int(item[c]) if c == "done" else item[c] for c in WORK_SESSION_COLS))
            added.append(item)
    return added


def _session_item(item_id):
    with db() as conn:
        r = conn.execute(f"SELECT {', '.join(WORK_SESSION_COLS)} FROM work_session WHERE id = ?", (item_id,)).fetchone()
    return {**dict(zip(WORK_SESSION_COLS, r)), "done": bool(r[4])} if r else None


def tick_session_item(item_id, done=True):
    """
    Tick (or untick) a session item, and with it its to-do and its bar. Returns the Start Working
    level it completed, if adding to the bar finished one, else None.
    """
    item = _session_item(item_id)
    if not item or item["done"] == bool(done):
        return None
    with db() as conn:
        conn.execute("UPDATE work_session SET done = ? WHERE id = ?", (int(bool(done)), item_id))
    if item["todo_id"] and get_todo(item["todo_id"]):
        set_todo_done(item["todo_id"], bool(done))
    levelled = None
    if item["track"] and work_bar(item["track"]):
        for _ in range(item["amount"]):
            levelled = work_tap(item["track"], 1 if done else -1) or levelled
    return levelled


def update_session_item(item_id, **changes):
    """Change an item's title or what it's linked to (todo_id, track, amount). Only while it isn't ticked."""
    allowed = {k: v for k, v in changes.items() if k in ("title", "todo_id", "track", "amount")}
    if not allowed:
        return
    with db() as conn:
        conn.execute(f"UPDATE work_session SET {', '.join(f'{k} = ?' for k in allowed)} WHERE id = ? AND done = 0",
                     (*allowed.values(), item_id))


def delete_session_item(item_id):
    with db() as conn:
        conn.execute("DELETE FROM work_session WHERE id = ?", (item_id,))


def clear_session(day=None):
    """Start the list again: today's items go (what they ticked stays ticked)."""
    with db() as conn:
        conn.execute("DELETE FROM work_session WHERE day = ?", ((day or local_today()).isoformat(),))


# Start Working's plan: triage that makes the user decide, for every task, whether only
# they can do it.

PLAN_DECISIONS = ("me", "delegate", "drop")


def plan_tasks(include_finished=False):
    """Plan tasks, newest first: undecided ones, then the rest."""
    with db() as conn:
        rows = conn.execute("SELECT id, title, decision, who, done, created, decided FROM work_plan "
                            + ("" if include_finished else "WHERE done = 0 AND COALESCE(decision, '') != 'drop' ")
                            + "ORDER BY decision IS NOT NULL, created DESC").fetchall()
    keys = ("id", "title", "decision", "who", "done", "created", "decided")
    return [{**dict(zip(keys, r)), "done": bool(r[4])} for r in rows]


def add_plan_task(title):
    title = str(title).strip()
    if not title:
        raise ValueError("A task needs a name.")
    with db() as conn:
        conn.execute("INSERT INTO work_plan (id, title, created) VALUES (?, ?, ?)",
                     (uuid.uuid4().hex, title, stamp()))


def decide_plan_task(task_id, decision, who=None):
    if decision not in PLAN_DECISIONS:
        raise ValueError("Decide: me, delegate or drop.")
    with db() as conn:
        conn.execute("UPDATE work_plan SET decision = ?, who = ?, decided = ? WHERE id = ?",
                     (decision, (str(who).strip() or None) if who else None,
                      stamp(), task_id))


def finish_plan_task(task_id, done=True):
    with db() as conn:
        conn.execute("UPDATE work_plan SET done = ? WHERE id = ?", (int(bool(done)), task_id))


def delete_plan_task(task_id):
    with db() as conn:
        conn.execute("DELETE FROM work_plan WHERE id = ?", (task_id,))


def delegation_stats(days=7):
    """How the user decided in the last `days` days: {me, delegate, drop}."""
    since = (datetime.now(tz()) - timedelta(days=days)).isoformat(timespec="seconds")
    out = dict.fromkeys(PLAN_DECISIONS, 0)
    with db() as conn:
        for decision, n in conn.execute("SELECT decision, COUNT(*) FROM work_plan WHERE decided >= ? "
                                        "GROUP BY decision", (since,)):
            out[decision] = n
    return out

# ---------------------------------------------------------------------------
# Search: one box for everything (Home)
# ---------------------------------------------------------------------------

# kind -> SQL giving (id, title, detail, date, extra) for rows whose `haystack` contains every word.
_SEARCH = {
    "To-do": ("SELECT id, title, notes, period_start, period FROM todos", "title || ' ' || COALESCE(notes, '')"),
    "Goal": ("SELECT id, title, unit, period_start, period FROM goals", "title"),
    "Deadline": ("SELECT id, title, notes, due, done FROM deadlines", "title || ' ' || COALESCE(notes, '')"),
    "Application": ("SELECT id, COALESCE(company, industry, route, 'Application'), "
                    "TRIM(COALESCE(route, '') || ' · ' || status, ' ·'), deadline, status FROM applications",
                    "COALESCE(industry, '') || ' ' || COALESCE(company, '') || ' ' || COALESCE(route, '') || ' ' || "
                    "COALESCE(description, '') || ' ' || COALESCE(contact, '') || ' ' || COALESCE(notes, '')"),
    "Habit": ("SELECT id, name, NULL, NULL, per_week FROM habits", "name"),
    "Journal": ("SELECT date, notes, NULL, date, NULL FROM entries", "COALESCE(notes, '')"),
    "Timetable": ("SELECT id, label, details, date, track || ' ' || start || '-' || \"end\" FROM tt_entries",
                  "label || ' ' || COALESCE(details, '')"),
    "Outlook": ("SELECT uid, title, location, date, start FROM tt_outlook",
                "title || ' ' || COALESCE(location, '') || ' ' || COALESCE(description, '')"),
    "Person": ("SELECT id, name, description, NULL, works_for FROM net_people",
               "name || ' ' || COALESCE(description, '') || ' ' || COALESCE(works_for, '')"),
    "Group": ("SELECT id, name, NULL, NULL, NULL FROM net_groups", "name"),
    "Met": ("SELECT i.person_id, p.name, i.note, i.date, NULL FROM net_interactions i "
            "JOIN net_people p ON p.id = i.person_id", "i.note || ' ' || p.name"),
    "Review": ("SELECT week_start, 'Weekly review', COALESCE(went_well, '') || ' ' || COALESCE(to_change, ''), "
               "week_start, NULL FROM weekly_reviews", "COALESCE(went_well, '') || ' ' || COALESCE(to_change, '')"),
}


def search(query, per_kind=8):
    """Everything matching all the words in `query` (any case), as
    [{kind, id, title, detail, date, extra}], newest first within each kind."""
    words = str(query or "").split()
    if not words:
        return []
    out = []
    with db() as conn:
        for kind, (select, haystack) in _SEARCH.items():
            where = " AND ".join(f"{haystack} LIKE ? ESCAPE '\\'" for _ in words)
            params = ["%" + w.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%" for w in words]
            order = " ORDER BY 4 DESC" if kind not in ("Habit", "Group", "Person") else " ORDER BY 2"
            rows = conn.execute(f"{select} WHERE {where}{order} LIMIT {int(per_kind)}", params).fetchall()
            out += [{"kind": kind, "id": r[0], "title": r[1], "detail": r[2], "date": r[3], "extra": r[4]} for r in rows]
    return out


_apply_day_hours()      # SLOTS / FIRST_MIN from settings.json (re-run when they change)
