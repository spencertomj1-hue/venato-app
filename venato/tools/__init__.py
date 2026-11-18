"""
The actions Claude can take in Venato, as plain Python functions.

assistant.py exposes each one as an MCP tool; the tests call them directly.
They only use store.py, so the rules are the same as the app's pages.

Anything that deletes data, or overwrites/trims existing data, doesn't run
straight away: it returns a Result with a `pending` preview. The chat panel
shows that preview with Confirm / Cancel, and Confirm calls `pending.run()`,
which re-runs the same tool with confirmed=True (so it re-checks the data).
"""


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
from .goals import (_amount, _find_goal, add_goal, delete_goal, describe_goal, edit_goal, list_goals,
    log_goal_progress, set_goal_progress)
from .journal import (read_journal, write_journal)


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
