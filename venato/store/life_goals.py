"""
Goals: the long-term plans ("Get fit", "Land a grad job") over 3, 6 or 12 months (or to any end date).

Under each goal sit
  - targets: the measurable ones with their own deadline ("Gym 40 sessions by 31/03"), kept in the `goals`
    table (goals.py: every mechanic there, pace, hours, habits, deadline plans, works the same). A target
    belongs to at most one goal (goals.life_goal_id; NULL = "not under a goal").
  - to-dos: through to-do categories. A goal is a to-do category (todo_groups.life_goal_id), like a target
    is (todo_groups.goal_id); the to-dos in its category and in its targets' categories are its to-dos.

In code a long-term goal is a "life goal" and a "goal" is a target (the table kept its name).
Progress: the mean of its targets' progress (each capped at 100%); with no targets, its to-dos done / all.
"""

import calendar
import sqlite3
import uuid
from datetime import date

from .database import KEEP, _read, db
from .dates import _as_date, local_today, stamp
from .history import _clean

HORIZONS = (3, 6, 12)                # months: the quick choices (any end date works too)
# A goal's colour: its own to-do category's colour, so its to-dos, Home's tile and the Goals page all agree.
# New goals take the first of these no running goal has. No red: red means "behind" across the app.
GOAL_COLOURS = ("#F76B15", "#E5A00D", "#30A46C", "#12A594", "#3E63DD", "#8E4EC6", "#D6409F", "#6F6E77")
GOAL_COLOUR_NAMES = dict(zip(GOAL_COLOURS, ("Orange", "Amber", "Green", "Teal", "Blue", "Violet", "Pink", "Slate")))
LIFE_GOAL_COLS = "id, title, why, start, end_date, ord, created_at, archived"


def months_on(day, n):
    """The same day n months later (the month's last day if it's shorter)."""
    day = _as_date(day)
    m = day.month - 1 + n
    y, m = day.year + m // 12, m % 12 + 1
    return date(y, m, min(day.day, calendar.monthrange(y, m)[1]))


def horizon_of(g):
    """3, 6 or 12 when a goal's span is exactly that many months, else None (a custom end date)."""
    return next((n for n in HORIZONS if months_on(g["start"], n).isoformat() == g["end_date"]), None)


def _row(row):
    g = dict(row)
    g["archived"] = bool(g["archived"])
    return g


def _life_goals(where="1", params=()):
    with db() as conn:
        conn.row_factory = sqlite3.Row
        rows = conn.execute(f"SELECT {LIFE_GOAL_COLS} FROM life_goals WHERE {where} ORDER BY ord, created_at",
                            params).fetchall()
    return [_row(r) for r in rows]


def life_goals(day=None, include_past=False):
    """The goals still running on `day` (default today: not archived, end on or after it), in list order.
    include_past=True: every goal that isn't archived."""
    if include_past:
        return _life_goals("archived = 0")
    return _life_goals("archived = 0 AND end_date >= ?", (_as_date(day or local_today()).isoformat(),))


def life_goals_past(day=None):
    """Goals that ended before `day` (default today) or were archived, the latest end first."""
    rows = _life_goals("archived = 1 OR end_date < ?", (_as_date(day or local_today()).isoformat(),))
    return sorted(rows, key=lambda g: g["end_date"], reverse=True)


def get_life_goal(life_goal_id):
    rows = _life_goals("id = ?", (life_goal_id,))
    return rows[0] if rows else None


def find_life_goal(title):
    """The goal with this title (any case), else the one whose title contains it; None if none or several."""
    want = str(title or "").strip().lower()
    if not want:
        return None
    rows = life_goals(include_past=True)
    exact = [g for g in rows if g["title"].lower() == want]
    if exact:
        return exact[0]
    part = [g for g in rows if want in g["title"].lower()]
    return part[0] if len(part) == 1 else None


def _span(start, end=None, months=None):
    start = _as_date(start or local_today())
    if end is None:
        if months is None:
            raise ValueError("A goal needs an end date or a length in months.")
        end = months_on(start, int(months))
    end = _as_date(end)
    if end <= start:
        raise ValueError("A goal's end has to be after its start.")
    return start.isoformat(), end.isoformat()


