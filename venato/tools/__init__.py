"""
The actions Claude can take in Venato, as plain Python functions.

assistant.py exposes each one as an MCP tool; the tests call them directly.
They only use store.py, so the rules are the same as the app's pages.

Anything that deletes data, or overwrites/trims existing data, doesn't run
straight away: it returns a Result with a `pending` preview. The chat panel
shows that preview with Confirm / Cancel, and Confirm calls `pending.run()`,
which re-runs the same tool with confirmed=True (so it re-checks the data).
"""

from datetime import date

from venato import facade, store

from .common import (FILLER_WORDS, PERIOD_NAMES, Pending, Result, ToolError, _best_match, _date_range, _day,
    _now, _period, _period_day, nice_day)
from .daily_log import (add_habit, delete_habit, get_stats, list_habits, log_day, query_entries,
    rename_habit, set_habit, set_habit_target)
from .timetable import (OUTLOOK_PREFIX, _days_between, _first_future_slot, _place, _spaced, _window,
    add_block, confirm_all, confirm_day, delete_block, describe_block, edit_category, list_categories,
    plan_time, query_blocks, set_activity_default, set_outlook_category, skip_block, update_block)
from .deadlines import (add_deadline, complete_deadline, delete_deadline, describe_deadline, edit_deadline,
    list_deadlines)
from .todos import (_find_todo, add_todo, complete_todo, delete_todo, describe_todo, edit_todo, list_todos,
    todo_list_name, uncomplete_todo)


# ---------------------------------------------------------------------------
# Goals: measurable monthly / yearly targets with progress
# ---------------------------------------------------------------------------

def _amount(goal, n=None):
    """"7/12 sessions" for a goal (or n of its unit)."""
    n = goal["value"] if n is None else n
    return f"{store._num(n)}/{goal['target']}" + (f" {goal['unit']}" if goal["unit"] else "")


def describe_goal(g):
    when = store.goal_title_due(g["due"])
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
        raise ToolError(f"There's no category '{category}'. Categories: {names}.")
    return cid


def _due(due):
    try:
        return date.fromisoformat(_day(due))
    except (TypeError, ValueError):
        raise ToolError("due must be a date, YYYY-MM-DD.")


def add_goal(title, target, period=None, unit=None, habit=None, date=None, category=None, label=None, due=None):
    """A measurable goal with a deadline (`due`), from today (or `date`). Without a deadline, `period`
    "monthly" / "yearly" makes it due at the end of the month / year (default: this month). With a
    category (and optionally an activity label) it counts the timetable's Actual hours instead of a hand-kept number."""
    day = _period_day(date)
    per = None
    if due is None:                              # the month's or year's: from its first day to its last
        per = _period(period or "monthly", store.GOAL_PERIODS)
        due = store.end_of_period(per, store.start_of_period(per, day))
    else:
        due = _due(due)
    if due < day:
        raise ToolError("The deadline can't be before the goal starts.")
    try:
        target = float(target)
    except (TypeError, ValueError):
        raise ToolError("target must be a number, e.g. 12.")
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
    g = store.add_goal(title, per, day, target, (unit or "h") if cid else unit, _habit_id(habit),
                       category_id=cid, label=label if cid else None, due=None if per else due)
    return Result(f"Added the goal {describe_goal(g)}.", changed=True)


def log_goal_progress(goal, amount=1, period=None, date=None):
    """Add to a goal's progress (a negative amount takes some off)."""
    g = _find_goal(goal, period, date)
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
    store.set_goal_progress(g["id"], float(value))
    g = store.get_goal(g["id"])
    return Result(f"Set {describe_goal(g)} (was {store._num(old)}).", changed=True)


def edit_goal(goal, title=None, target=None, unit=None, habit=None, unlink_habit=False, period=None, date=None,
              category=None, label=None, unlink_category=False, due=None, start=None):
    """Change a goal's title, target, unit, deadline, start (the day it counts from: earlier to count
    progress already made), or what (a habit, timetable hours, or nothing) it counts."""
    g = _find_goal(goal, period, date)
    changes = {}
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
    if not changes:
        raise ToolError("Say what to change: title, target, unit, due, start, habit, category, label, unlink_habit or unlink_category.")
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
    lines = ["Goals:" + ("" if goals else " none")]
    for g in goals:
        if True:
            pct = round(100 * min(g["value"] / g["target"], 1))
            how = f"; counts habit {g['habit']}" if g["habit"] else ""
            if g.get("category"):
                how = f"; counts Actual hours of {g['label'] + ' (' + g['category'] + ')' if g.get('label') else g['category']}"
            lines.append(f"- {g['title']} {store.goal_title_due(g['due'], day)}: {_amount(g)} ({pct}%) (id {g['id']}{how})")
    return Result("\n".join(lines))


