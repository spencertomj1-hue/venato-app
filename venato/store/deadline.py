"""
Deadlines: something due on a date (and optionally a time), with a countdown, ticked off when done.
A deadline can belong to a module (Modules) and can come from Canvas (import_canvas).
A deadline can have a plan: an hours goal (goals.deadline_id) in its module's category. Ticking the
deadline done closes the goal, deleting it deletes the goal, and a new date moves the goal's due date.

(The module isn't called deadlines.py so that store.deadlines stays the function that lists them.)
"""

import re
import uuid
from datetime import datetime, timedelta
from datetime import time as dtime

from .database import KEEP, db
from .dates import _as_date, local_now, local_today, stamp
from .goals import _period_for, add_goal, deadline_goal, get_goal, update_goal


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
        with db() as conn:                       # the plan moves in the same transaction as the date
            if "due" in fields:
                row = conn.execute("SELECT due FROM deadlines WHERE id = ?", (did,)).fetchone()
                if row:
                    _move_plan(conn, did, row[0], fields["due"])
            conn.execute(f"UPDATE deadlines SET {', '.join(f'{k} = ?' for k in fields)} WHERE id = ?",
                         (*fields.values(), did))
            # Its plan goal follows: a new title shows in the goal (its label, which counts the sittings,
            # stays so they keep counting); a new module moves the hours to that module's category.
            if "title" in fields:
                conn.execute("UPDATE goals SET title = ? WHERE deadline_id = ?", (fields["title"], did))
            if fields.get("module_id"):
                cat = conn.execute("SELECT category_id FROM gr_modules WHERE id = ?", (fields["module_id"],)).fetchone()
                if cat and cat[0]:
                    conn.execute("UPDATE goals SET category_id = ? WHERE deadline_id = ?", (cat[0], did))


def set_deadline_done(did, done):
    """Tick a deadline off (or back on). Its plan goal closes with it, and its suggested sittings go;
    un-ticking opens the plan again."""
    with db() as conn:
        conn.execute("UPDATE deadlines SET done = ?, done_at = ? WHERE id = ?",
                      (int(bool(done)), stamp() if done else None, did))
        conn.execute("UPDATE goals SET closed = ? WHERE deadline_id = ?", (int(bool(done)), did))


def delete_deadline(did):
    """Delete a deadline. An imported one is remembered (deadlines_hidden), so a sync doesn't bring it back."""
    with db() as conn:
        conn.execute("INSERT OR IGNORE INTO deadlines_hidden "
                     "SELECT uid FROM deadlines WHERE id = ? AND uid IS NOT NULL", (did,))
        conn.execute("DELETE FROM goal_week WHERE goal_id IN (SELECT id FROM goals WHERE deadline_id = ?)", (did,))
        conn.execute("DELETE FROM goals WHERE deadline_id = ?", (did,))     # its plan goes with it
        conn.execute("DELETE FROM deadlines WHERE id = ?", (did,))


def _move_plan(conn, did, old_due, new_due):
    """A deadline moved from old_due to new_due: its plan's finish-by day moves by the same number of days
    (so "the day before" stays the day before, and a custom finish-by keeps its gap). Never before the plan's start."""
    delta = (_as_date(new_due) - _as_date(old_due)).days
    row = conn.execute("SELECT id, due, period_start FROM goals WHERE deadline_id = ?", (did,)).fetchone() if delta else None
    if row:
        start = _as_date(row[2])
        due = max(start, min(_as_date(new_due), _as_date(row[1]) + timedelta(days=delta)))   # never after the deadline
        conn.execute("UPDATE goals SET due = ?, period = ? WHERE id = ?",
                     (due.isoformat(), _period_for(start, due), row[0]))


