"""
To-dos for a day, a week or a month.

Each to-do belongs to one period, identified by its first day (period_start; the period maths
is in dates.py). Repeating to-dos get a fresh unticked copy when a new period starts
(roll_todos). "Today" is the date in the user's time zone (dates.local_today).

A to-do can also have a due day, how long it takes (minutes) and one of the user's own to-do
categories (todo_groups, separate from the timetable's). The To-dos page's "By due date" view lists
open to-dos by them; a to-do given a due day goes in the list that day falls in (list_for_due).
"""

import sqlite3
import uuid
from datetime import date, timedelta

import pandas as pd

from .database import _read, db
from .dates import _as_date, end_of_period, local_today, shift_period, stamp, start_of_period
from .history import _clean, _is_ticked


TODO_PERIODS = ("daily", "weekly", "monthly")


TODO_BASE = 'id, title, notes, period, period_start, done, done_at, "repeat", ord, created_at'   # an insert sets these
TODO_COLS = TODO_BASE + ", due, minutes, group_id"
TODO_MINUTES = 30                      # how long a to-do takes when the user didn't say
TODO_GROUP_COLOURS = ("#60A5FA", "#F472B6", "#34D399", "#FBBF24", "#A78BFA", "#F87171", "#2DD4BF", "#FB923C")


def _todo(row):
    g = dict(row)
    g["done"], g["repeat"] = bool(g["done"]), bool(g["repeat"])
    return g


def todos_for(period, start):
    """The to-dos of one period, in list order."""
    start = start_of_period(period, start).isoformat()
    with db() as conn:
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            f"SELECT {TODO_COLS} FROM todos WHERE period = ? AND period_start = ? ORDER BY ord, created_at",
            (period, start),
        ).fetchall()
    return [_todo(r) for r in rows]


def get_todo(todo_id):
    with db() as conn:
        conn.row_factory = sqlite3.Row
        row = conn.execute(f"SELECT {TODO_COLS} FROM todos WHERE id = ?", (todo_id,)).fetchone()
    return _todo(row) if row else None


def _next_ord(conn, period, start):
    return conn.execute("SELECT COALESCE(MAX(ord) + 1, 0) FROM todos WHERE period = ? AND period_start = ?",
                        (period, start)).fetchone()[0]


def _insert_todo(conn, title, period, start, notes=None, repeat=False, todo_id=None, minutes=None, group_id=None):
    """Add a to-do at the end of its list. Idempotent for a given id (the to-do list replays ops)."""
    todo_id = todo_id or uuid.uuid4().hex
    conn.execute(
        f"INSERT OR IGNORE INTO todos ({TODO_BASE}) VALUES (?, ?, ?, ?, ?, 0, NULL, ?, ?, ?)",
        (todo_id, title, notes, period, start, int(bool(repeat)), _next_ord(conn, period, start),
         stamp()),
    )
    if minutes or group_id:
        conn.execute("UPDATE todos SET minutes = ?, group_id = ? WHERE id = ?", (minutes, group_id, todo_id))
    return todo_id


def add_todo(title, period, day, notes=None, repeat=False, todo_id=None, **details):
    """Add a to-do to the period containing `day` (details: due, minutes, group_id); returns it."""
    title = str(title).strip()
    if not title:
        raise ValueError("A todo needs a title.")
    start = start_of_period(period, day).isoformat()
    with db() as conn:
        todo_id = _insert_todo(conn, title, period, start, notes or None, repeat, todo_id)
    if details:
        update_todo(todo_id, move=False, **details)
    return get_todo(todo_id)


def set_todo_done(todo_id, done):
    """Tick or untick a to-do (done_at records when it was ticked)."""
    with db() as conn:
        conn.execute(
            "UPDATE todos SET done = ?, done_at = CASE WHEN ? THEN COALESCE(done_at, ?) END WHERE id = ?",
            (int(bool(done)), int(bool(done)), stamp(), todo_id),
        )
    _mark_block(todo_id, done)


