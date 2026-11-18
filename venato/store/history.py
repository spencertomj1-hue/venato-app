"""
The whole daily log as one table, for History and Export/Import.

Everything is represented as one "wide" table: one row per date with
mood/sleep/energy/productivity/notes plus a True/False column per habit.
The value cleaners here are shared with the to-do and goal imports.
"""

import pandas as pd

from .database import KEEP, db
from .habits import HABIT_PREFIX, get_habits, set_habit_done
from .journal import save_entry


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
