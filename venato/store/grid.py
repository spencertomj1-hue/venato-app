"""
The timetable grid: a day's half-hour slots, the painting rules, and raw block rows.

A timetable day runs from day_start to day_end (settings.py) in 30-minute slots, numbered from 0.
Each day has two tracks: the Plan and the Actual.

The painting rules (plan_paint) are the source of truth. The grid's JS (timetable_component.js,
paintRange) mirrors them only to show edits instantly; what gets saved is always computed here.
"""

import sqlite3
import uuid

from .settings import day_hours, day_length


TRACKS = ("plan", "actual")


def slot_count():
    """Half-hour slots in a timetable day (36 for 07:00 to 01:00)."""
    start, end = day_hours()
    return 2 * day_length(start, end)


def first_min():
    """Minutes after midnight of the first slot (420 for 07:00)."""
    return day_hours()[0] * 60


def slot_time(i):
    """Slot index (0..SLOTS) -> "HH:mm". Slot SLOTS is the end of the last slot (01:00 by default)."""
    m = (first_min() + 30 * i) % 1440
    return f"{m // 60:02d}:{m % 60:02d}"


def slot_of(t):
    """"HH:mm" -> slot index. Times before the day's start (07:00 by default) are after midnight."""
    h, m = map(int, t.split(":"))
    mins = h * 60 + m
    if mins < first_min():
        mins += 1440
    return round((mins - first_min()) / 30)


def plan_paint(existing, day, track, s, e, block, new_id=None):
    """
    Work out how to fill slots s..e-1 of one day/track.

    existing: that day/track's blocks (dicts with id, date, track, start, end,
              label, category_id).
    block:    {"label", "category_id"} to paint, or None to clear the slots.

    Overlapped blocks are trimmed or split; the new block merges with touching
    blocks that have the same label and category.

    Returns (ops, affected): ops are ("upsert", entry) / ("delete", id) tuples,
    affected are existing blocks with a different label/category that get
    trimmed, split or removed (i.e. data that would be overwritten).
    """
    ops, affected = [], []
    for en in existing:
        es, ee = slot_of(en["start"]), slot_of(en["end"])
        if ee <= s or es >= e:
            continue
        same = block and en["label"] == block["label"] and en["category_id"] == block["category_id"]
        if not same:
            affected.append(en)
        left, right = es < s, ee > e
        if left:
            ops.append(("upsert", {**en, "end": slot_time(s)}))
        if right:
            ops.append(("upsert", {**en, "id": uuid.uuid4().hex if left else en["id"], "start": slot_time(e)}))
        if not left and not right:
            ops.append(("delete", en["id"]))

    if block:
        # Look at the state after trimming to find blocks to merge with.
        after = {en["id"]: en for en in existing}
        for kind, val in ops:
            if kind == "upsert":
                after[val["id"]] = val
            else:
                after.pop(val, None)
        ns, ne = s, e
        for en in list(after.values()):
            if en["label"] != block["label"] or en["category_id"] != block["category_id"]:
                continue
            if slot_of(en["end"]) == ns:
                ns = slot_of(en["start"])
                ops.append(("delete", en["id"]))
            elif slot_of(en["start"]) == ne:
                ne = slot_of(en["end"])
                ops.append(("delete", en["id"]))
        ops.append(("upsert", {
            "id": new_id or uuid.uuid4().hex, "date": day, "track": track,
            "start": slot_time(ns), "end": slot_time(ne),
            "label": block["label"], "category_id": block["category_id"], "details": block.get("details"),
        }))
    return ops, affected


BLOCK_COLS = 'id, date, track, start, "end", label, category_id, details'


def blocks_for(conn, day, track):
    conn.row_factory = sqlite3.Row
    rows = conn.execute(
        f"SELECT {BLOCK_COLS} FROM tt_entries WHERE date = ? AND track = ?",
        (day, track),
    ).fetchall()
    conn.row_factory = None
    return [dict(r) for r in rows]


def apply_block_ops(conn, ops):
    for kind, val in ops:
        if kind == "delete":
            conn.execute("DELETE FROM tt_entries WHERE id = ?", (val,))
        else:
            conn.execute(
                f"INSERT OR REPLACE INTO tt_entries ({BLOCK_COLS}) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (val["id"], val["date"], val["track"], val["start"], val["end"], val["label"], val["category_id"],
                 val.get("details")),
            )


def get_block_in(conn, block_id):
    return conn.execute("SELECT 1 FROM tt_entries WHERE id = ?", (block_id,)).fetchone() is not None
