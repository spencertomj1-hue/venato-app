"""
The user's timetable blocks: painting, moving, relabelling and reading them. Painting the Plan
first turns any calendar events in the way into the user's own blocks (outlook.py).
"""

import sqlite3

from .database import _read, db
from .grid import BLOCK_COLS, apply_block_ops, blocks_for, plan_paint, slot_count, slot_of, slot_time
from .outlook import _as_block, _detach, _visible_outlook


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
        if not row or not 0 <= s < e <= slot_count():
            return None
        conn.execute("DELETE FROM tt_entries WHERE id = ?", (block_id,))
        paint(day, track, s, e, {"label": row["label"], "category_id": row["category_id"], "details": row["details"]},
              new_id=block_id, conn=conn)
        conn.execute('UPDATE tt_todo_links SET date = ?, start = ?, "end" = ? WHERE date = ? AND start = ?',
                     (day, slot_time(s), slot_time(e), row["date"], row["start"]))    # its to-do goes with it
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


# --- To-dos on the timetable ---
# A to-do's block is the one at the linked date and start, on either track: block ids change when a day
# locks (its Plan copied into the Actual), its date and start don't. One block per to-do.

def link_todo(todo_id, day, start, end, conn=None):
    """Make the block at day/start the to-do's block (replacing any block it had)."""
    if conn is None:
        with db() as conn:
            return link_todo(todo_id, day, start, end, conn)
    conn.execute('INSERT OR REPLACE INTO tt_todo_links (todo_id, date, start, "end") VALUES (?, ?, ?, ?)',
                 (todo_id, day, start, end))


def unlink_todo(todo_id, conn=None):
    if conn is None:
        with db() as conn:
            return unlink_todo(todo_id, conn)
    conn.execute("DELETE FROM tt_todo_links WHERE todo_id = ?", (todo_id,))


def todo_links(first, last):
    """{todo_id: {date, start, end}} for to-dos scheduled on days first..last."""
    rows = _read('SELECT todo_id, date, start, "end" FROM tt_todo_links WHERE date BETWEEN ? AND ?', [first, last])
    return {r["todo_id"]: {"date": r["date"], "start": r["start"], "end": r["end"]} for r in rows.to_dict("records")}


def todo_link(todo_id):
    """The to-do's slot {date, start, end}, or None."""
    with db() as conn:
        row = conn.execute('SELECT date, start, "end" FROM tt_todo_links WHERE todo_id = ?', (todo_id,)).fetchone()
    return dict(zip(("date", "start", "end"), row)) if row else None


def linked_todo(day, start):
    """The id of the to-do whose block is at day/start, or None."""
    with db() as conn:
        row = conn.execute("SELECT todo_id FROM tt_todo_links WHERE date = ? AND start = ?", (day, start)).fetchone()
    return row[0] if row else None


def blocks_at(day, start):
    """The blocks (either track) that start at day/start: a to-do's Plan block and its Actual copy."""
    with db() as conn:
        return [b for track in ("plan", "actual") for b in blocks_for(conn, day, track) if b["start"] == start]
