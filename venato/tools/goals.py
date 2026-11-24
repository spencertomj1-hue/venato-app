"""
Tools for targets (called goals in the tool names, from before long-term goals): measurable, with a deadline,
and their progress. A target can sit under a long-term goal (life_goals.py).
"""

from datetime import date

from venato import store

from .common import Pending, Result, ToolError, _best_match, _day, _period, _period_day


def _amount(goal, n=None):
    """"7/12 sessions" for a goal (or n of its unit); a milestone: "60% (3 of 5 steps)", "done", "not done"."""
    n = goal["value"] if n is None else n
    if goal.get("milestone"):
        done, total = goal.get("steps") or (0, 0)
        pct = f"{round(100 * min(float(n), 1))}%"
        if goal.get("self_rated"):
            return f"{pct}, self-rated"
        return f"{pct} ({done} of {total} steps)" if total else ("done" if float(n) >= 1 else "not done")
    return f"{store._num(n)}/{goal['target']}" + (f" {goal['unit']}" if goal["unit"] else "")


def describe_goal(g):
    when = store.goal_title_due(g["due"])
    if g.get("milestone"):
        return f"'{g['title']}' (milestone {when}: {_amount(g)}, effort {store.effort(g)})"
    how = f", counted from the habit {g['habit']}" if g["habit"] else ""
    if g.get("category"):
        how = f", counted from Actual hours of {g['label'] + ' (' + g['category'] + ')' if g.get('label') else g['category']}"
    return f"'{g['title']}' ({when}: {_amount(g)}{how})"


def _habit_id(name):
    if not name:
        return None
    found = store.find_habit(str(name))
    if not found:
        names = ", ".join(n for _, n in store.get_habits()) or "none yet"
        raise ToolError(f"There's no habit called '{name}'. Existing habits: {names}.")
    return found[0]


def _find_goal(goal, period=None, date=None):
    """A goal by id, or by title among those not past their deadline on `date` (default today)."""
    found = store.get_goal(str(goal).strip())
    if found:
        return found
    pool = store.goals_open(_period_day(date))
    matches = _best_match(pool, goal)
    if len(matches) == 1:
        return matches[0]
    if matches:
        options = "; ".join(f"id {g['id']}: {describe_goal(g)}" for g in matches)
        raise ToolError(f"More than one goal matches '{goal}': {options}. Ask the user which one, or pass its id.")
    raise ToolError(f"There's no current goal matching '{goal}'. Use list_goals to find it.")


def _goal_category(category):
    cid = store.resolve_category(category=str(category))
    if cid is None:
        names = ", ".join(store.load_categories()["name"])
        if not names:
            raise ToolError("There are no categories yet. Ask the user for a name, then create it with edit_category (create=true).")
        raise ToolError(f"There's no category '{category}'. Categories: {names}.")
    return cid


def _due(due):
    try:
        return date.fromisoformat(_day(due))
    except (TypeError, ValueError):
        raise ToolError("due must be a date, YYYY-MM-DD.")


def _life_goal_id(life_goal):
    """A long-term goal's id from its title or id ("" / "none": no goal)."""
    if life_goal is None:
        return None
    if str(life_goal).strip().lower() in ("", "none"):
        return ""
    from .life_goals import find_life_goal
    return find_life_goal(life_goal)["id"]


def _effort(effort):
    try:
        return store.check_effort(effort)
    except (TypeError, ValueError):
        raise ToolError("effort goes from 1 (tiny) to 10 (huge); 2 small, 5 medium, 8 big.")


def add_goal(title, target=None, period=None, unit=None, habit=None, date=None, category=None, label=None, due=None,
             life_goal=None, effort=None, milestone=False):
    """A measurable goal with a deadline (`due`), from today (or `date`). Without a deadline, `period`
    "monthly" / "yearly" makes it due at the end of the month / year (default: this month). With a
    category (and optionally an activity label) it counts the timetable's Actual hours instead of a hand-kept number.
    milestone=True: a qualitative target (no number): its to-dos are its steps, or it's ticked when done.
    effort (1-10): how big a chunk of its long-term goal it is (default 5)."""
    effort = _effort(effort)
    day = _period_day(date)
    per = None
    if due is None:                              # the month's or year's: from its first day to its last
        per = _period(period or "monthly", store.GOAL_PERIODS)
        due = store.end_of_period(per, store.start_of_period(per, day))
    else:
        due = _due(due)
    if due < day:
        raise ToolError("The deadline can't be before the goal starts.")
    if milestone:
        target = 1
        if habit or category:
            raise ToolError("A milestone has no number, so it can't count a habit or timetable hours.")
    try:
        target = float(target)
    except (TypeError, ValueError):
        raise ToolError("target must be a number, e.g. 12 (or milestone=true for one with no number).")
    if target <= 0:
        raise ToolError("target must be more than 0.")
    title = str(title).strip()
    if not title:
        raise ToolError("The goal needs a title.")
    if any(g["title"].lower() == title.lower() and g["due"] == due.isoformat() for g in store.goals_open(day)):
        return Result(f"There's already a goal called '{title}' {store.goal_title_due(due)}.")
    if habit and category:
        raise ToolError("A goal counts either a habit's ticks or timetable hours, not both.")
    cid = _goal_category(category) if category else None
    life = _life_goal_id(life_goal) or None
    g = store.add_goal(title, per, day, target, (unit or "h") if cid else unit, _habit_id(habit),
                       category_id=cid, label=label if cid else None, due=None if per else due, life_goal_id=life,
                       effort=effort, milestone=bool(milestone))
    under = f" under the goal '{store.get_life_goal(life)['title']}'" if life else ""
    return Result(f"Added the target {describe_goal(g)}{under}.", changed=True)


