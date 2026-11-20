"""
The daily log: one row per day (notes, and optionally sleep and water). A day's notes are its journal
entry (entries.notes). The table still has the old mood, energy and productivity columns: nothing
reads or writes them, so an older install's values stay as they were.
"""

import sqlite3

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
