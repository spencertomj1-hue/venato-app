"""
Tools for long-term goals: plans over 3, 6 or 12 months (or to any end date) with targets (the measurable
goals of goals.py) and to-dos under them.
"""

from venato import store

from .common import Pending, Result, ToolError, _best_match, _day


def describe_life_goal(g):
    from venato import regional
    p = store.life_goal_progress(g["id"])
    span = f"{regional.short_date(g['start'])} to {regional.short_date(g['end_date'])}"
    return f"'{g['title']}' ({span}, {store.time_left(g)}, {round(100 * p['fraction'])}%)"


def find_life_goal(goal):
    """A long-term goal by id, or by title (running ones first, then past ones)."""
    found = store.get_life_goal(str(goal).strip())
    if found:
        return found
    for pool in (store.life_goals(), store.life_goals_past()):
        matches = _best_match(pool, goal)
        if len(matches) == 1:
            return matches[0]
        if matches:
            options = "; ".join(f"id {g['id']}: '{g['title']}'" for g in matches)
            raise ToolError(f"More than one goal matches '{goal}': {options}. Ask the user which one, or pass its id.")
    raise ToolError(f"There's no long-term goal matching '{goal}'. Use list_life_goals to find it.")


def _months(months):
    if months is None:
        return None
    try:
        months = int(months)
    except (TypeError, ValueError):
        raise ToolError("months must be a whole number, e.g. 3, 6 or 12.")
    if months <= 0:
        raise ToolError("months must be more than 0.")
    return months


def add_life_goal(title, months=None, end=None, why=None, start=None):
    """A long-term goal from `start` (default today) for `months` (3, 6, 12…) or to `end`."""
    title = str(title or "").strip()
    if not title:
        raise ToolError("The goal needs a title.")
    if months is None and end is None:
        raise ToolError("Say how long: months (3, 6 or 12) or an end date.")
    if any(g["title"].lower() == title.lower() for g in store.life_goals()):
        return Result(f"There's already a goal called '{title}'.")
    try:
        g = store.add_life_goal(title, months=_months(months), end=_day(end) if end else None,
                                start=_day(start) if start else None, why=why)
    except ValueError as e:
        raise ToolError(str(e))
    return Result(f"Added the goal {describe_life_goal(g)}. Add targets (add_goal with life_goal) "
                  "or to-dos (add_todo with life_goal) under it.", changed=True)


def edit_life_goal(goal, title=None, why=None, months=None, end=None, start=None, archive=None):
    """Change a long-term goal's title, why, start, length (months from its start) or end date, or archive it."""
    g = find_life_goal(goal)
    changes = {}
    if title:
        changes["title"] = title
    if why is not None:
        changes["why"] = why
    if start:
        changes["start"] = _day(start)
    if months is not None:
        changes["months"] = _months(months)
    elif end:
        changes["end"] = _day(end)
    if archive is not None:
        changes["archived"] = bool(archive)
    if not changes:
        raise ToolError("Say what to change: title, why, start, months, end or archive.")
    try:
        g = store.update_life_goal(g["id"], **changes)
    except ValueError as e:
        raise ToolError(str(e))
    return Result(f"Updated: {describe_life_goal(g)}.", changed=True)


def delete_life_goal(goal, confirmed=False):
    g = find_life_goal(goal)
    summary = f"Delete the goal '{g['title']}' (its targets and to-dos stay, under no goal)"
    if not confirmed:
        return Result("", pending=Pending(summary, lambda: delete_life_goal(g["id"], confirmed=True)))
    store.delete_life_goal(g["id"])
    return Result(f"Done: {summary}.", changed=True)


def list_life_goals():
    """Running long-term goals with ids, progress, their targets and open to-dos; then the targets under none."""
    goals = store.life_goals()
    lines = ["Long-term goals:" + ("" if goals else " none")]
    for g in goals:
        targets = store.life_goal_targets(g["id"])
        todos = store.life_goal_todos(g["id"], open_only=True)
        p = store.life_goal_progress(g["id"], targets=targets)
        why = f" Why: {g['why']}." if g["why"] else ""
        lines.append(f"- {g['title']} ({g['start']} to {g['end_date']}, {store.time_left(g)}, "
                     f"{round(100 * p['fraction'])}%, id {g['id']}).{why}")
        for t in targets:
            lines.append(f"  - target {t['title']} {store.goal_title_due(t['due'])}: {store._num(t['value'])}/"
                         f"{store._num(t['target'])}{' ' + t['unit'] if t['unit'] else ''} (id {t['id']})")
        for t in todos:
            lines.append(f"  - to-do {t['title']} (id {t['id']})")
    loose = store.unparented_targets()
    if loose and goals:
        lines.append("Targets under no goal: " + ", ".join(t["title"] for t in loose))
    return Result("\n".join(lines))
