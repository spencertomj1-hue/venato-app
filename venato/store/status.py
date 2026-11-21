"""
Done / not done, marked on a timetable block or calendar event (its card's buttons). Each mark keeps
a snapshot of what was marked (date, times, label, category), so it survives the block moving or going:
status_log is there for analysis.
"""

from .database import db
from .dates import _as_date, local_today, stamp

BLOCK_STATUSES = ("done", "missed")


def set_block_status(block_id, status, date=None, start=None, end=None, label=None, category_id=None):
    """
    Mark a timetable block (or "outlook:<uid>" calendar event) done or missed (not done), with a
    snapshot of it for analysis; status None clears it. Returns the status now saved.
    """
    with db() as conn:
        if status is None:
            conn.execute("DELETE FROM tt_status WHERE id = ?", (block_id,))
            return None
        if status not in BLOCK_STATUSES:
            raise ValueError("status must be 'done' or 'missed'.")
        conn.execute('INSERT OR REPLACE INTO tt_status (id, date, start, "end", label, category_id, status, at) '
                     "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                     (block_id, _as_date(date).isoformat() if date else local_today().isoformat(),
                      start, end, label, category_id, status, stamp()))
    return status


def block_statuses(first, last):
    """{id: "done" | "missed"} for blocks and events on days first..last."""
    with db() as conn:
        rows = conn.execute("SELECT id, status FROM tt_status WHERE date BETWEEN ? AND ?",
                            (_as_date(first).isoformat(), _as_date(last).isoformat())).fetchall()
    return dict(rows)


def status_log(first=None, last=None):
    """Every done / missed mark (oldest first), for analysis: [{id, date, start, end, label, category_id, status, at}]."""
    sql, args = 'SELECT id, date, start, "end", label, category_id, status, at FROM tt_status', ()
    if first and last:
        sql, args = sql + " WHERE date BETWEEN ? AND ?", (_as_date(first).isoformat(), _as_date(last).isoformat())
    with db() as conn:
        rows = conn.execute(sql + " ORDER BY date, start", args).fetchall()
    return [dict(zip(("id", "date", "start", "end", "label", "category_id", "status", "at"), r)) for r in rows]