def _link_group(conn, life_goal_id, title):
    """A goal is a to-do category too: the one already called that (if it isn't another goal's), else a new one."""
    from .todos import _add_group
    row = conn.execute("SELECT id FROM todo_groups WHERE life_goal_id = ?", (life_goal_id,)).fetchone()
    if row:
        return row[0]
    group_id = _add_group(conn, str(title).strip(), _free_colour(conn))
    conn.execute("UPDATE todo_groups SET life_goal_id = ? WHERE id = ? AND life_goal_id IS NULL",
                 (life_goal_id, group_id))
    return group_id


def add_life_goal(title, months=None, end=None, start=None, why=None, life_goal_id=None):
    """Add a goal running from `start` (default today) for `months` (3, 6, 12, or any) or to `end`; returns it."""
    title = str(title or "").strip()
    if not title:
        raise ValueError("A goal needs a title.")
    first, last = _span(start, end, months)
    life_goal_id = life_goal_id or uuid.uuid4().hex
    with db() as conn:
        conn.execute(
            f"INSERT INTO life_goals ({LIFE_GOAL_COLS}) VALUES (?, ?, ?, ?, ?, "
            "(SELECT COALESCE(MAX(ord) + 1, 0) FROM life_goals), ?, 0)",
            (life_goal_id, title, (why or "").strip() or None, first, last, stamp()))
        _link_group(conn, life_goal_id, title)
    return get_life_goal(life_goal_id)


def update_life_goal(life_goal_id, title=KEEP, why=KEEP, start=KEEP, end=KEEP, months=None, archived=KEEP):
    """Change a goal's title, why, start or end (or, with months, end = start + that many months), or archive it."""
    g = get_life_goal(life_goal_id)
    if not g:
        raise ValueError("There's no such goal.")
    fields = {}
    if title is not KEEP:
        fields["title"] = str(title or "").strip()
        if not fields["title"]:
            raise ValueError("A goal needs a title.")
    if why is not KEEP:
        fields["why"] = (why or "").strip() or None
    if start is not KEEP or end is not KEEP or months is not None:
        s = g["start"] if start is KEEP else start
        fields["start"], fields["end_date"] = _span(s, None if months is not None else (g["end_date"] if end is KEEP else end),
                                                    months)
    if archived is not KEEP:
        fields["archived"] = 1 if archived else 0
    if not fields:
        return g
    with db() as conn:
        conn.execute(f"UPDATE life_goals SET {', '.join(f'{k} = ?' for k in fields)} WHERE id = ?",
                     (*fields.values(), life_goal_id))
        if "title" in fields:
            clash = conn.execute("SELECT 1 FROM todo_groups WHERE name = ? AND life_goal_id IS NOT ?",
                                 (fields["title"], life_goal_id)).fetchone()
            if not clash:
                conn.execute("UPDATE todo_groups SET name = ? WHERE life_goal_id = ?", (fields["title"], life_goal_id))
    return get_life_goal(life_goal_id)


def delete_life_goal(life_goal_id):
    """Delete a goal. Its targets and to-dos stay (no longer under a goal); so does its to-do category."""
    with db() as conn:
        conn.execute("UPDATE goals SET life_goal_id = NULL WHERE life_goal_id = ?", (life_goal_id,))
        conn.execute("UPDATE todo_groups SET life_goal_id = NULL WHERE life_goal_id = ?", (life_goal_id,))
        conn.execute("DELETE FROM life_goals WHERE id = ?", (life_goal_id,))


def reorder_life_goals(ids):
    with db() as conn:
        conn.executemany("UPDATE life_goals SET ord = ? WHERE id = ?", [(i, gid) for i, gid in enumerate(ids)])


def set_target_goal(target_id, life_goal_id):
    """Put a target under a goal (None: under none)."""
    with db() as conn:
        if life_goal_id and not conn.execute("SELECT 1 FROM life_goals WHERE id = ?", (life_goal_id,)).fetchone():
            raise ValueError("There's no such goal.")
        conn.execute("UPDATE goals SET life_goal_id = ? WHERE id = ?", (life_goal_id or None, target_id))


def life_goal_group(life_goal_id):
    """A goal's own to-do category ({id, name, colour, goal_id, life_goal_id}), or None."""
    from .todos import todo_groups
    return next((g for g in todo_groups() if g.get("life_goal_id") == life_goal_id), None)