def _mark_block(todo_id, done):
    """A scheduled to-do's block (Plan and Actual copy) is marked done when it's ticked, cleared when unticked."""
    from .status import set_block_status            # (status sits below todos; nothing circular)
    from .timetable import blocks_at, todo_link
    link = todo_link(todo_id)
    if not link:
        return
    for b in blocks_at(link["date"], link["start"]):
        set_block_status(b["id"], "done" if done else None, b["date"], b["start"], b["end"], b["label"],
                         b["category_id"])


def update_todo(todo_id, move=True, **changes):
    """
    Change a to-do's title, notes, repeat flag, or details: due (a day, or None to clear it), minutes
    and group_id (its to-do category). A new due day moves it to the list that day falls in, unless
    move=False.
    """
    if "due" in changes:
        changes["due"] = _as_date(changes["due"]).isoformat() if changes["due"] else None
    if "minutes" in changes:
        changes["minutes"] = int(changes["minutes"]) if changes["minutes"] else None
    if "group_id" in changes:
        changes["group_id"] = changes["group_id"] or None
    fields = {k: v for k, v in changes.items() if k in ("title", "notes", "repeat", "due", "minutes", "group_id")}
    if "title" in fields:
        fields["title"] = str(fields["title"]).strip()
        if not fields["title"]:
            raise ValueError("A todo needs a title.")
    if "notes" in fields:
        fields["notes"] = (str(fields["notes"]).strip() if fields["notes"] is not None else "") or None
    if "repeat" in fields:
        fields["repeat"] = int(bool(fields["repeat"]))
    if not fields:
        return
    sets = ", ".join(f'"{k}" = ?' for k in fields)
    with db() as conn:
        conn.execute(f"UPDATE todos SET {sets} WHERE id = ?", (*fields.values(), todo_id))
        if move and fields.get("due"):
            period, start = list_for_due(fields["due"])
            row = conn.execute("SELECT period, period_start FROM todos WHERE id = ?", (todo_id,)).fetchone()
            if row and tuple(row) != (period, start):
                conn.execute("UPDATE todos SET period = ?, period_start = ?, ord = ? WHERE id = ?",
                             (period, start, _next_ord(conn, period, start), todo_id))


# --- Due days, how long, and the user's own to-do categories ---

def list_for_due(due, today=None):
    """
    (period, period_start) of the list a to-do due on `due` goes in: today's if it's due today or
    earlier, this week's if it's due later this week, else the month's list of the month it's due in.
    """
    today = today or local_today()
    due = _as_date(due)
    if due <= today:
        return "daily", start_of_period("daily", today).isoformat()
    week = start_of_period("weekly", today)
    if due <= end_of_period("weekly", week):
        return "weekly", week.isoformat()
    return "monthly", start_of_period("monthly", due).isoformat()


def todo_due(todo):
    """The day a to-do should be done by: its own due day, else the last day of its list's period."""
    if todo.get("due"):
        return date.fromisoformat(todo["due"])
    return end_of_period(todo["period"], date.fromisoformat(todo["period_start"]))


def add_detailed_todo(title, due=None, group_id=None, minutes=None, notes=None):
    """A to-do from the To-dos page's pop-up: it goes in the list its due day falls in (today's if none)."""
    period, start = list_for_due(due or local_today())
    return add_todo(title, period, start, notes=notes, due=due, group_id=group_id, minutes=minutes)


def open_todos(today=None):
    """
    Every unticked to-do in today's, this week's and this month's lists, plus any with a due day in
    a later list, most urgent first (by due day, then list order).
    """
    today = today or local_today()
    starts = [(p, start_of_period(p, today).isoformat()) for p in TODO_PERIODS]
    where = " OR ".join("(period = ? AND period_start = ?)" for _ in starts)
    with db() as conn:
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            f"SELECT {TODO_COLS} FROM todos WHERE done = 0 AND ({where} OR (due IS NOT NULL AND period_start > ?))",
            (*[x for pair in starts for x in pair], today.isoformat()),
        ).fetchall()
    order = {p: i for i, p in enumerate(TODO_PERIODS)}
    return sorted((_todo(r) for r in rows), key=lambda t: (todo_due(t), order[t["period"]], t["ord"]))


