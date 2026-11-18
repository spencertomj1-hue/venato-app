"""
Deadlines: something due on a date, with a countdown, ticked off when done.

(The module isn't called deadlines.py so that store.deadlines stays the function that lists them.)
"""

import uuid

from .database import KEEP, db
from .dates import _as_date, local_today, stamp


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
