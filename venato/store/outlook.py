"""
Imported Outlook (calendar) events on the timetable. The sync itself is venato/outlook.py.

Every sync puts all events on the timetable; the user can then remove an occurrence (hidden)
or change it, which turns it into their own block ("detached": a tt_entries copy with id
"ol:<uid>", and the occurrence hidden). Nothing is ever written back to Outlook.

An event that names a module code (module_code) is tagged with the module that has that code
(module_id), and then takes that module's category (module_category) instead of the Outlook one.
"""

import re
import sqlite3

from .categories import event_category
from .database import _read, db
from .grid import apply_block_ops, get_block_in, slot_count, slot_of


def replace_outlook(rows):
    """Swap in a fresh set of Outlook events (dicts with the tt_outlook columns), tagged with their modules."""
    with db() as conn:
        conn.execute("DELETE FROM tt_outlook")
        conn.executemany(
            'INSERT OR REPLACE INTO tt_outlook (uid, date, start, "end", title, location, all_day, exact, description, '
            "module_code) VALUES (:uid, :date, :start, :end, :title, :location, :all_day, :exact, :description, "
            ":module_code)",
            [{"description": None, "module_code": None, **r} for r in rows],
        )
        _tag_modules(conn)


def title_key(title):
    """An event series' key: its title without Lecture / Seminar / Lab / Tutorial, lower case, spaces collapsed."""
    from venato import feeds
    return re.sub(r"\s+", " ", feeds.strip_kind(title)).strip().lower()


def _rule(text):
    """A title rule as a pattern: its words, whole, any case, any spacing."""
    words = str(text or "").lower().split()
    return re.compile(r"(?<!\w)" + r"\s+".join(map(re.escape, words)) + r"(?!\w)") if words else None


def _tag_modules(conn):
    """Set each event's module_id, the first that applies:
    1. the student's choice for its series (gr_event_links, by title_key; a NULL module = not a module),
    2. the module whose code (any case, spaces ignored) is the event's code,
    3. the first module (oldest) whose title rule is in its title: its `match` words, or its name when it
       has neither a code nor a rule.
    Reads gr_* with SQL only (the store never imports the blocks); no Modules tables = no modules."""
    from venato import feeds
    mods = []
    for cols in ("id, name, code, match", "id, name, code, NULL"):         # (before the Modules block adds match)
        try:
            mods = conn.execute(f"SELECT {cols} FROM gr_modules ORDER BY created_at, rowid").fetchall()
            break
        except sqlite3.OperationalError:
            continue
    try:
        links = dict(conn.execute("SELECT title_key, module_id FROM gr_event_links").fetchall())
    except sqlite3.OperationalError:
        links = {}
    ids = {m[0] for m in mods}
    by_code = {}
    for mid, _, code, _ in mods:
        if code:
            by_code.setdefault(feeds.norm_code(code), mid)
    rules = [(mid, _rule(match or (None if code else name))) for mid, name, code, match in mods]
    rules = [(mid, r) for mid, r in rules if r]
    seen = {}

    def module_of(title, code):
        if (title, code) not in seen:
            key = title_key(title)
            if key in links and (links[key] is None or links[key] in ids):
                hit = links[key]
            else:
                hit = by_code.get(code) if code else None
                full = " ".join(str(title or "").lower().split())        # a rule may name the kind ("lab")
                hit = hit or next((mid for mid, r in rules if r.search(key) or r.search(full)), None)
            seen[(title, code)] = hit
        return seen[(title, code)]

    rows = conn.execute("SELECT uid, title, module_code FROM tt_outlook").fetchall()
    conn.executemany("UPDATE tt_outlook SET module_id = ? WHERE uid = ?",
                     [(module_of(title, code), uid) for uid, title, code in rows])


def tag_outlook_modules():
    """Re-tag the imported events (after a module is added, deleted or its code changed)."""
    with db() as conn:
        _tag_modules(conn)


OUTLOOK_COLS = 'uid, date, start, "end", title, location, all_day, exact, description, module_id'

# The events with their module's category (NULL without a module, or if that category is gone).
_SELECT = ("SELECT " + ", ".join(f"o.{c.strip()}" for c in OUTLOOK_COLS.split(","))
           + ", c.id AS module_category FROM tt_outlook o LEFT JOIN gr_modules m ON m.id = o.module_id "
           "LEFT JOIN tt_categories c ON c.id = m.category_id")


def outlook_between(first, last):
    """Visible Outlook events between two ISO dates (inclusive), timed ones in time order."""
    rows = _read(f"{_SELECT} WHERE o.date BETWEEN ? AND ? "
                 "AND o.uid NOT IN (SELECT uid FROM tt_outlook_hidden)", (first, last)).to_dict("records")
    return sorted(rows, key=lambda r: (r["date"], r["all_day"] == 0, slot_of(r["start"]) if r["start"] else -1))


def _visible_outlook(conn, day, s=0, e=None):
    """Visible timed Outlook events on a timetable day overlapping slots s..e-1 (e: the day's end)."""
    e = slot_count() if e is None else e
    conn.row_factory = sqlite3.Row
    rows = conn.execute(
        f"{_SELECT} WHERE o.date = ? AND o.all_day = 0 "
        "AND o.uid NOT IN (SELECT uid FROM tt_outlook_hidden)", (day,)).fetchall()
    conn.row_factory = None
    return [dict(r) for r in rows if slot_of(r["start"]) < e and slot_of(r["end"]) > s]


def outlook_details(row):
    """Location and description of an Outlook event as one short text."""
    parts = [f"Location: {row['location']}" if row.get("location") else None, row.get("description")]
    return "\n".join(p for p in parts if p) or None


def _as_block(row):
    """An Outlook event in the shape of one of the user's blocks (as it would be once detached)."""
    return {"id": f"ol:{row['uid']}", "date": row["date"], "track": "plan", "start": row["start"],
            "end": row["end"], "label": row["title"], "category_id": event_category(row),
            "details": outlook_details(row)}


def _detach(conn, row):
    conn.execute("INSERT OR IGNORE INTO tt_outlook_hidden VALUES (?)", (row["uid"],))
    apply_block_ops(conn, [("upsert", _as_block(row))])
    return f"ol:{row['uid']}"


def get_outlook(uid):
    """One visible Outlook event, or None."""
    with db() as conn:
        conn.row_factory = sqlite3.Row
        row = conn.execute(f"{_SELECT} WHERE o.uid = ? "
                           "AND o.uid NOT IN (SELECT uid FROM tt_outlook_hidden)", (uid,)).fetchone()
    return dict(row) if row else None


def hide_outlook(uid):
    """Remove an Outlook occurrence from the timetable (it stays in Outlook)."""
    with db() as conn:
        conn.execute("INSERT OR IGNORE INTO tt_outlook_hidden VALUES (?)", (uid,))


def detach_outlook(uid):
    """Turn an Outlook occurrence into the user's own block; returns its block id (or None)."""
    with db() as conn:
        conn.row_factory = sqlite3.Row
        row = conn.execute(f"{_SELECT} WHERE o.uid = ?", (uid,)).fetchone()
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
