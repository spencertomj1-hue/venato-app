"""
Tools for to-dos: tick-off lists for a day, a week or a month, found by a loosely typed title.
"""

from venato import store

from .common import PERIOD_NAMES, Pending, Result, ToolError, _best_match, _period, _period_day


def todo_list_name(period, start):
    """"this week's to-dos (26 Oct to 1 Nov)", "today's to-dos", "the November 2026 to-dos"."""
    title = store.period_title(period, start)
    named = {"Today": "today's", "Yesterday": "yesterday's", "Tomorrow": "tomorrow's"}.get(title)
    if named:
        return f"{named} to-dos"
    if ": " in title:
        when, span = title.split(": ")
        return f"{when.lower()}'s to-dos ({span})"
    return f"the {title} to-dos"


def describe_todo(t):
    return f"'{t['title']}' in {todo_list_name(t['period'], t['period_start'])}"


def add_todo(title, period, date=None, repeat=False, notes=None, life_goal=None, target=None, effort=None):
    """Add a to-do to the period containing `date` (default today); with life_goal, under that long-term goal; with
    target, a step of that target (a milestone's to-dos are its progress). effort: 1-10 (default 5)."""
    from .goals import _effort, _find_goal
    effort = _effort(effort)
    title, per = str(title).strip(), _period(period)
    if not title:
        raise ToolError("The to-do needs a title.")
    day = _period_day(date)
    store.roll_todos()
    start = store.start_of_period(per, day)
    if any(t["title"].lower() == title.lower() for t in store.todos_for(per, start)):
        return Result(f"'{title}' is already in {todo_list_name(per, start)}.")
    group = None
    step = None
    if target:
        step = _find_goal(target)
        group = store.ensure_target_group(step["id"])
    elif life_goal:
        from .life_goals import find_life_goal
        life = find_life_goal(life_goal)
        group = store.ensure_life_goal_group(life["id"])
    t = store.add_todo(title, per, day, notes=notes, repeat=bool(repeat), group_id=group, effort=effort)
    extra = f", repeating every {PERIOD_NAMES[per]}" if repeat else ""
    extra += f", a step of '{step['title']}'" if step else f", under the goal '{life['title']}'" if life_goal else ""
    extra += f", effort {effort}" if effort else ""
    return Result(f"Added '{t['title']}' to {todo_list_name(per, start)}{extra}.", changed=True)


def _current_todos(day, period=None):
    """To-dos in the periods containing `day` (all kinds, or just one)."""
    periods = [period] if period else store.TODO_PERIODS
    return [t for p in periods for t in store.todos_for(p, store.start_of_period(p, day))]


def _find_todo(todo, period=None, date=None):
    """A to-do by id, or by title in the periods containing `date` (default today)."""
    store.roll_todos()
    found = store.get_todo(str(todo).strip())
    if found:
        return found
    pool = _current_todos(_period_day(date), _period(period) if period else None)
    matches = _best_match(pool, todo)
    if len(matches) == 1:
        return matches[0]
    if matches:
        options = "; ".join(f"id {t['id']}: {describe_todo(t)}" for t in matches)
        raise ToolError(f"More than one to-do matches '{todo}': {options}. Ask the user which one, or pass its id.")
    raise ToolError(f"There's no to-do matching '{todo}' in the current periods. "
                    "Use list_todos (with a date for other periods) to find it.")


def edit_todo(todo, period=None, date=None, title=None, notes=None, repeat=None, move_to=None, effort=None):
    """Change a to-do's title / notes / repeat / effort (1-10), and/or move it to the day, week or month list."""
    from .goals import _effort
    t = _find_todo(todo, period, date)
    changes = {k: v for k, v in (("title", title), ("notes", notes), ("repeat", repeat), ("effort", _effort(effort)))
               if v is not None}
    try:
        store.update_todo(t["id"], **changes)
    except ValueError as e:
        raise ToolError(str(e))
    if move_to:
        store.move_todo(t["id"], _period(move_to))
    if not changes and not move_to:
        return Result("Nothing to change: give a new title, notes, repeat, effort or move_to.")
    return Result(f"Updated the to-do: {describe_todo(store.get_todo(t['id']))}.", changed=True)


def complete_todo(todo, period=None, date=None):
    t = _find_todo(todo, period, date)
    if t["done"]:
        return Result(f"{describe_todo(t)} is already ticked off.")
    store.set_todo_done(t["id"], True)
    done, total = store.todos_progress(t["period"], t["period_start"])
    return Result(f"Ticked off {describe_todo(t)} ({done}/{total} done).", changed=True)


def uncomplete_todo(todo, period=None, date=None):
    t = _find_todo(todo, period, date)
    if not t["done"]:
        return Result(f"{describe_todo(t)} isn't ticked.")
    store.set_todo_done(t["id"], False)
    return Result(f"Unticked {describe_todo(t)}.", changed=True)


def delete_todo(todo, period=None, date=None, confirmed=False):
    t = _find_todo(todo, period, date)
    summary = f"Delete the to-do {describe_todo(t)}"
    if not confirmed:
        return Result("", pending=Pending(summary, lambda: delete_todo(t["id"], confirmed=True)))
    store.delete_todo(t["id"])
    return Result(f"Done: {summary}.", changed=True)


def list_todos(period=None, date=None):
    """To-dos (with ids) in the periods containing `date` (default today)."""
    store.roll_todos()
    day = _period_day(date)
    sections = []
    for per in ([_period(period)] if period else store.TODO_PERIODS):
        start = store.start_of_period(per, day)
        todos = store.todos_for(per, start)
        done = sum(t["done"] for t in todos)
        name = todo_list_name(per, start)
        lines = [f"{name[0].upper()}{name[1:]}: {done}/{len(todos)} done"]
        for t in todos:
            extras = [x for x in ("repeats" if t["repeat"] else None, f"notes: {t['notes']}" if t["notes"] else None) if x]
            lines.append(f"- [{'x' if t['done'] else ' '}] {t['title']} (id {t['id']}"
                         + "".join(f"; {x}" for x in extras) + ")")
        sections.append("\n".join(lines))
    return Result("\n\n".join(sections))
