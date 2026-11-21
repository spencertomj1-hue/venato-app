"""
The daily log: one row per day (notes, and optionally sleep and water). A day's notes are its journal
entry (entries.notes). The table still has the old mood, energy and productivity columns: nothing
reads or writes them, so an older install's values stay as they were.
"""

import sqlite3
import uuid

from .database import KEEP, _read, data_version, db, db_path
from .dates import _as_date
from .settings import load_settings, save_settings


def get_entry(day):
    """Return the entry for an ISO date as a dict, or an empty dict."""
    with db() as conn:
        conn.row_factory = sqlite3.Row
        row = conn.execute("SELECT * FROM entries WHERE date = ?", (day,)).fetchone()
    return dict(row) if row else {}


_seen = {}      # column -> (data version, has values): the existing-install check runs once per database change


def _has_values(column):
    version = (data_version(), str(db_path()))
    if _seen.get(column, (None,))[0] != version:
        with db() as conn:
            found = conn.execute(f"SELECT 1 FROM entries WHERE {column} IS NOT NULL LIMIT 1").fetchone() is not None
        _seen[column] = (version, found)
    return _seen[column][1]


def logged_rows(rows):
    """The days that count as logged: those with notes, or sleep/water while that is switched on."""
    sleep, water = tracks_sleep(), tracks_water()
    return [r for r in rows if (r.get("notes") or "").strip()
            or (sleep and r.get("sleep") is not None) or (water and r.get("water") is not None)]


def _tracks(setting, column):
    """Is this optional measure switched on? Off on new installs; an install that already has some
    recorded counts as on until it chooses (so an upgrade doesn't hide anything)."""
    chosen = load_settings().get(setting)
    return bool(chosen) if chosen is not None else _has_values(column)


def tracks_sleep():
    """Is sleep switched on (Settings -> Daily Log)?"""
    return _tracks("log_sleep", "sleep")


def tracks_water():
    """Is water switched on (Settings -> Daily Log)?"""
    return _tracks("log_water", "water")


def set_tracking(sleep=None, water=None):
    """Switch sleep and/or water on or off. Recorded values are kept either way."""
    changes = {k: bool(v) for k, v in (("log_sleep", sleep), ("log_water", water)) if v is not None}
    if changes:
        save_settings(**changes)


def save_entry(conn, day, notes=KEEP, sleep=KEEP, water=KEEP):
    """Insert or update the entry for a date (uses an open connection). Only the fields given are
    written (KEEP leaves one as it is), so the old mood/energy/productivity columns are never touched."""
    cols = {k: v for k, v in (("notes", notes), ("sleep", sleep), ("water", water)) if v is not KEEP}
    if not cols:
        conn.execute("INSERT OR IGNORE INTO entries (date) VALUES (?)", (day,))
        return
    conn.execute(
        f"INSERT INTO entries (date, {', '.join(cols)}) VALUES (?{', ?' * len(cols)}) "
        f"ON CONFLICT(date) DO UPDATE SET {', '.join(f'{c} = excluded.{c}' for c in cols)}",
        (day, *cols.values()),
    )


def entries_between(first, last):
    """Daily entries between two ISO dates (inclusive), oldest first."""
    return _read("SELECT * FROM entries WHERE date BETWEEN ? AND ? ORDER BY date", (first, last))


def get_journal(day):
    """A day's notes / journal entry ('' if none)."""
    with db() as conn:
        row = conn.execute("SELECT notes FROM entries WHERE date = ?", (_as_date(day).isoformat(),)).fetchone()
    return (row[0] or "") if row else ""


def save_journal(day, text):
    """Set a day's notes / journal entry, leaving sleep and water alone; blank text clears it."""
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
# The journal book (Daily Log): its left page sets sleep and water one at a time, the journal's
# "quoted" / ^marked^ to-dos are remembered so they're only made once, and day trackers are the
# user's own numbers for each day.
# ---------------------------------------------------------------------------

ENTRY_FIELDS = {"sleep": (0, 24), "water": (0, 20)}     # water in litres, like save_entry


def set_entry_field(day, field, value):
    """Set one ENTRY_FIELDS value for a day (None clears it), keeping the rest of its entry."""
    lo, hi = ENTRY_FIELDS[field]
    value = None if value is None else max(lo, min(hi, float(value)))
    with db() as conn:
        save_entry(conn, _as_date(day).isoformat(), **{field: value})


def journal_todo_new(day, period, title):
    """Record that the journal made this to-do; False if it already had (so it isn't added again)."""
    with db() as conn:
        cur = conn.execute("INSERT OR IGNORE INTO journal_todos VALUES (?, ?, ?)",
                           (_as_date(day).isoformat(), period, str(title).strip()))
        return cur.rowcount == 1


def day_trackers():
    """The user's own day trackers (settings "day_trackers"): [{id, name, unit, step}]."""
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
    """Change a tracker's name, unit and/or step."""
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
    day = _as_date(day).isoformat()
    with db() as conn:
        if value is None:
            conn.execute("DELETE FROM day_values WHERE date = ? AND tracker = ?", (day, tracker_id))
        else:
            conn.execute("INSERT OR REPLACE INTO day_values VALUES (?, ?, ?)",
                         (day, tracker_id, max(0.0, min(float(value), 100000.0))))


def day_values(day):
    """{tracker id: value} logged for a day."""
    with db() as conn:
        return dict(conn.execute("SELECT tracker, value FROM day_values WHERE date = ?",
                                 (_as_date(day).isoformat(),)).fetchall())


def day_values_between(first, last):
    """[(date, tracker id, value)] between two dates (inclusive), oldest first."""
    with db() as conn:
        return conn.execute("SELECT date, tracker, value FROM day_values WHERE date BETWEEN ? AND ? ORDER BY date",
                            (_as_date(first).isoformat(), _as_date(last).isoformat())).fetchall()