def done_todos(today=None):
    """To-dos ticked in the last 7 days, most recently ticked first."""
    since = ((today or local_today()) - timedelta(days=6)).isoformat()
    with db() as conn:
        conn.row_factory = sqlite3.Row
        rows = conn.execute(f"SELECT {TODO_COLS} FROM todos WHERE done = 1 AND substr(done_at, 1, 10) >= ? "
                            "ORDER BY done_at DESC", (since,)).fetchall()
    return [_todo(r) for r in rows]


def todo_groups():
    """The user's to-do categories in order: [{id, name, colour, goal_id}]. goal_id: the goal it was made
    for (a goal is also a to-do category), else None."""
    with db() as conn:
        rows = conn.execute("SELECT id, name, colour, goal_id FROM todo_groups ORDER BY ord, name").fetchall()
    return [{"id": r[0], "name": r[1], "colour": r[2], "goal_id": r[3]} for r in rows]


def _add_group(conn, name, colour=None):
    """The id of the category called `name` (any case), adding it if there isn't one."""
    row = conn.execute("SELECT id FROM todo_groups WHERE name = ?", (name,)).fetchone()
    if row:
        return row[0]
    count = conn.execute("SELECT COUNT(*) FROM todo_groups").fetchone()[0]
    group_id = uuid.uuid4().hex[:8]
    conn.execute("INSERT INTO todo_groups (id, name, colour, ord) VALUES (?, ?, ?, ?)",
                 (group_id, name, colour or TODO_GROUP_COLOURS[count % len(TODO_GROUP_COLOURS)], count))
    return group_id


def add_todo_group(name, colour=None):
    """Add a to-do category (or return the one already called that); returns it."""
    name = str(name).strip()
    if not name:
        raise ValueError("A category needs a name.")
    with db() as conn:
        group_id = _add_group(conn, name, colour)
    return next(g for g in todo_groups() if g["id"] == group_id)


def link_goal_group(conn, goal_id, title):
    """Setting a goal ("Get a job") makes it a to-do category too: the one already called that, if there
    is one, else a new one. Returns its id."""
    row = conn.execute("SELECT id FROM todo_groups WHERE goal_id = ?", (goal_id,)).fetchone()
    if row:
        return row[0]
    group_id = _add_group(conn, str(title).strip())
    conn.execute("UPDATE todo_groups SET goal_id = ? WHERE id = ? AND goal_id IS NULL", (goal_id, group_id))
    return group_id


def rename_goal_group(conn, goal_id, title):
    """A goal's new title renames its category (unless another category already has that name)."""
    clash = conn.execute("SELECT 1 FROM todo_groups WHERE name = ? AND goal_id IS NOT ?",
                         (title, goal_id)).fetchone()
    if not clash:
        conn.execute("UPDATE todo_groups SET name = ? WHERE goal_id = ?", (title, goal_id))


def goal_todo_group(goal_id):
    """The to-do category of a goal, or None."""
    return next((g for g in todo_groups() if g["goal_id"] == goal_id), None)


def update_todo_group(group_id, name=None, colour=None):
    """Rename a to-do category and/or change its colour."""
    with db() as conn:
        if name is not None and str(name).strip():
            conn.execute("UPDATE todo_groups SET name = ? WHERE id = ?", (str(name).strip(), group_id))
        if colour:
            conn.execute("UPDATE todo_groups SET colour = ? WHERE id = ?", (colour, group_id))