def log_goal_progress(goal, amount=1, period=None, date=None):
    """Add to a goal's progress (a negative amount takes some off)."""
    g = _find_goal(goal, period, date)
    if g["milestone"]:
        raise ToolError(f"{describe_goal(g)} is a milestone: tick its to-dos, set_goal_progress(value=1) to tick "
                        "it done, or edit_goal(self_rating=...).")
    if g["habit"]:
        raise ToolError(f"{describe_goal(g)} counts the habit {g['habit']} automatically. "
                        "Tick the habit instead (set_habit).")
    if g["kind"] == "hours":
        raise ToolError(f"{describe_goal(g)} counts timetable hours automatically. Add the time to the Actual "
                        "track instead (add_block).")
    store.add_goal_progress(g["id"], float(amount))
    g = store.get_goal(g["id"])
    return Result(f"Updated {describe_goal(g)}.", changed=True)


def set_goal_progress(goal, value, period=None, date=None):
    """Set a goal's progress to an exact number."""
    g = _find_goal(goal, period, date)
    if g["kind"] != "count":
        raise ToolError(f"{describe_goal(g)} is counted automatically; it can't be set by hand.")
    old = g["value"]
    if g["milestone"]:
        value = 1 if float(value) >= 1 else 0          # a milestone's own progress is a tick
    store.set_goal_progress(g["id"], float(value))
    g = store.get_goal(g["id"])
    return Result(f"Set {describe_goal(g)} (was {store._num(old)}).", changed=True)


def edit_goal(goal, title=None, target=None, unit=None, habit=None, unlink_habit=False, period=None, date=None,
              category=None, label=None, unlink_category=False, due=None, start=None, life_goal=None,
              effort=None, milestone=None, self_rating=None, clear_self_rating=False):
    """Change a goal's title, target, unit, deadline, start (the day it counts from: earlier to count
    progress already made), what (a habit, timetable hours, or nothing) it counts, its effort (1-10), whether
    it's a milestone, or a milestone's self-rating (0-100%; clear_self_rating goes back to its to-dos)."""
    g = _find_goal(goal, period, date)
    changes = {}
    if effort is not None:
        changes["effort"] = _effort(effort)
    if milestone is not None:
        changes["milestone"] = bool(milestone)
    if self_rating is not None or clear_self_rating:
        if not (changes.get("milestone", g["milestone"])):
            raise ToolError("Only a milestone can be self-rated.")
        if self_rating is not None and not 0 <= float(self_rating) <= 100:
            raise ToolError("self_rating is a percentage, 0 to 100.")
        changes["self_rating"] = None if clear_self_rating else float(self_rating) / 100
    if start is not None:
        changes["start"] = _due(start)
    if due is not None:
        changes["due"] = _due(due)
    if (changes.get("due") or store._as_date(g["due"])) < (changes.get("start") or store._as_date(g["period_start"])):
        raise ToolError("The deadline can't be before the day the goal counts from.")
    if title:
        changes["title"] = title
    if target is not None:
        if float(target) <= 0:
            raise ToolError("target must be more than 0.")
        changes["target"] = target
    if unit is not None:
        changes["unit"] = unit
    if habit:
        changes["habit_id"] = _habit_id(habit)
    elif unlink_habit:
        changes["habit_id"] = None
    if habit and category:
        raise ToolError("A goal counts either a habit's ticks or timetable hours, not both.")
    if category:
        changes["category_id"] = _goal_category(category)
    elif unlink_category:
        changes["category_id"] = None
    if label is not None:
        changes["label"] = label
    if life_goal is not None:
        changes["life_goal_id"] = _life_goal_id(life_goal) or None
    if not changes:
        raise ToolError("Say what to change: title, target, unit, due, start, habit, category, label, life_goal, "
                        "effort, milestone, self_rating, unlink_habit or unlink_category.")
    store.update_goal(g["id"], **changes)
    return Result(f"Updated: {describe_goal(store.get_goal(g['id']))}.", changed=True)


def delete_goal(goal, period=None, date=None, confirmed=False):
    g = _find_goal(goal, period, date)
    summary = f"Delete the goal {describe_goal(g)}"
    if not confirmed:
        return Result("", pending=Pending(summary, lambda: delete_goal(g["id"], confirmed=True)))
    store.delete_goal(g["id"])
    return Result(f"Done: {summary}.", changed=True)


def list_goals(period=None, date=None):
    """Goals (with ids, progress and deadlines) not past their deadline on `date` (default today)."""
    day = _period_day(date)
    goals = store.goals_open(day)
    lines = ["Targets:" + ("" if goals else " none")]
    for g in goals:
        if True:
            pct = round(100 * min(g["value"] / g["target"], 1))
            how = f"; counts habit {g['habit']}" if g["habit"] else ""
            if g.get("category"):
                how = f"; counts Actual hours of {g['label'] + ' (' + g['category'] + ')' if g.get('label') else g['category']}"
            life = store.get_life_goal(g["life_goal_id"]) if g.get("life_goal_id") else None
            how += f"; under the goal {life['title']}" if life else ""
            lines.append(f"- {g['title']} {store.goal_title_due(g['due'], day)}: {_amount(g)} ({pct}%) (id {g['id']}{how})")
    return Result("\n".join(lines))
