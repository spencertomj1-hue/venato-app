"""
Imported Outlook (calendar) events on the timetable. The sync itself is venato/outlook.py.

Every sync puts all events on the timetable; the user can then remove an occurrence (hidden)
or change it, which turns it into their own block ("detached": a tt_entries copy with id
"ol:<uid>", and the occurrence hidden). Nothing is ever written back to Outlook.
"""

import sqlite3

from .categories import outlook_category
from .database import _read, db
from .grid import apply_block_ops, get_block_in, slot_count, slot_of


def replace_outlook(rows):
    """Swap in a fresh set of Outlook events (dicts with the tt_outlook columns)."""
    with db() as conn:
        conn.execute("DELETE FROM tt_outlook")
        conn.executemany(
            'INSERT OR REPLACE INTO tt_outlook (uid, date, start, "end", title, location, all_day, exact, description) '
            "VALUES (:uid, :date, :start, :end, :title, :location, :all_day, :exact, :description)",
            [{"description": None, **r} for r in rows],
        )


def outlook_between(first, last):
    """Visible Outlook events between two ISO dates (inclusive), timed ones in time order."""
    rows = _read(f"SELECT {OUTLOOK_COLS} FROM tt_outlook WHERE date BETWEEN ? AND ? "
                 "AND uid NOT IN (SELECT uid FROM tt_outlook_hidden)", (first, last)).to_dict("records")
    return sorted(rows, key=lambda r: (r["date"], r["all_day"] == 0, slot_of(r["start"]) if r["start"] else -1))


OUTLOOK_COLS = 'uid, date, start, "end", title, location, all_day, exact, description'


def _visible_outlook(conn, day, s=0, e=None):
    """Visible timed Outlook events on a timetable day overlapping slots s..e-1 (e: the day's end)."""
    e = slot_count() if e is None else e
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
            "end": row["end"], "label": row["title"], "category_id": outlook_category(row["title"]),
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


def outlook_signature():
    """A cheap fingerprint of tt_outlook, to tell whether a sync changed anything."""
    with db() as conn:
        return conn.execute(
            'SELECT COUNT(*), TOTAL(LENGTH(uid || date || COALESCE(start, \'\') || COALESCE("end", \'\') || title)), '
            "GROUP_CONCAT(uid || COALESCE(start, '') || title, '|') FROM tt_outlook"
        ).fetchone()


def outlook_overlaps(day, s, e):
    """Visible timed Outlook events on that timetable day covering any of slots s..e-1."""
    return [r for r in outlook_between(day, day)
            if not r["all_day"] and slot_of(r["start"]) < e and slot_of(r["end"]) > s]