# ---------------------------------------------------------------------------
# Journal
# ---------------------------------------------------------------------------

def write_journal(text, date=None, replace=False, confirmed=False):
    """Add a paragraph to a day's notes / journal entry (today by default); replace=True rewrites the whole entry."""
    day = _day(date) if date else store.local_today().isoformat()
    text = str(text or "").strip()
    if not text:
        raise ToolError("Nothing to write.")
    old = store.get_journal(day)
    if not replace or not old:
        store.append_journal(day, text)
        return Result(f"Added to the journal for {nice_day(day)}.", changed=True)
    if not confirmed:
        return Result("", pending=Pending(f"Replace the journal for {nice_day(day)} ({len(old.split())} words)",
                                          lambda: write_journal(text, day, True, True)))
    store.save_journal(day, text)
    return Result(f"Replaced the journal for {nice_day(day)}.", changed=True)


def read_journal(date=None, start_date=None, end_date=None, query=None, limit=10):
    """Journal entries for a day, a date range and/or matching words, newest first."""
    if date:
        start_date = end_date = date
    first = _day(start_date) if start_date else None
    last = _day(end_date) if end_date else None
    rows = store.journal_entries(query, first, last, limit=min(int(limit), 31))
    if not rows:
        return Result("No journal entries found.")
    return Result("\n\n".join(f"## {nice_day(r['date'])} ({r['date']})\n{r['text']}" for r in rows))


# ---------------------------------------------------------------------------
# Goals and the timetable: pace, the week's budget, planning goal time
# (the Goals page and the Timetable's goal chips call these too)
# ---------------------------------------------------------------------------

def _pace_ctx():
    from venato import pace
    return pace.Ctx(_now())


def goal_pace(goal=None, period=None, date=None):
    """How one goal (or every current goal) is doing: on track / behind / slipping / can't be reached,
    this week's need with any carried debt, the projected finish, and what to plan."""
    from venato import pace
    ctx = _pace_ctx()
    if goal:
        found = [_find_goal(goal, period, date)]
    else:
        found = store.goals_active(ctx.today)
    if not found:
        return Result("No goals this month or year.")
    return Result("\n".join(f"- {g['title']} ({_amount(g)}): {pace.goal_pace(g, ctx)['line']}" for g in found))


def week_budget(date=None):
    """Free time in a week (default this one) against what every hours goal needs, goal by goal in priority order."""
    from venato import pace
    ctx = _pace_ctx()
    day = _day(date) if date else ctx.today
    b = pace.week_budget(day, ctx)
    lines = [f"Week of {nice_day(b['week_start'].isoformat())}: {b['text']}"]
    for w in b["goals"]:
        g = w["goal"]
        extra = f", the budget is {pace.fmt(w['budget_short'])} h short" if w["budget_short"] > pace.TOLERANCE else ""
        lines.append(f"- {g['title']}: {pace.fmt(w['covered'])}/{pace.fmt(w['want'])} h covered "
                     f"({pace.debt_text(g, w['need'], w['baseline'])}){extra}")
    return Result("\n".join(lines))


def goal_spots(date=None, earliest="09:00", latest="21:00", max_block_hours=2, ctx=None):
    """
    Where Plan my goals would put what each hours goal is short in the week containing `date`:
    [(goal, [(day, start slot, end slot)])], goal by goal in priority order, within what the week's
    budget gives it, only in free gaps from now on. Nothing fixed is ever moved or overwritten.
    The Timetable draws these as suggested sittings; plan_goals adds them.
    """
    from venato import pace
    ctx = ctx or _pace_ctx()
    day = _day(date) if date else ctx.today.isoformat()
    lo, hi = _window(earliest, latest)
    chunk = max(1, round(float(max_block_hours) * 2))
    free, placed = {}, []                                   # free gaps shared by all goals
    for w in pace.week_goals(day, ctx):
        g = w["goal"]
        add = min(w["want"] - w["covered"], w["alloc"] - w["planned_future"])
        if w["over"] or add < pace.TOLERANCE:
            continue
        days = [d for d in _days_between(max(w["first"], ctx.today).isoformat(), w["last"].isoformat(), False)
                if _first_future_slot(d) < hi]
        for d in days:
            free.setdefault(d, store.free_runs(d, max(lo, _first_future_slot(d)), hi, now=_now()))
        need = round(pace.half_up(add) * 2)
        spots = _place(_spaced(days, need, chunk), free, need, chunk)
        if spots:
            placed.append((g, sorted(spots)))
    return placed


