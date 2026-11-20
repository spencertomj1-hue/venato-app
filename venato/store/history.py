"""
The whole daily log as one table, for History and Export/Import.

Everything is represented as one "wide" table: one row per date with
notes (plus sleep and water when switched on) and a True/False column per habit.
The value cleaners here are shared with the to-do and goal imports.
"""

import pandas as pd

from .database import db
from .habits import HABIT_PREFIX, get_habits, set_habit_done
from .journal import save_entry, tracks_sleep, tracks_water


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
    # The old mood/energy/productivity columns stay in the database but aren't exported, and sleep
    # and water only when switched on.
    df = df[[c for c in ("notes", "sleep", "water") if c in df.columns
             and (c == "notes" or (tracks_sleep() if c == "sleep" else tracks_water()))]]
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
    with db() as conn:
        if replace:
            # Clear what the export holds; the old mood/energy/productivity columns are left as they are.
            conn.execute("UPDATE entries SET notes = NULL, sleep = NULL, water = NULL")
            conn.execute("DELETE FROM entries WHERE mood IS NULL AND energy IS NULL AND productivity IS NULL")
            conn.execute("DELETE FROM habits")  # also clears habit_log (cascade)

        # Make sure every habit column has a habit, then look up the ids.
        for col in habit_cols:
            conn.execute("INSERT OR IGNORE INTO habits (name) VALUES (?)", (col[len(HABIT_PREFIX):],))
        habit_ids = dict(conn.execute("SELECT name, id FROM habits").fetchall())

        for row in df.to_dict("records"):
            if row.get("date") is None or pd.isna(row.get("date")):
                continue  # skip blank rows (e.g. an empty row added in the editor)
            day = pd.to_datetime(row["date"]).date().isoformat()

            # Old exports have mood/energy/productivity columns: ignored. Only the columns present are written.
            fields = {"notes": _clean(row.get("notes"), str)} if "notes" in df.columns else {}
            if "sleep" in df.columns:
                fields["sleep"] = _clean(row.get("sleep"), float)
            if "water" in df.columns:
                fields["water"] = _clean(row.get("water"), float)
            if any(v is not None for v in fields.values()):
                save_entry(conn, day, **fields)

            for col in habit_cols:
                set_habit_done(conn, habit_ids[col[len(HABIT_PREFIX):]], day, _is_ticked(row[col]))