def delete_todo_group(group_id):
    """Delete a to-do category; its to-dos stay, with no category."""
    with db() as conn:
        conn.execute("UPDATE todos SET group_id = NULL WHERE group_id = ?", (group_id,))
        conn.execute("DELETE FROM todo_groups WHERE id = ?", (group_id,))


def move_target(todo, period, today=None):
    """
    Where a to-do lands when moved to another kind of period: the period containing
    today if its current period includes today, otherwise its own first day.
    """
    today = today or local_today()
    start = date.fromisoformat(todo["period_start"])
    anchor = today if start <= today <= end_of_period(todo["period"], start) else start
    return start_of_period(period, anchor)


def move_todo(todo_id, period, today=None):
    """Move a to-do to another kind of period (to the end of that list). Returns the new period start."""
    todo = get_todo(todo_id)
    if not todo:
        return None
    start = move_target(todo, period, today).isoformat()
    with db() as conn:
        conn.execute("UPDATE todos SET period = ?, period_start = ?, ord = ? WHERE id = ?",
                     (period, start, _next_ord(conn, period, start), todo_id))
    return start


def delete_todo(todo_id):
    with db() as conn:
        conn.execute("DELETE FROM todos WHERE id = ?", (todo_id,))
        conn.execute("DELETE FROM tt_todo_links WHERE todo_id = ?", (todo_id,))


def reorder_todos(ids):
    """Put to-dos in this order (ids of one list, first to last). They take the places they had between
    them, so a list filtered to one category reorders without moving the to-dos it hides."""
    with db() as conn:
        marks = ",".join("?" * len(ids))
        slots = sorted(r[0] for r in conn.execute(f"SELECT ord FROM todos WHERE id IN ({marks})", ids))
        if len(slots) != len(ids) or len(set(slots)) != len(slots):
            slots = range(len(ids))                     # unknown ids or ties: number them from the top
        conn.executemany("UPDATE todos SET ord = ? WHERE id = ?", list(zip(slots, ids)))


def _titles(conn, period, start):
    rows = conn.execute("SELECT lower(title) FROM todos WHERE period = ? AND period_start = ?", (period, start))
    return {r[0] for r in rows}


def roll_todos(today=None):
    """
    Give every repeating to-do an unticked copy in the current period, once per
    period (todo_rollover remembers the last one done, so a copy the user deletes
    stays deleted). A to-do repeats if the latest to-do with its title in an earlier
    period has repeat on. Titles already in the current period are never doubled.
    Returns how many copies were made.
    """
    today = today or local_today()
    made = 0
    with db() as conn:
        for period in TODO_PERIODS:
            start = start_of_period(period, today).isoformat()
            done = conn.execute("SELECT period_start FROM todo_rollover WHERE period = ?", (period,)).fetchone()
            if done and done[0] >= start:
                continue
            latest = {}
            for title, notes, repeat, minutes, group_id in conn.execute(
                'SELECT title, notes, "repeat", minutes, group_id FROM todos WHERE period = ? AND period_start < ? '
                "ORDER BY period_start DESC, ord",
                (period, start),
            ):
                latest.setdefault(title.lower(), (title, notes, repeat, minutes, group_id))
            existing = _titles(conn, period, start)
            for key, (title, notes, repeat, minutes, group_id) in latest.items():
                if repeat and key not in existing:
                    _insert_todo(conn, title, period, start, notes, True, minutes=minutes, group_id=group_id)
                    made += 1
            conn.execute("INSERT OR REPLACE INTO todo_rollover VALUES (?, ?)", (period, start))
    return made


