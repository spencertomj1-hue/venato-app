"""
Goals meet the timetable: how much free time a week has, what each goal needs, whether
it's on pace, and what to plan. No Streamlit and no SQL (the store does the SQL).

The core rule: a week's capacity is the timetable's hours minus fixed time. Fixed time is
every visible timed calendar event and every Plan block that doesn't serve an hours goal
(detached calendar events, ids "ol:...", always stay fixed). Goals only get what's left,
and nothing here ever proposes moving or overwriting fixed time.

Words used throughout:
  need      what a goal needs in a week to finish on time, in its own unit: the remaining
            amount spread evenly over the days left (from the start of that week)
  baseline  the even-pace share of the week (target / days in the period), so
            need - baseline is the "carried" debt (negative = ahead)
  follow    follow-through: Actual / Plan for the goal over the last 6 weeks (None until there
            are 3 weeks with a Plan), clamped to 30-100%. Planning need / follow lands need.
  want      hours a goal should have in the timetable this week: what's done so far plus the
            rest of the need, inflated by follow-through (or the user's own split, goal_week)
  covered   what it has: done so far plus what's planned for the rest of the week

A Ctx reads the blocks and events once for everything a page needs (and pins "now").

Actual time counts on confirmed timetable days only (store, "One timeline"): an unconfirmed
day's Plan is only assumed to have happened. So `done`, values, rates and follow-through use
confirmed days, Plan-vs-Actual comparisons use the same days, and the assumed time on
unconfirmed days is kept apart (`assumed`) so Plan my goals doesn't plan it a second time.
"""

import math
from datetime import datetime, time, timedelta

from venato import store
from venato.cache import cached

TRAILING_DAYS = 28            # the Actual rate behind the projection: the last 4 weeks
FOLLOW_WEEKS = 6              # follow-through looks at the last 6 complete weeks...
FOLLOW_MIN_WEEKS = 3          # ...and needs a Plan in at least 3 of them
FOLLOW_RANGE = (0.3, 1.0)
TOLERANCE = 0.25              # hours: anything closer than a quarter of an hour counts as there

STATES = {"done": "Done", "on_track": "On track", "behind": "Behind", "slipping": "Slipping",
          "unreachable": "Can't be reached", "ended": "Ended", "upcoming": "Not started"}


def _d(day):
    return store._as_date(day)


def _iso(day):
    return _d(day).isoformat()


def bounds(goal):
    """(first day, deadline) of a goal."""
    return _d(goal["period_start"]), _d(goal["due"])


def week_days(day):
    """The 7 days of the week containing `day` (Monday or Sunday first, as set)."""
    first = store.week_start_of(day)
    return [first + timedelta(days=i) for i in range(7)]


def half_up(x):
    """Round up to the next half hour (Fit time works in half hours)."""
    return math.ceil(x * 2 - 1e-9) / 2


def fmt(x):
    """A number for people: 6, 6.5, 0.3."""
    x = round(float(x), 1)
    return f"{x:g}"


def amount(goal, x):
    """"6 h", "3 sessions", "250"; a milestone's (0..1) as "60%"."""
    if goal.get("milestone"):
        return f"{round(100 * float(x))}%"
    unit = goal.get("unit")
    return f"{fmt(x)} {unit}" if unit else fmt(x)


def priority(goals):
    """Goals in priority order: the list's own order (move up / down to rank), the sooner deadline on a tie."""
    return sorted(goals, key=lambda g: (g["ord"], g["due"], g["created_at"]))


def inflation_on():
    """Settings: "goal_inflate" (default on) plans extra to make up for time that usually slips."""
    return bool(store.load_settings().get("goal_inflate", True))


# Reads remembered until the data changes (kit.cached). The lambdas look `store` up when called.
goals_overlapping = cached(lambda first, last: store.goals_overlapping(first, last))
goals_active = cached(lambda day=None: store.goals_active(day))
goals_open = cached(lambda day=None: store.goals_open(day))
goals_past = cached(lambda day=None: store.goals_past(day))
_blocks_between = cached(lambda first, last: store.blocks_between(first, last))
_outlook_between = cached(lambda first, last: store.outlook_between(first, last))
_confirmed_days = cached(lambda first, last: store.confirmed_days(first, last))