def plan_deadline(did, category_id, total=None, per_week=None, finish_by=None, today=None):
    """
    Plan a deadline: an hours goal in `category_id` (its module's) labelled with the deadline's title, so pace,
    carry-over, sittings and "can't make it" all work for it. Give `total` hours, or `per_week` (the hours
    for each week from today to the finish-by day, in halves). finish_by defaults to the day before it's
    due (or the due day itself when that's today). Planning again changes the same goal. Returns it.
    `today` is for tests; it's the day the plan starts.
    """
    d = get_deadline(did)
    if not d or d["done"]:
        raise ValueError("That deadline is gone or already done.")
    if (total is None) == (per_week is None):
        raise ValueError("Give either the total hours or the hours a week.")
    today, due = _as_date(today or local_today()), _as_date(d["due"])
    finish = _as_date(finish_by) if finish_by else max(today, due - timedelta(days=1))
    if finish < today:
        raise ValueError("Finish by today or later.")
    if finish > due:
        raise ValueError("Finish by the day it's due at the latest.")
    existing = deadline_goal(did)
    if total is None:
        days = (finish - today).days + 1
        total = round(float(per_week) * days / 7 * 2) / 2 + (existing["value"] if existing else 0)
    if float(total) <= 0:
        raise ValueError("Give more than 0 hours.")
    if existing:
        update_goal(existing["id"], title=d["title"], target=total, category_id=category_id, label=d["title"],
                    due=finish)
        return get_goal(existing["id"])
    return add_goal(d["title"], None, today, total, unit="h", category_id=category_id, label=d["title"],
                    due=finish, deadline_id=did)


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
    from venato import feeds
    in_label = {feeds.norm_code(c) for c in feeds.CODE.findall(label or "")}   # whole codes, not substrings
    module = None
    for mid, code in conn.execute("SELECT id, code FROM gr_modules WHERE code IS NOT NULL AND TRIM(code) != '' "
                                  "ORDER BY created_at"):
        if feeds.norm_code(code) in in_label:
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
            row = conn.execute("SELECT id, source_title, source_due, source_due_time, due FROM deadlines "
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
            did, s_title, s_due, s_time, current_due = row
            fields = {}
            if ev["title"] != s_title:
                fields |= {"title": ev["title"], "source_title": ev["title"]}
            if ev["due"] != s_due:            # date and time apart: a new time keeps a date the student moved
                fields |= {"due": ev["due"], "source_due": ev["due"]}
                _move_plan(conn, did, current_due, ev["due"])          # its plan's finish-by moves with it
            if ev.get("due_time") != s_time:
                fields |= {"due_time": ev.get("due_time"), "source_due_time": ev.get("due_time")}
            if fields:
                conn.execute(f"UPDATE deadlines SET {', '.join(f'{k} = ?' for k in fields)} WHERE id = ?",
                             (*fields.values(), did))
                if "title" in fields:
                    conn.execute("UPDATE goals SET title = ? WHERE deadline_id = ?", (fields["title"], did))
                updated += 1
    return {"added": added, "updated": updated}


def _due_at(due, due_time):
    """The moment a deadline is due (naive local): its time, or the end of its day."""
    day = _as_date(due)
    if due_time:
        h, m = map(int, due_time.split(":"))
        return datetime.combine(day, dtime(h, m))
    return datetime.combine(day + timedelta(days=1), dtime(0))


def deadline_overdue(d, now=None):
    """Is a deadline ({due, due_time}) past it? With a time, from that minute; without, from the next day."""
    now = now or local_now()
    return now.replace(tzinfo=None) > _due_at(d["due"], d.get("due_time"))


def countdown(due, today=None, due_time=None, now=None):
    """'Today', 'Today, 17:00', 'Overdue since 17:00', 'Tomorrow', 'Tomorrow, 09:00', 'in 5 days',
    '1 day overdue' or '3 days overdue'. With a due time and `now` (default: the clock, unless only
    `today` is given), a deadline due today is overdue from that time on."""
    from venato import regional
    if now is None and today is None:
        now = local_now()
    today = _as_date(today) if today is not None else now.date()
    if now is not None and now.date() != today:
        now = None                                   # a `now` on another day says nothing about the time
    n = (_as_date(due) - today).days
    at = f", {regional.time(due_time)}" if due_time else ""
    if n == 0:
        if due_time and now is not None and deadline_overdue({"due": due, "due_time": due_time}, now):
            return f"Overdue since {regional.time(due_time)}"
        return "Today" + at
    if n == 1:
        return "Tomorrow" + at
    if n == -1:
        return "1 day overdue"
    return f"in {n} days" if n > 0 else f"{-n} days overdue"