def carry_over(period, start):
    """Copy a period's unticked to-dos into the next period (skipping titles already there). Returns the count."""
    start = start_of_period(period, start).isoformat()
    nxt = shift_period(period, start, 1).isoformat()
    copied = 0
    with db() as conn:
        existing = _titles(conn, period, nxt)
        rows = conn.execute(
            'SELECT title, notes, "repeat", minutes, group_id FROM todos '
            "WHERE period = ? AND period_start = ? AND done = 0 ORDER BY ord",
            (period, start),
        ).fetchall()
        for title, notes, repeat, minutes, group_id in rows:
            if title.lower() not in existing:
                _insert_todo(conn, title, period, nxt, notes, repeat, minutes=minutes, group_id=group_id)
                existing.add(title.lower())
                copied += 1
    return copied


def todos_progress(period, start):
    """(done, total) for one period."""
    todos = todos_for(period, start)
    return sum(g["done"] for g in todos), len(todos)


def load_todos():
    """Every to-do, for export: one row each, oldest period first."""
    return _read(f"SELECT {TODO_COLS} FROM todos ORDER BY period_start, period, ord")


def save_todos(df, replace=False):
    """
    Import to-dos (the export's columns; only title and period are required).
    Rows with an id that already exists update that to-do; replace=True wipes all to-dos first.
    Returns how many rows were imported.
    """
    count = 0
    with db() as conn:
        if replace:
            conn.execute("DELETE FROM todos")
            conn.execute("DELETE FROM todo_rollover")
        for row in df.to_dict("records"):
            title = _clean(row.get("title"), str)
            period = (_clean(row.get("period"), str) or "").strip().lower()
            if not title or period not in TODO_PERIODS:
                continue
            day = _clean(row.get("period_start"), str)
            start = start_of_period(period, pd.to_datetime(day).date() if day else local_today()).isoformat()
            done = _is_ticked(row.get("done"))
            ord_ = _clean(row.get("ord"), int)
            due = _clean(row.get("due"), str)
            conn.execute(
                f"INSERT OR REPLACE INTO todos ({TODO_COLS}) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (_clean(row.get("id"), str) or uuid.uuid4().hex, title.strip(), _clean(row.get("notes"), str),
                 period, start, int(done), _clean(row.get("done_at"), str) if done else None,
                 int(_is_ticked(row.get("repeat"))),
                 _next_ord(conn, period, start) if ord_ is None else ord_,
                 _clean(row.get("created_at"), str) or stamp(),
                 pd.to_datetime(due).date().isoformat() if due else None, _clean(row.get("minutes"), int),
                 _clean(row.get("group_id"), str)),
            )
            count += 1
    return count


# --- To-dos on the timetable (the link itself: timetable.link_todo) ---

def todo_slots(todo, day, start, now=None):
    """Where scheduling a to-do at day/start puts it: (track, s, e). Its length is its minutes (30 if not
    set), rounded up to whole slots; the track is the day's live one (its Plan, or its Actual once started)."""
    from .days import live_track
    from .grid import slot_count, slot_of
    s = slot_of(start)
    if not 0 <= s < slot_count():
        raise ValueError("That time isn't on the timetable.")
    n = -(-(todo.get("minutes") or TODO_MINUTES) // 30)
    return live_track(day, now), s, min(s + max(n, 1), slot_count())


def schedule_todo(todo_id, day, start, category_id=None, now=None, new_id=None):
    """Paint a to-do onto the timetable at day/start (titled with it) and link it: one block per to-do,
    so scheduling it again moves the link. Returns the block's (track, start, end)."""
    from .categories import match_category
    from .grid import slot_time
    from .timetable import link_todo, paint
    todo = get_todo(todo_id)
    if not todo:
        raise ValueError("There's no such to-do.")
    day = _as_date(day).isoformat()
    track, s, e = todo_slots(todo, day, start, now)
    cid = category_id or match_category(todo["title"])
    with db() as conn:
        paint(day, track, s, e, {"label": todo["title"], "category_id": cid, "details": None}, new_id=new_id, conn=conn)
        link_todo(todo_id, day, slot_time(s), slot_time(e), conn=conn)
    if todo["done"]:
        _mark_block(todo_id, True)
    return track, slot_time(s), slot_time(e)