class Ctx:
    """
    One look at the data: "now", the calendar's reach, the away days, and the timetable's
    blocks and events, read once for a window of days and kept for every calculation.
    """

    def __init__(self, now=None):
        self.now = now or store.local_now()
        self.today = self.now.date()
        self.horizon = store.calendar_horizon()
        self.away = store.away_uids()
        self.away_days = store.away_days()
        self.inflate = inflation_on()
        self.ocat = store.outlook_category("")
        self._window = None
        self._data = None
        self._day_cap = {}
        self._avg_fixed = None
        self._goals = {}

    # --- data ---

    def data(self, first, last):
        """Blocks (both tracks) and calendar events covering first..last, read once."""
        first, last = _d(first), _d(last)
        lo = min(first, self.today - timedelta(days=TRAILING_DAYS + 7 * (FOLLOW_WEEKS + 2)))
        hi = max(last, self.today + timedelta(weeks=9))
        if self._window is None or lo < self._window[0] or hi > self._window[1]:
            if self._window:
                lo, hi = min(lo, self._window[0]), max(hi, self._window[1])
            self._window = (lo, hi)
            store.lock_started(lo, hi, self.now)     # started days' Plans are locked (copied into the Actual): see "live"
            blocks = _blocks_between(lo.isoformat(), hi.isoformat())
            events = _outlook_between(lo.isoformat(), hi.isoformat())
            by_day = {}
            for b in blocks:
                by_day.setdefault(b["date"], {"blocks": [], "events": []})["blocks"].append(b)
            for ev in events:
                by_day.setdefault(ev["date"], {"blocks": [], "events": []})["events"].append(ev)
            # "live": what's ahead as it stands: a started day's Actual (its Plan is locked; changes go to the
            # Actual), else the Plan and its calendar events. Track "live" for goal_hours.
            started = lambda d: store.day_started(d, self.now)
            live = [{**b, "track": "live"} for b in blocks
                    if b["track"] == ("actual" if started(b["date"]) else "plan")]
            live_events = [ev for ev in events if not started(ev["date"])]
            for b in live:
                by_day[b["date"]].setdefault("live", []).append(b)
            self._data = {"blocks": blocks + live, "events": events, "live_events": live_events,
                          "outlook_category": self.ocat, "by_day": by_day,
                          "confirmed": set(_confirmed_days(lo.isoformat(), hi.isoformat()))}
            self._day_cap = {}
            self._avg_fixed = None
        return self._data

    def hours(self, goal, first, last, track, window=None, days=None):
        """store.goal_hours over the data already read (the Actual: confirmed days only).
        days: "confirmed" / "unconfirmed" counts only those days (for the Plan)."""
        data = self.data(first, last)
        if track == "live":
            data = {**data, "events": data["live_events"]}
        if days:
            keep = (lambda d: d in data["confirmed"]) if days == "confirmed" else (lambda d: d not in data["confirmed"])
            inner = window
            window = lambda d: (inner(d) if inner else (0, store.SLOTS)) if keep(d) else (0, 0)
        return store.goal_hours(goal, first, last, track, data=data, window=window)

    def confirmed(self, first, last):
        """(confirmed days, days so far) between two days: "based on 5 of 7 confirmed days"."""
        first, last = _d(first), min(_d(last), self.today)
        conf = self.data(first, max(first, last))["confirmed"]
        days = [first + timedelta(days=i) for i in range((last - first).days + 1)]
        return sum(_iso(d) in conf for d in days), len(days)

    def first_future_slot(self, day):
        """The first slot of a timetable day that hasn't started yet (SLOTS once it's over, 0 for later days)."""
        start = datetime.combine(_d(day), time(store.FIRST_MIN // 60, store.FIRST_MIN % 60))
        gone = (self.now - start).total_seconds() / 60
        return min(store.SLOTS, max(0, -(-int(gone) // 30)))

    def future(self, day):
        return self.first_future_slot(day), store.SLOTS

    def past(self, day):
        return 0, self.first_future_slot(day)

    def hours_goals(self, first, last):
        """Hours goals whose period overlaps first..last, in priority order (cached)."""
        key = (_iso(first), _iso(last))
        if key not in self._goals:
            self._goals[key] = priority([g for g in goals_overlapping(first, last) if g["kind"] == "hours"])
        return self._goals[key]

    # --- capacity ---

    def _day(self, day):
        return self.data(day, day)["by_day"].get(_iso(day), {"blocks": [], "events": []})

    def is_away(self, day):
        return _iso(day) in self.away_days or \
            any(ev["all_day"] and ev["uid"] in self.away for ev in self._day(day)["events"])

    def month_goals(self, day):
        """Hours goals active in the month containing `day` (cached per month)."""
        first = store.start_of_period("monthly", day)
        return self.hours_goals(first, store.end_of_period("monthly", first))

    def _fixed(self, day, goals):
        """[slot is fixed] for a day: blocks and timed events that serve no hours goal active that day."""
        iso = _iso(day)
        serving = [g for g in goals if _iso(bounds(g)[0]) <= iso <= _iso(bounds(g)[1])]
        fixed = [False] * store.SLOTS
        rows = self._day(day)

        def mark(s, e):
            for i in range(max(0, s), min(e, store.SLOTS)):
                fixed[i] = True

        for b in rows.get("live", []):              # what's ahead as it stands (today: its Actual)
            if str(b["id"]).startswith("ol:") or not any(store._goal_matches(g, b["category_id"], b["label"]) for g in serving):
                mark(store.slot_of(b["start"]), store.slot_of(b["end"]))
        for ev in rows["events"] if not store.day_started(day, self.now) else ():   # (copied into a started day's Actual)
            if ev["all_day"] or not ev["start"]:
                continue
            cat = ev.get("module_category") or self.ocat       # a module's event: its module's category only
            if not any(store._goal_matches(g, cat, ev["title"], event=True) for g in serving):
                mark(store.slot_of(ev["start"]), store.slot_of(ev["end"]))
        return fixed

    def _average_fixed(self):
        """Fixed slots per weekday, averaged over the days the calendar reaches (for estimates further out)."""
        if self._avg_fixed is None:
            sums, counts = [0] * 7, [0] * 7
            day = self.today + timedelta(days=1)
            while self.horizon and day <= self.horizon:
                sums[day.weekday()] += sum(self._fixed(day, self.month_goals(day)))
                counts[day.weekday()] += 1
                day += timedelta(days=1)
            self._avg_fixed = [s / c if c else 0 for s, c in zip(sums, counts)]
        return self._avg_fixed

    def day_capacity(self, day):
        """
        {"hours", "estimate", "away", "past"} for one day: the free time left for goals from now on
        (time already planned for an hours goal counts as free for goals). Past days have none,
        an away day has none, and days past the calendar's reach use the average fixed load.
        """
        iso = _iso(day)
        if iso not in self._day_cap:
            day = _d(day)
            lo = self.first_future_slot(day)
            out = {"date": iso, "hours": 0.0, "estimate": False, "away": self.is_away(day), "past": lo >= store.SLOTS}
            if not out["away"] and not out["past"]:
                fixed = self._fixed(day, self.month_goals(day))
                free = sum(1 for i in range(lo, store.SLOTS) if not fixed[i])
                if self.horizon and day > self.horizon:
                    out["estimate"] = True
                    known = sum(fixed[lo:])
                    free = max(0, store.SLOTS - lo - max(known, round(self._average_fixed()[day.weekday()])))
                out["hours"] = free / 2
            self._day_cap[iso] = out
        return self._day_cap[iso]

    def capacity_between(self, first, last):
        """Free hours for goals between two days (inclusive), from now on, and whether any of it is an estimate."""
        total, estimate, day = 0.0, False, max(_d(first), self.today)
        while day <= _d(last):
            c = self.day_capacity(day)
            total += c["hours"]
            estimate |= c["estimate"]
            day += timedelta(days=1)
        return total, estimate


# ---------------------------------------------------------------------------
# Phase 1: a week's capacity
# ---------------------------------------------------------------------------

def week_capacity(week, ctx=None):
    """
    The week containing `week`: per day the free hours left for goals (none for days already over or
    marked away; the current week counts only what hasn't started), the total, and whether it's an
    estimate (beyond the 8 weeks calendar sync reaches).
    """
    ctx = ctx or Ctx()
    days = [ctx.day_capacity(d) for d in week_days(week)]
    return {"week_start": week_days(week)[0], "days": days, "hours": sum(d["hours"] for d in days),
            "estimate": any(d["estimate"] for d in days), "timetable_hours": 7 * store.SLOTS / 2}


# ---------------------------------------------------------------------------
# Progress over time (shared by need, pace and debt)
# ---------------------------------------------------------------------------

def value_before(goal, day, ctx):
    """A goal's progress from the start of its period up to (not including) `day`, in its own unit.
    Hand-kept goals have no history, so it's their current number."""
    start, end = bounds(goal)
    last = min(_d(day) - timedelta(days=1), end)
    if goal["kind"] == "hours":
        return ctx.hours(goal, start, last, "actual") if last >= start else 0.0
    if goal["kind"] == "habit":
        return sum(1 for d in store.get_habit_dates(goal["habit_id"]) if _iso(start) <= d <= _iso(last))
    return goal["value"]


def daily_rate(goal, ctx):
    """Recent progress per day: the last 4 weeks' Actual hours or habit ticks (hand-kept: the period so far).
    None when there's nothing to go on."""
    first, last = ctx.today - timedelta(days=TRAILING_DAYS), ctx.today - timedelta(days=1)
    if goal["kind"] == "hours":                     # per confirmed day: unconfirmed days tell us nothing
        n, _ = ctx.confirmed(first, last)
        return ctx.hours(goal, first, last, "actual") / n if n else None
    if goal["kind"] == "habit":
        return sum(1 for d in store.get_habit_dates(goal["habit_id"]) if _iso(first) <= d <= _iso(last)) / TRAILING_DAYS
    start, _ = bounds(goal)
    elapsed = (ctx.today - start).days
    return goal["value"] / elapsed if elapsed > 0 else None


def week_need(goal, week, ctx):
    """
    (need, baseline) for a goal in the week containing `week`, in its own unit. The need spreads
    what was left at the start of that week (or now, for later weeks) evenly over the days left,
    so a slow week carries into the next ones; the baseline is the even-pace share.
    """
    start, end = bounds(goal)
    days = [d for d in week_days(week) if start <= d <= end]
    if not days:
        return 0.0, 0.0
    total_days = (end - start).days + 1
    baseline = goal["target"] * len(days) / total_days
    as_of = max(days[0], start) if days[0] <= ctx.today else max(ctx.today, start)
    left = (end - as_of).days + 1
    remaining = max(0.0, goal["target"] - value_before(goal, as_of, ctx))
    return remaining * len(days) / left, baseline


def follow_through(goal, ctx):
    """Actual / Plan for an hours goal over the last 6 complete weeks, clamped to 30-100%.
    None until 3 of those weeks had something planned for it."""
    if goal["kind"] != "hours":
        return None
    this_week = week_days(ctx.today)[0]
    planned = done = weeks = 0
    for n in range(1, FOLLOW_WEEKS + 1):
        first = this_week - timedelta(weeks=n)
        last = first + timedelta(days=6)
        p = ctx.hours(goal, first, last, "plan", days="confirmed")     # the same days the Actual counts
        if p > 0:
            weeks += 1
            planned += p
            done += ctx.hours(goal, first, last, "actual")
    if weeks < FOLLOW_MIN_WEEKS:
        return None
    return min(FOLLOW_RANGE[1], max(FOLLOW_RANGE[0], done / planned))


# ---------------------------------------------------------------------------
# Phases 1, 3, 4, 5: what each hours goal wants in a week, and the budget
# ---------------------------------------------------------------------------

def week_goals(week, ctx=None):
    """
    Every hours goal active in the week containing `week`, in priority order, each a dict:
      goal, need, baseline, carried, done (Actual so far), planned (whole week), planned_future,
      plan_so_far, follow, factor (what to plan per hour to land), want, covered, short, chosen
      (the user's own split, or None), alloc (hours of the rest of the week it gets from the
      budget, top-down by priority) and budget_short (what the budget can't give it).
    """
    ctx = ctx or Ctx()
    days = week_days(week)
    first, last = days[0], days[-1]
    chosen = store.goal_week_hours(first)
    out = []
    for g in ctx.hours_goals(first, last):
        start, end = bounds(g)
        a, b = max(first, start), min(last, end)
        need, baseline = week_need(g, first, ctx)
        upto = min(b, ctx.today)
        done = ctx.hours(g, a, upto, "actual", window=ctx.past) if upto >= a else 0.0
        planned = ctx.hours(g, a, b, "plan")
        planned_future = ctx.hours(g, max(a, ctx.today), b, "live", window=ctx.future) if b >= ctx.today else 0.0
        plan_so_far = ctx.hours(g, a, upto, "plan", window=ctx.past, days="confirmed") if upto >= a else 0.0
        # Time that has passed on days not confirmed yet (their Actual as it stands): maybe done, so not planned again.
        assumed = ctx.hours(g, a, upto, "live", window=ctx.past, days="unconfirmed") if upto >= a else 0.0
        confirmed, so_far = ctx.confirmed(a, upto) if upto >= a else (0, 0)
        follow = follow_through(g, ctx)
        factor = 1 / follow if follow and ctx.inflate else 1.0
        over = b < ctx.today                                    # the week (for this goal) is over
        want = done if over else done + max(0.0, need - done) * factor
        if g["id"] in chosen:
            want = chosen[g["id"]]
        covered = done + assumed + planned_future
        out.append({"goal": g, "need": need, "baseline": baseline, "carried": need - baseline,
                    "done": done, "planned": planned, "planned_future": planned_future, "plan_so_far": plan_so_far,
                    "assumed": assumed, "confirmed_days": confirmed, "days_so_far": so_far,
                    "follow": follow, "factor": factor, "want": want, "covered": covered,
                    "short": 0.0 if over else max(0.0, want - covered),
                    "chosen": chosen.get(g["id"]), "first": a, "last": b, "over": over})
    # The budget: the rest of the week's free time, handed out top-down by priority.
    left = week_capacity(first, ctx)["hours"]
    for w in out:
        rest = max(0.0, w["want"] - w["done"])
        w["alloc"] = min(rest, left)
        w["budget_short"] = rest - w["alloc"]
        left -= w["alloc"]
    return out


def week_budget(week, ctx=None):
    """
    Capacity against what every hours goal wants for the rest of the week containing `week`:
    {"week_start", "capacity", "need", "estimate", "over", "goals": week_goals(...), "text"}.
    """
    ctx = ctx or Ctx()
    cap = week_capacity(week, ctx)
    goals = week_goals(week, ctx)
    need = sum(max(0.0, w["want"] - w["done"]) for w in goals)
    est = " (an estimate: your calendar only reaches 8 weeks ahead)" if cap["estimate"] else ""
    if not goals:
        text = f"No hours targets this week. You have {fmt(cap['hours'])} h free{est}."
    else:
        text = f"Targets need {fmt(need)} h, you have {fmt(cap['hours'])} h free{est}."
    return {"week_start": cap["week_start"], "capacity": cap["hours"], "need": need, "estimate": cap["estimate"],
            "over": need > cap["hours"] + TOLERANCE, "goals": goals, "days": cap["days"], "text": text}


def week_text(goal, need, baseline):
    """"9 h needed this week, 3 h of it carried over" (or "(2 h ahead)") for the Goals page."""
    carried = need - baseline
    text = f"{amount(goal, need)} needed this week"
    if carried >= 0.05:
        text += f", {amount(goal, carried)} of it carried over"
    elif carried <= -0.05:
        text += f" ({amount(goal, -carried)} ahead)"
    return text


def debt_text(goal, need, baseline):
    """"9 h this week (6 h + 3 h carried)", or "(6 h − 2 h ahead)"."""
    carried = need - baseline
    if abs(carried) < 0.05:
        return f"{amount(goal, need)} this week"
    sign = "+" if carried > 0 else "−"
    word = "carried" if carried > 0 else "ahead"
    return f"{amount(goal, need)} this week ({amount(goal, baseline)} {sign} {amount(goal, abs(carried))} {word})"


# ---------------------------------------------------------------------------
# Phase 2: pace
# ---------------------------------------------------------------------------

def expected(goal, today=None):
    """Where an even pace would have a goal by today (the start of today), in its own unit."""
    today = today or store.local_today()
    start, end = bounds(goal)
    total = (end - start).days + 1
    return float(goal["target"]) * min(total, max(0, (today - start).days)) / total


def goal_pace(goal, ctx=None):
    """
    How a goal is doing, in its own unit:
      state (STATES key), value, target, remaining, expected (where an even pace would have it
      by today), week_need (remaining per week from now), need / baseline / debt (this week),
      rate (recent progress per week), finish (projected day, or None), late (days after the
      period's end; negative = early), and for hours goals the week's row from week_goals and
      `available` (free time left in the period). `line` says it in one sentence.
    """
    ctx = ctx or Ctx()
    start, end = bounds(goal)
    today = ctx.today
    value, target = float(goal["value"]), float(goal["target"])
    remaining = max(0.0, target - value)
    p = {"goal": goal, "value": value, "target": target, "remaining": remaining, "start": start, "end": end,
         "expected": expected(goal, today),
         "week": None, "available": None, "available_estimate": False, "finish": None, "late": None,
         "rate": None, "week_need": None, "need": 0.0, "baseline": 0.0}
    if today > end:
        p["state"] = "done" if remaining <= 0 else "ended"
        p["line"] = f"{STATES[p['state']]}: {amount(goal, value)} of {amount(goal, target)}."
        return p
    if today < start:
        p["state"] = "upcoming"
        p["line"] = f"Starts {store.fmt_day(start, '%-d %b')}."
        return p
    days_left = (end - today).days + 1
    p["week_need"] = remaining / days_left * 7
    p["need"], p["baseline"] = week_need(goal, today, ctx)
    rate = daily_rate(goal, ctx)
    p["rate"] = None if rate is None else rate * 7
    if remaining > 0 and rate:
        p["finish"] = today + timedelta(days=math.ceil(remaining / rate) - 1)
        p["late"] = (p["finish"] - end).days
    if goal["kind"] == "hours":
        rows = [w for w in week_goals(today, ctx) if w["goal"]["id"] == goal["id"]]
        p["week"] = rows[0] if rows else None
        p["available"], p["available_estimate"] = ctx.capacity_between(today, end)

    if remaining <= 0:
        state = "done"
    elif goal["kind"] == "hours" and remaining > p["available"] + TOLERANCE:
        state = "unreachable"
    elif goal["kind"] == "habit" and remaining > days_left:
        state = "unreachable"                                  # one tick a day at most
    elif goal["kind"] == "hours" and p["week"]:
        w = p["week"]
        if w["covered"] < w["want"] - TOLERANCE:
            state = "behind"                                   # not enough planned
        elif w["plan_so_far"] - w["done"] >= 1:
            state = "slipping"                                 # planned enough, Actual trailing Plan
        else:
            state = "on_track"
    else:
        state = "behind" if value < p["expected"] - 1e-9 and (p["late"] is None or p["late"] > 0) else "on_track"
    p["state"] = state
    p["line"] = _pace_line(p)
    p["details"] = _details(p)
    return p


def _projection(p):
    g = p["goal"]
    if p["remaining"] <= 0:
        return ""
    if p["late"] is None:
        return "no progress in the last 4 weeks" if g["kind"] != "count" else ""
    if p["late"] > 0:
        return f"{p['late']} day{'s' if p['late'] != 1 else ''} late at this rate"
    if p["late"] < 0:
        return f"done {-p['late']} day{'s' if p['late'] != -1 else ''} early at this rate"
    return "done on the last day at this rate"


def _pace_line(p):
    g = p["goal"]
    parts = [STATES[p["state"]]]
    if p["state"] != "done":
        parts.append(debt_text(g, p["need"], p["baseline"]))
        w = p["week"]
        if w and w["factor"] > 1 and w["want"] > w["done"]:
            parts.append(f"plan {fmt(w['want'] - w['done'])} h to land {fmt(max(0.0, w['need'] - w['done']))} h "
                         f"(you usually do {round(100 * w['follow'])}% of what you plan)")
        proj = _projection(p)
        if proj:
            parts.append(proj)
        if p["state"] == "unreachable" and g["kind"] == "hours":
            parts.append(f"only {fmt(p['available'])} h free before the end"
                         + (" (estimated)" if p["available_estimate"] else ""))
    return " · ".join(parts)


def _details(p):
    """The pace in short plain lines for the Goals page (the state itself is shown as a badge)."""
    g = p["goal"]
    if p["state"] in ("done", "ended", "upcoming"):
        return []
    out = [week_text(g, p["need"], p["baseline"])]
    proj = _projection(p)
    if proj:
        out.append(proj[0].upper() + proj[1:])
    w = p["week"]
    if w and w["factor"] > 1 and w["want"] > w["done"]:
        out.append(f"Plan {fmt(w['want'] - w['done'])} h to land {fmt(max(0.0, w['need'] - w['done']))} h: "
                   f"you usually do {round(100 * w['follow'])}% of what you plan")
    if p["state"] == "unreachable" and g["kind"] == "hours":
        out.append(f"Only {fmt(p['available'])} h free before the end" + (" (estimated)" if p["available_estimate"] else ""))
    return out


def pace_all(ctx=None):
    """goal_pace for every goal running today, in list order."""
    ctx = ctx or Ctx()
    return [goal_pace(g, ctx) for g in goals_active(ctx.today)]


def history(goal, ctx):
    """
    A goal's progress over its period so far, for the pace chart: [(day, value by the end of that day)]
    from the day before its start (0) to yesterday, plus today. Hours goals count confirmed days only;
    habit goals their ticks. Hand-kept goals have no history: None.
    """
    if goal["kind"] == "count":
        return None
    start, end = bounds(goal)
    last = min(ctx.today, end)
    out, total = [(start - timedelta(days=1), 0.0)], 0.0
    if goal["kind"] == "habit":
        ticks = {d for d in store.get_habit_dates(goal["habit_id"]) if _iso(start) <= d <= _iso(last)}
    else:
        data = ctx.data(start, last)
    day = start
    while day <= last:
        if goal["kind"] == "habit":
            total += _iso(day) in ticks
        else:
            rows = data["by_day"].get(_iso(day))
            if rows:
                total += store.goal_hours(goal, day, day, "actual",
                                          data={"blocks": rows["blocks"], "events": [], "confirmed": data["confirmed"]})
        out.append((day, total))
        day += timedelta(days=1)
    return out


# ---------------------------------------------------------------------------
# Phase 6: negotiation, when the time left can't cover a goal
# ---------------------------------------------------------------------------

def available_for(goal, ctx):
    """Free hours an hours goal can still get before its period ends, after every higher-priority
    goal has taken what it needs (week by week)."""
    start, end = bounds(goal)
    total, week = 0.0, week_days(ctx.today)[0]
    while week <= end:
        days = [d for d in week_days(week) if max(start, ctx.today) <= d <= end]
        if days:
            cap = sum(ctx.day_capacity(d)["hours"] for d in days)
            for g in ctx.hours_goals(week, week + timedelta(days=6)):
                if g["id"] == goal["id"]:
                    break
                cap -= week_need(g, week, ctx)[0]
            total += max(0.0, cap)
        week += timedelta(days=7)
    return total


def negotiation(goal, ctx=None):
    """
    For a goal that can't be finished with the time (or days) left: what's reachable and the offers
    {"reachable", "deficit", "offers": [{"kind": "lower"|"extend"|"take", "text", ...}]}, else None.
    """
    ctx = ctx or Ctx()
    p = goal_pace(goal, ctx)
    if p["state"] in ("done", "ended", "upcoming"):
        return None
    start, end = bounds(goal)
    days_left = (end - ctx.today).days + 1
    rate = daily_rate(goal, ctx) or 0.0
    if goal["kind"] == "hours":
        room = available_for(goal, ctx)
        if p["remaining"] <= room + TOLERANCE:
            return None
        reachable = p["value"] + min(room, rate * days_left) if rate else p["value"] + room
    elif p["state"] == "unreachable":
        reachable = p["value"] + min(days_left, rate * days_left)
    else:
        return None
    new_target = max(0.5, math.floor(reachable * 2) / 2)
    if new_target >= p["target"]:
        return None
    deficit = p["target"] - new_target
    unit = lambda x: amount(goal, x)
    offers = [{"kind": "lower", "target": new_target,
               "text": f"Lower the target to {unit(new_target)} (what you're on course for)"}]
    # Keep the target and give it the time it needs: at your recent rate, or (none yet) the pace the goal was set at.
    per_day = rate or float(goal["target"]) / ((end - start).days + 1)
    if per_day > 0:
        due = ctx.today + timedelta(days=math.ceil(p["remaining"] / per_day) - 1)
        if due > end:
            offers.append({"kind": "extend", "due": due.isoformat(),
                           "text": f"Keep {unit(p['target'])} and move the deadline to {store.fmt_day(due, '%-d %b %Y')}"})
    if goal["kind"] == "hours":
        mine = [g for g in ctx.hours_goals(ctx.today, end)]
        ids = [g["id"] for g in mine]
        if goal["id"] in ids:
            for other in reversed(mine[ids.index(goal["id"]) + 1:]):        # the lowest priority first
                spare = float(other["target"]) - max(float(other["value"]), 0.5)
                if spare >= 0.5:
                    take = min(deficit, math.floor(spare * 2) / 2)
                    offers.append({"kind": "take", "other": other["id"], "hours": take,
                                   "text": f"Take {fmt(take)} h from {other['title']} "
                                           f"(its target {amount(other, other['target'])} → "
                                           f"{amount(other, float(other['target']) - take)})"})
                    break
    return {"goal": goal, "reachable": reachable, "deficit": deficit, "offers": offers, "pace": p}


def dismissed_offers():
    return set(store.load_settings().get("goal_offers_dismissed") or [])


def dismiss_offer(goal_id):
    store.save_settings(goal_offers_dismissed=sorted(dismissed_offers() | {goal_id}))


# ---------------------------------------------------------------------------
# The weekly review
# ---------------------------------------------------------------------------

def review_rows(first, ctx=None):
    """
    Each goal active in the week starting `first`: what was done that week against its need then
    (hours and habit goals; hand-kept goals only have a total), and its pace now.
    [{"goal", "done", "need", "state", "text"}]
    """
    ctx = ctx or Ctx()
    days = week_days(first)
    out = []
    for g in priority(goals_overlapping(days[0], days[-1])):
        start, end = bounds(g)
        a, b = max(days[0], start), min(days[-1], end)
        need, _ = week_need(g, days[0], ctx)
        if g["kind"] == "hours":
            done = ctx.hours(g, a, b, "actual")
        elif g["kind"] == "habit":
            done = sum(1 for d in store.get_habit_dates(g["habit_id"]) if a.isoformat() <= d <= b.isoformat())
        else:
            done = None
        p = goal_pace(g, ctx)
        week = f"{amount(g, done)} of {amount(g, need)} this week" if done is not None else \
            f"{amount(g, g['value'])} of {amount(g, g['target'])} so far"
        out.append({"goal": g, "done": done, "need": need, "state": p["state"],
                    "text": f"{g['title']}: {week} · {STATES[p['state']].lower()}"})
    return out


# ---------------------------------------------------------------------------
# The mid-week nudge (notify.py) and Claude's snapshot
# ---------------------------------------------------------------------------

NUDGE_DAY = 2            # days after the week's first day (Wednesday for Monday weeks)
NUDGE_HOUR = 12


def nudges(now=None):
    """[(goal id, week start, title, body)] for hours goals that can't be hit this week with what's planned,
    from midday on the week's third day, at most once a week per goal (remembered in settings.json)."""
    now = now or store.local_now()
    first = week_days(now.date())[0]
    into = (now.date() - first).days
    if into < NUDGE_DAY or into == NUDGE_DAY and now.hour < NUDGE_HOUR:
        return []
    ctx = Ctx(now)
    sent = store.load_settings().get("goal_nudged") or {}
    out = []
    for w in week_goals(ctx.today, ctx):
        g = w["goal"]
        if sent.get(g["id"]) == first.isoformat() or w["short"] < 0.5 or w["over"]:
            continue
        out.append((g["id"], first.isoformat(), f"{g['title']}: {fmt(w['short'])} h short this week",
                    f"Planned {fmt(w['covered'])} of {fmt(w['want'])} h. Click its chip on the Timetable to fit the rest."))
    return out


def mark_nudged(goal_id, week_start):
    sent = dict(store.load_settings().get("goal_nudged") or {})
    sent[goal_id] = week_start
    store.save_settings(goal_nudged=sent)


def snapshot(ctx=None):
    """One line for Claude's [Now] section: the week's budget and each goal's state."""
    ctx = ctx or Ctx()
    paces = pace_all(ctx)
    if not paces:
        return ""
    budget = week_budget(ctx.today, ctx)
    goals = "; ".join(f"{p['goal']['title']} {STATES[p['state']].lower()}"
                      + (f" ({fmt(p['week']['covered'])}/{fmt(p['week']['want'])} h this week)" if p["week"] else "")
                      for p in paces)
    return f"{budget['text']} Goals: {goals}."