def plan_goals(date=None, earliest="09:00", latest="21:00", max_block_hours=2, confirmed=False):
    """
    Fill what each hours goal is short this week (default this one) into the Plan's free gaps,
    goal by goal in priority order, within what the week's budget gives it (goal_spots). Only free
    time is used: nothing fixed is moved or overwritten. Always previewed first.
    """
    placed = goal_spots(date, earliest, latest, max_block_hours)
    if not placed:
        return Result("Nothing to plan: every hours goal has enough time planned this week, or there's no free time left.")
    parts = []
    for g, spots in placed:
        got = sum(e - s for _, s, e in spots) / 2
        when = "; ".join(f"{nice_day(d)} {store.slot_time(s)}–{store.slot_time(e)}" for d, s, e in spots)
        parts.append(f"{got:g} h of {g['label'] or g['title']} for {g['title']}: {when}")
    summary = "Plan " + ". ".join(parts)
    if not confirmed:
        return Result("", pending=Pending(summary, lambda: plan_goals(date, earliest, latest, max_block_hours, True)))
    for g, spots in placed:
        for d, s, e in spots:
            store.paint(d, store.live_track(d, _now()), s, e, {"label": g["label"] or g["title"], "category_id": g["category_id"],
                                          "details": None})
    return Result(f"Done: {summary}.", changed=True)


def resolve_goal(goal, offer, confirmed=False):
    """
    Take one of the offers for a goal that can't be finished with the time left (pace.negotiation):
    "lower" its target to what's reachable, "extend" its deadline to when this rate gets there, or "take" hours
    from a lower-priority goal. Always previewed first.
    """
    from venato import pace
    g = _find_goal(goal)
    n = pace.negotiation(g, _pace_ctx())
    chosen = next((o for o in (n["offers"] if n else []) if o["kind"] == offer), None)
    if not chosen:
        return Result(f"{g['title']} doesn't need that any more.")
    if not confirmed:
        return Result("", pending=Pending(f"{g['title']}: {chosen['text']}",
                                          lambda: resolve_goal(g["id"], offer, True)))
    if offer == "lower":
        store.update_goal(g["id"], target=chosen["target"])
    if offer == "extend":
        store.update_goal(g["id"], due=chosen["due"])
    if offer == "take":
        other = store.get_goal(chosen["other"])
        store.update_goal(other["id"], target=float(other["target"]) - chosen["hours"])
    return Result(f"Done: {g['title']}: {chosen['text']}.", changed=True)


# ---------------------------------------------------------------------------
# Weekly review
# ---------------------------------------------------------------------------

def weekly_review(date=None):
    """The main numbers for the week containing `date` (default: the latest review week)."""
    from venato import review
    first = store.week_start_of(_day(date)) if date else review.due_week()
    return Result(review.as_text(review.summary(first)))


def save_review_answers(went_well=None, to_change=None, date=None, confirmed=False):
    """Write the weekly review's two reflections (what went well / what to change) for a week."""
    from venato import review
    first = store.week_start_of(_day(date)) if date else review.due_week()
    old = next((r for r in store.reviews() if r["week_start"] == first.isoformat()), {})
    overwrite = [k for k, v in (("went_well", went_well), ("to_change", to_change)) if v is not None and old.get(k)]
    label = f"the week of {nice_day(first.isoformat())}"
    if overwrite and not confirmed:
        return Result("", pending=Pending(f"Replace your review answers for {label}",
                                          lambda: save_review_answers(went_well, to_change, first.isoformat(), True)))
    store.save_review(first, went_well=went_well if went_well is not None else store.KEEP,
                      to_change=to_change if to_change is not None else store.KEEP)
    return Result(f"Saved your review for {label}.", changed=True)


# `tools._now = fake` (tests) reaches the submodules that use it (see venato/facade.py).
facade.install(__name__)