def _free_colour(conn):
    """The first goal colour no other goal's category has (they cycle once all are taken)."""
    used = [r[0].upper() for r in conn.execute("SELECT colour FROM todo_groups WHERE life_goal_id IS NOT NULL")]
    return next((c for c in GOAL_COLOURS if c.upper() not in used), GOAL_COLOURS[len(used) % len(GOAL_COLOURS)])


def life_goal_colours():
    """{goal id: "#RRGGBB"} for every goal with a category (a goal always has one unless the user deleted it)."""
    with db() as conn:
        return {lid: colour for lid, colour in
                conn.execute("SELECT life_goal_id, colour FROM todo_groups WHERE life_goal_id IS NOT NULL")}


def life_goal_colour(life_goal_id):
    return life_goal_colours().get(life_goal_id) or GOAL_COLOURS[0]


def set_life_goal_colour(life_goal_id, colour):
    """Change a goal's colour (its category's, so its to-dos follow)."""
    colour = str(colour or "").strip()
    if not (len(colour) == 7 and colour.startswith("#")):
        raise ValueError("A colour is #RRGGBB.")
    group_id = ensure_life_goal_group(life_goal_id)
    with db() as conn:
        conn.execute("UPDATE todo_groups SET colour = ? WHERE id = ?", (colour, group_id))


def ensure_life_goal_group(life_goal_id):
    """The id of a goal's own to-do category, making it again if the user deleted it."""
    g = get_life_goal(life_goal_id)
    if not g:
        raise ValueError("There's no such goal.")
    with db() as conn:
        return _link_group(conn, life_goal_id, g["title"])


def life_goal_group_ids(life_goal_id):
    """The to-do categories whose to-dos count for a goal: its own and its targets'."""
    with db() as conn:
        return [r[0] for r in conn.execute(
            """SELECT id FROM todo_groups WHERE life_goal_id = ?
               OR goal_id IN (SELECT id FROM goals WHERE life_goal_id = ?) ORDER BY ord, name""",
            (life_goal_id, life_goal_id))]


def group_life_goals():
    """{to-do category id: goal id} for every category under a goal (its own, or one of its targets')."""
    with db() as conn:
        rows = conn.execute(
            """SELECT t.id, COALESCE(t.life_goal_id, g.life_goal_id) FROM todo_groups t
               LEFT JOIN goals g ON g.id = t.goal_id
               WHERE t.life_goal_id IS NOT NULL OR g.life_goal_id IS NOT NULL""").fetchall()
    return {gid: lid for gid, lid in rows}


def life_goal_todos(life_goal_id, open_only=False):
    """The to-dos under a goal (any period), open ones first then by due day."""
    from .todos import TODO_COLS, _todo
    groups = life_goal_group_ids(life_goal_id)
    if not groups:
        return []
    marks = ", ".join("?" * len(groups))
    with db() as conn:
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            f"SELECT {TODO_COLS} FROM todos WHERE group_id IN ({marks}) {'AND done = 0' if open_only else ''} "
            "ORDER BY done, COALESCE(due, period_start), ord, created_at", groups).fetchall()
    return [_todo(r) for r in rows]


def target_todos(target_id, open_only=False):
    """The to-dos in a target's own to-do category, open ones first then by due day."""
    from .todos import TODO_COLS, _todo, goal_todo_group
    group = goal_todo_group(target_id)
    if not group:
        return []
    with db() as conn:
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            f"SELECT {TODO_COLS} FROM todos WHERE group_id = ? {'AND done = 0' if open_only else ''} "
            "ORDER BY done, COALESCE(due, period_start), ord, created_at", (group["id"],)).fetchall()
    return [_todo(r) for r in rows]


def ensure_target_group(target_id):
    """The id of a target's own to-do category, making it again if the user deleted it."""
    from .goals import get_goal
    from .todos import link_goal_group
    t = get_goal(target_id)
    if not t:
        raise ValueError("There's no such target.")
    with db() as conn:
        return link_goal_group(conn, target_id, t["title"])


