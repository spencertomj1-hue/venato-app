"""
The daily log: one row per day (mood, sleep, energy, water, productivity, notes). A day's notes
are its journal entry (entries.notes).
"""

import sqlite3

from .database import KEEP, _read, db
from .dates import _as_date


def get_entry(day):
    """Return the entry for an ISO date as a dict, or an empty dict."""
    with db() as conn:
        conn.row_factory = sqlite3.Row
        row = conn.execute("SELECT * FROM entries WHERE date = ?", (day,)).fetchone()
    return dict(row) if row else {}


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


def entries_between(first, last):
    """Daily entries between two ISO dates (inclusive), oldest first."""
    return _read("SELECT * FROM entries WHERE date BETWEEN ? AND ? ORDER BY date", (first, last))


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
