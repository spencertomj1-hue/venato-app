"""
Deadlines: something due on a date (and optionally a time), with a countdown, ticked off when done.
A deadline can belong to a module (Grades) and can come from Canvas (import_canvas).

(The module isn't called deadlines.py so that store.deadlines stays the function that lists them.)
"""

import re
import uuid

from .database import KEEP, db
from .dates import _as_date, local_today, stamp


DEADLINE_COLS = "id, title, due, notes, done, done_at, created_at, due_time, module_id, source, uid"


def _deadline(row):
    return dict(zip(DEADLINE_COLS.split(", "), row)) | {"done": bool(row[4])}


def _time(value):
    """'9:05' -> '09:05'; None / '' -> None. Raises ValueError if it isn't a time of day."""
    if value in (None, ""):
        return None
    m = re.fullmatch(r"(\d{1,2}):(\d{2})", str(value).strip())
    if not m or int(m.group(1)) > 23 or int(m.group(2)) > 59:
        raise ValueError("Give the time as HH:MM, e.g. 17:00.")
    return f"{int(m.group(1)):02d}:{m.group(2)}"


def add_deadline(title, due, notes=None, due_time=None, module_id=None):
    """Add a deadline; returns its id."""
    title = str(title or "").strip()
    if not title:
        raise ValueError("Say what's due.")
    did = uuid.uuid4().hex
    with db() as conn:
        conn.execute("INSERT INTO deadlines (id, title, due, notes, done, done_at, created_at, due_time, module_id) "
                     "VALUES (?, ?, ?, ?, 0, NULL, ?, ?, ?)",
                     (did, title, _as_date(due).isoformat(), (notes or "").strip() or None,
                      stamp(), _time(due_time), module_id or None))
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


def update_deadline(did, title=KEEP, due=KEEP, notes=KEEP, due_time=KEEP, module_id=KEEP):
    fields = {}
    if title is not KEEP:
        if not str(title or "").strip():
            raise ValueError("Say what's due.")
        fields["title"] = str(title).strip()
    if due is not KEEP:
        fields["due"] = _as_date(due).isoformat()
    if notes is not KEEP:
        fields["notes"] = (notes or "").strip() or None
    if due_time is not KEEP:
        fields["due_time"] = _time(due_time)
    if module_id is not KEEP:
        fields["module_id"] = module_id or None
    if fields:
        with db() as conn:
            conn.execute(f"UPDATE deadlines SET {', '.join(f'{k} = ?' for k in fields)} WHERE id = ?",
                         (*fields.values(), did))


def set_deadline_done(did, done):
    with db() as conn:
        conn.execute("UPDATE deadlines SET done = ?, done_at = ? WHERE id = ?",
                      (int(bool(done)), stamp() if done else None, did))


def delete_deadline(did):
    """Delete a deadline. An imported one is remembered (deadlines_hidden), so a sync doesn't bring it back."""
    with db() as conn:
        conn.execute("INSERT OR IGNORE INTO deadlines_hidden "
                     "SELECT uid FROM deadlines WHERE id = ? AND uid IS NOT NULL", (did,))
        conn.execute("DELETE FROM deadlines WHERE id = ?", (did,))


def _course_module(conn, course_id, label):
    """Remember a Canvas course (gr_canvas_courses) and return the module it's linked to (or None).
    A course seen for the first time is linked to the module whose code its label contains, if any."""
    if not course_id:
        return None
    row = conn.execute("SELECT module_id, label FROM gr_canvas_courses WHERE course_id = ?", (course_id,)).fetchone()
    if row:
        if label and label != row[1]:
            conn.execute("UPDATE gr_canvas_courses SET label = ? WHERE course_id = ?", (label, course_id))
        return row[0]
    norm = re.sub(r"\s+", "", label or "").upper()
    module = None
    for mid, code in conn.execute("SELECT id, code FROM gr_modules WHERE code IS NOT NULL AND TRIM(code) != ''"):
        if re.sub(r"\s+", "", code).upper() in norm:
            module = mid
            break
    conn.execute("INSERT INTO gr_canvas_courses (course_id, label, module_id) VALUES (?, ?, ?)",
                 (course_id, label, module))
    return module


def import_canvas(events):
    """
    Upsert Canvas assignments (feeds.canvas_events) as deadlines, by uid. Returns {added, updated}.
    Deleted ones (deadlines_hidden) are skipped. done, done_at and notes are never touched. A title or
    date changes only when Canvas changed it (it differs from source_title / source_due), so one the
    student edited stays as they left it. A new deadline gets its course's module (gr_canvas_courses).
    """
    added = updated = 0
    with db() as conn:
        hidden = {r[0] for r in conn.execute("SELECT uid FROM deadlines_hidden")}
        for ev in events:
            if not ev.get("uid") or ev["uid"] in hidden:
                continue
            module = _course_module(conn, ev.get("course_id"), ev.get("label"))
            row = conn.execute("SELECT id, source_title, source_due, source_due_time FROM deadlines "
                               "WHERE uid = ?", (ev["uid"],)).fetchone()
            if row is None:
                conn.execute(
                    "INSERT INTO deadlines (id, title, due, notes, done, done_at, created_at, due_time, module_id, "
                    "source, uid, course_id, source_title, source_due, source_due_time) "
                    "VALUES (?, ?, ?, NULL, 0, NULL, ?, ?, ?, 'canvas', ?, ?, ?, ?, ?)",
                    (uuid.uuid4().hex, ev["title"], ev["due"], stamp(), ev.get("due_time"), module, ev["uid"],
                     ev.get("course_id"), ev["title"], ev["due"], ev.get("due_time")))
                added += 1
                continue
            did, s_title, s_due, s_time = row
            fields = {}
            if ev["title"] != s_title:
                fields |= {"title": ev["title"], "source_title": ev["title"]}
            if (ev["due"], ev.get("due_time")) != (s_due, s_time):
                fields |= {"due": ev["due"], "due_time": ev.get("due_time"),
                           "source_due": ev["due"], "source_due_time": ev.get("due_time")}
            if fields:
                conn.execute(f"UPDATE deadlines SET {', '.join(f'{k} = ?' for k in fields)} WHERE id = ?",
                             (*fields.values(), did))
                updated += 1
    return {"added": added, "updated": updated}


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