def next_step(life_goal_id, today=None, targets=None):
    """What to do next for a goal: {"target": the open target due soonest or None, "todo": its first open to-do,
    else the goal's own first open to-do, or None}. None when there's nothing open at all."""
    today = _as_date(today or local_today()).isoformat()
    targets = life_goal_targets(life_goal_id) if targets is None else targets
    target = next((t for t in targets if t["due"] >= today and (not t["target"] or t["value"] < t["target"])), None)
    todo = None
    if target:
        todo = next(iter(target_todos(target["id"], open_only=True)), None)
    if not todo:
        group = life_goal_group(life_goal_id)
        todo = next((t for t in life_goal_todos(life_goal_id, open_only=True)
                     if group and t["group_id"] == group["id"]), None)
    if not target and not todo:
        return None
    return {"target": target, "todo": todo}


def life_goal_targets(life_goal_id, day=None):
    """The targets under a goal that are still open (not closed), soonest deadline first, each with `value`."""
    from .goals import _goals_where
    return _goals_where("life_goal_id = ?", (life_goal_id,), order="due, ord, created_at")


def unparented_targets(day=None):
    """Targets not past their deadline and under no goal (deadline plans included), in list order."""
    from .goals import _goals_where
    return _goals_where("life_goal_id IS NULL AND due >= ?", (_as_date(day or local_today()).isoformat(),))


def _fraction(t):
    return min(t["value"] / t["target"], 1.0) if t["target"] else 0.0


def life_goal_progress(life_goal_id, targets=None, todos=None):
    """{"fraction": 0..1, "targets": n, "targets_done": n, "todos": n, "todos_done": n}.
    fraction: the mean of the targets' progress, or (with none) to-dos done out of all of them."""
    targets = life_goal_targets(life_goal_id) if targets is None else targets
    todos = life_goal_todos(life_goal_id) if todos is None else todos
    done = sum(1 for t in todos if t["done"])
    if targets:
        frac = sum(_fraction(t) for t in targets) / len(targets)
    else:
        frac = done / len(todos) if todos else 0.0
    return {"fraction": frac, "targets": len(targets), "targets_done": sum(_fraction(t) >= 1 for t in targets),
            "todos": len(todos), "todos_done": done}


def time_left(g, today=None):
    """("12 weeks left" / "ends today" / "ended" / "starts 01/12"), for people."""
    from venato import regional
    today = _as_date(today or local_today())
    start, end = _as_date(g["start"]), _as_date(g["end_date"])
    if start > today:
        return f"starts {regional.short_date(start, today)}"
    days = (end - today).days
    if days < 0:
        return "ended"
    if days == 0:
        return "ends today"
    if days < 14:
        return "1 day left" if days == 1 else f"{days} days left"
    if days < 70:
        return f"{days // 7} weeks left"
    return f"{round(days / 30.4)} months left"


def load_life_goals():
    """Every goal, for export."""
    return _read(f"SELECT {LIFE_GOAL_COLS} FROM life_goals ORDER BY ord, created_at")


def save_life_goals(df, replace=False):
    """Import goals (the export's columns; `title`, `start` and `end_date` are required). A row with an existing
    id updates that goal; replace=True deletes every goal first (targets and to-dos stay). Returns the count."""
    count = 0
    if replace:
        for g in life_goals(include_past=True) + [g for g in life_goals_past() if g["archived"]]:
            delete_life_goal(g["id"])
    for row in df.to_dict("records"):
        title = _clean(row.get("title"), str)
        start, end = _clean(row.get("start"), str), _clean(row.get("end_date"), str)
        if not title or not title.strip() or not start or not end:
            continue
        try:
            first, last = _span(start[:10], end[:10])
        except ValueError:
            continue
        gid = _clean(row.get("id"), str) or uuid.uuid4().hex
        with db() as conn:
            conn.execute(
                f"INSERT INTO life_goals ({LIFE_GOAL_COLS}) VALUES (?, ?, ?, ?, ?, ?, ?, ?) "
                "ON CONFLICT(id) DO UPDATE SET title = excluded.title, why = excluded.why, start = excluded.start, "
                "end_date = excluded.end_date, ord = excluded.ord, archived = excluded.archived",
                (gid, title.strip(), _clean(row.get("why"), str), first, last,
                 _clean(row.get("ord"), int) if _clean(row.get("ord"), int) is not None else count,
                 _clean(row.get("created_at"), str) or stamp(), 1 if _clean(row.get("archived"), int) else 0))
            _link_group(conn, gid, title)
        count += 1
    return count
