"""
Weekly review: the main numbers for one week, worked out from the data already
there (nothing new to log), plus the user's two reflections (store.weekly_reviews).

It's due from 7pm on Sunday: the first time Venato is opened after that, the review
of the week ending that Sunday pops up (ui/review.py). With weeks that start on
Sunday, that's the week that ended the day before. No Streamlit here.
"""

from datetime import timedelta

from venato import blocks, store

REVIEW_WEEKDAY = 6          # Sunday
REVIEW_HOUR = 19            # 7pm


def week_for(sunday):
    """The first day of the week a Sunday-evening review covers."""
    first = store.week_start_of(sunday)
    return first - timedelta(days=7) if first == sunday else first      # Sunday-start weeks: the one just ended


def due_week(now=None):
    """The week to review now: the one ending on the latest Sunday that's past 7pm."""
    now = now or store.local_now()
    back = (now.weekday() - REVIEW_WEEKDAY) % 7
    sunday = now.date() - timedelta(days=back)
    if back == 0 and now.hour < REVIEW_HOUR:
        sunday -= timedelta(days=7)
    return week_for(sunday)


def should_show(now=None):
    """The week whose review should pop up now (not seen yet, and with something in it), or None."""
    week = due_week(now)
    if store.get_review(week).get("seen_at"):
        return None
    return week if summary(week)["has_data"] else None      # e.g. a brand-new install: nothing to review


def _avg(rows, key):
    vals = [r[key] for r in rows if r.get(key) is not None]
    return round(sum(vals) / len(vals), 1) if vals else None


def _slot_maps(day):
    """({slot: category} for the Plan, the same for Actual) on one timetable day."""
    plan, actual = {}, {}
    default = store.outlook_category("")
    for ev in store.outlook_between(day, day):
        if not ev["all_day"] and ev["start"]:
            for s in range(store.slot_of(ev["start"]), min(store.slot_of(ev["end"]), store.SLOTS)):
                plan[s] = store.event_category(ev, default)
    for b in store.blocks_between(day, day):
        target = plan if b["track"] == "plan" else actual
        for s in range(store.slot_of(b["start"]), min(store.slot_of(b["end"]), store.SLOTS)):
            target[s] = b["category_id"]
    return plan, actual


def _time(days, now):
    """Hours per category (plan and actual), planned slots, matched slots and the confirmed days, over `days`.
    Only confirmed days count (an unconfirmed day's Plan is just assumed to have happened), and only time
    that's already happened (for "this week so far")."""
    hours, planned, matched = {}, 0, 0
    confirmed = set(store.confirmed_days(days[0], days[-1]))
    for d in days:
        if d not in confirmed:
            continue
        plan, actual = _slot_maps(d)
        cutoff = store.slots_gone(d, now)
        plan = {k: v for k, v in plan.items() if k < cutoff}
        actual = {k: v for k, v in actual.items() if k < cutoff}
        for track, slots in (("plan", plan), ("actual", actual)):
            for cat in slots.values():
                hours.setdefault(cat, {"plan": 0.0, "actual": 0.0})[track] += 0.5
        planned += len(plan)
        matched += sum(1 for s, cat in plan.items() if actual.get(s) == cat)
    return hours, planned, matched, confirmed


def _days(first):
    return [(first + timedelta(days=i)).isoformat() for i in range(7)]


def _pct(part, whole):
    return round(100 * part / whole) if whole else None


def _todos(first, days):
    todos = store.todos_for("weekly", first) + [t for d in days for t in store.todos_for("daily", d)]
    return sum(t["done"] for t in todos), len(todos)


def _numbers(first, now):
    """The few numbers compared week to week (and drawn as trends): plan followed, hours, to-dos."""
    days = _days(first)
    hours, planned, matched, _ = _time(days, now)
    done, total = _todos(first, days)
    return {"followed_pct": _pct(matched, planned), "actual_hours": sum(h["actual"] for h in hours.values()),
            "todos_done": done, "todos": total}


def _unconfirmed(days, now):
    """The week's days that are over (their Plan has ended) but haven't been confirmed on the timetable."""
    confirmed = set(store.confirmed_days(days[0], days[-1]))
    return [d for d in days if d not in confirmed and store.slots_gone(d, now) > 0 and store.day_ended(d, now)
            and (store.blocks_between(d, d) or store.outlook_between(d, d))]


def gaps(time, top=2, at_least=1.0):
    """The categories where the most planned time didn't happen (plan - actual, at least `at_least` hours)."""
    short = [t for t in time if t["plan"] - t["actual"] >= at_least]
    return sorted(short, key=lambda t: -(t["plan"] - t["actual"]))[:top]


def headline(s):
    """One line that says how the week went, before the numbers."""
    pct, before = s["followed_pct"], s["before"]["followed_pct"]
    if pct is None:
        if not s["days_confirmed"] and s["days_so_far"]:
            return "No days confirmed on the timetable yet, so there's no verdict on your time."
        return "Not much to go on yet."
    word = "Strong week" if pct >= 80 else "Solid week" if pct >= 60 else "Patchy week" if pct >= 40 else "Rough week"
    if not s["complete"]:
        word += " so far"
    trend = "" if before is None or abs(pct - before) < 5 else f", {'up' if pct > before else 'down'} from {before}%"
    parts = [f"{word}: {pct}% of the plan followed{trend}"]
    g = gaps(s["time"], top=1)
    if g:
        parts.append(f"{g[0]['category']} fell short ({g[0]['actual']:g} of {g[0]['plan']:g} h)")
    missed = [h["name"] for h in s["habits"] if not h["hit"]]
    if s["complete"] and missed:
        parts.append(f"{' and '.join(missed)} missed {'its' if len(missed) == 1 else 'their'} target"
                     if len(missed) <= 2 else f"{len(missed)} of {len(s['habits'])} habits missed their target")
    return ". ".join(parts) + "."


def planned_hours(days):
    """Hours on the Plan track (blocks and Outlook events) over `days` (ISO dates), confirmed or not."""
    return sum(len(_slot_maps(d)[0]) for d in days) / 2


def next_week_numbers(this_planned, next_planned, goals, tolerance=0.25):
    """
    The Next week card's numbers, from plain inputs (no store). this_planned / next_planned: hours on the
    Plan this week and next. goals: [{"title", "state", "need", "booked"}] for next week (need and booked in
    hours). Returns {"planned", "this_planned", "frac" (next / this, 0..1, None with nothing this week),
    "short": the goals that need time booked, most short first, each with "text"}.
    """
    short = []
    for g in goals:
        if g["state"] == "unreachable":
            short.append({**g, "gap": float("inf"), "text": "can't be reached · move the date?"})
        elif g["state"] not in ("done", "ended") and g["need"] - g["booked"] > tolerance:
            short.append({**g, "gap": g["need"] - g["booked"],
                          "text": f"needs {g['need']:g} h · {g['booked']:g} h booked"})
    short.sort(key=lambda g: -g["gap"])
    frac = None if not this_planned else min(1.0, next_planned / this_planned)
    return {"planned": next_planned, "this_planned": this_planned, "frac": frac, "short": short}


def next_week(first):
    """The week after the one starting `first`: deadlines aside, what's planned and what goals still need."""
    from venato import pace
    first = store._as_date(first)
    nxt = first + timedelta(days=7)
    ctx = pace.Ctx()
    rows = []
    for g in pace.priority(pace.goals_overlapping(nxt, nxt + timedelta(days=6))):
        state = pace.goal_pace(g, ctx)["state"]
        if g["kind"] != "hours" and state != "unreachable":
            continue                                   # only hours goals can be booked on the timetable
        start, end = pace.bounds(g)
        a, b = max(nxt, start), min(nxt + timedelta(days=6), end)
        need = pace.half_up(pace.week_need(g, nxt, ctx)[0]) if g["kind"] == "hours" else 0.0
        booked = ctx.hours(g, a, b, "plan") if g["kind"] == "hours" and a <= b else 0.0
        rows.append({"title": g["title"], "state": state, "need": need, "booked": round(booked * 2) / 2})
    return next_week_numbers(planned_hours(_days(first)), planned_hours(_days(nxt)), rows)


def trend(first, weeks=8):
    """The last `weeks` weeks up to the one starting `first`, oldest first: [{week, followed_pct,
    actual_hours, sleep}] (sleep None when Daily Log or its sleep switch is off, or nothing was logged)."""
    first, now = store._as_date(first), store.local_now()
    log_on = blocks.is_on("log") and store.tracks_sleep()
    out = []
    for i in range(weeks - 1, -1, -1):
        w = first - timedelta(days=7 * i)
        n = _numbers(w, now)
        rows = store.entries_between(w.isoformat(), (w + timedelta(days=6)).isoformat()).to_dict("records") \
            if log_on else []
        out.append({"week": w, "followed_pct": n["followed_pct"], "actual_hours": n["actual_hours"],
                    "sleep": _avg(rows, "sleep")})
    return out


def summary(first):
    """Everything the review shows for the week starting `first` (a date)."""
    first = store._as_date(first)
    last = first + timedelta(days=6)
    days = _days(first)
    today = store.local_today()

    # --- Time: hours per category, planned and actual; how much of the Plan was followed ---
    cats = store.load_categories()
    names, colours = dict(zip(cats["id"], cats["name"])), dict(zip(cats["id"], cats["colour"]))
    now = store.local_now()
    hours, planned, matched, confirmed = _time(days, now)
    so_far = sum(1 for d in days if store.slots_gone(d, now) > 0)       # days of the week begun by now
    time = [{"category": names.get(c, "Uncategorised"), "colour": colours.get(c, "#8B8D98"), **h}
            for c, h in sorted(hours.items(), key=lambda kv: -(kv[1]["actual"] + kv[1]["plan"]))]

    # --- Daily log, against the week before (nothing when the Daily Log block is off) ---
    log_on = blocks.is_on("log")
    this = store.entries_between(days[0], days[-1]).to_dict("records")
    prev = store.entries_between((first - timedelta(days=7)).isoformat(), (first - timedelta(days=1)).isoformat()).to_dict("records")
    if not log_on:
        this, prev = [], []
    measures = [k for k, on in (("sleep", store.tracks_sleep()), ("water", store.tracks_water())) if on]
    log = {k: {"now": _avg(this, k), "before": _avg(prev, k)} for k in measures}

    # --- Habits ---
    targets, habits = store.habit_targets(), []
    for hid, name in (store.get_habits() if log_on else []):
        done = store.get_habit_dates(hid)
        ticks = sum(d in done for d in days)
        target = targets.get(hid, 7)
        habits.append({"name": name, "ticks": ticks, "target": target, "hit": ticks >= target})

    # --- To-dos: the week's list, and each day's ---
    weekly = store.todos_for("weekly", first)
    daily = [t for d in days for t in store.todos_for("daily", d)]

    # --- Last week: its numbers (for the changes), and what they said they'd do differently ---
    prev_first = first - timedelta(days=7)
    before = _numbers(prev_first, now)

    # --- Deadlines that were due this week, and the ones coming up next week ---
    all_deadlines = store.deadlines(include_done=True)
    due = [d for d in all_deadlines if days[0] <= d["due"] <= days[-1]]
    upcoming = [d for d in all_deadlines if not d["done"] and last < store._as_date(d["due"]) <= last + timedelta(days=7)]

    # --- Goals: each one's week against what it needed then, and its pace now ---
    from venato import pace
    goals = pace.review_rows(first)

    journal = store.journal_entries(first=days[0], last=days[-1]) if log_on else []
    sections = blocks.review_sections(first, last)        # what the switched-on blocks say about the week
    has_data = bool(hours or store.blocks_between(days[0], days[-1]) or any(this) or any(h["ticks"] for h in habits) or weekly or daily or journal or sections)
    s = {
        "first": first, "last": last, "complete": last < today, "has_data": has_data,
        "time": time, "planned_hours": planned / 2, "actual_hours": sum(h["actual"] for h in time),
        "followed_pct": _pct(matched, planned),
        "days_confirmed": len(confirmed), "days_so_far": so_far, "unconfirmed": _unconfirmed(days, now),
        "before": before, "promise": store.get_review(prev_first).get("to_change"),
        "log": log, "days_logged": len(this),
        "habits": habits,
        "todos": {"weekly_done": sum(t["done"] for t in weekly), "weekly": len(weekly),
                  "daily_done": sum(t["done"] for t in daily), "daily": len(daily)},
        "deadlines": {"met": [d for d in due if d["done"]], "missed": [d for d in due if not d["done"]],
                      "upcoming": upcoming},
        "journal": journal, "goals": goals,
        "review": store.get_review(first),
        "sections": sections,
    }
    s["headline"] = headline(s)
    return s


def as_text(s):
    """The summary in a few lines, for Claude."""
    lines = [f"Week {s['first']} to {s['last']}" + ("" if s["complete"] else " (so far)"), s["headline"]]
    if s["planned_hours"] or s["actual_hours"]:
        lines.append(f"Time: {s['planned_hours']:g} h planned, {s['actual_hours']:g} h logged as done"
                     + (f", {s['followed_pct']}% of the Plan followed" if s["followed_pct"] is not None else "")
                     + f" (from {s['days_confirmed']} of {s['days_so_far']} days confirmed)")
        lines.append("By category (plan / actual): " + ", ".join(
            f"{t['category']} {t['plan']:g}/{t['actual']:g} h" for t in s["time"]))
        b = s["before"]
        if b["followed_pct"] is not None or b["actual_hours"]:
            lines.append(f"The week before: {b['actual_hours']:g} h logged"
                         + (f", {b['followed_pct']}% of the Plan followed" if b["followed_pct"] is not None else ""))
    if s["unconfirmed"]:
        lines.append(f"Days over but not confirmed (not counted): {', '.join(s['unconfirmed'])}")
    for k, v in s["log"].items():
        if v["now"] is not None:
            lines.append(f"Average {k}: {v['now']}" + (f" (week before {v['before']})" if v["before"] is not None else ""))
    if s["habits"]:
        lines.append("Habits: " + ", ".join(f"{h['name']} {h['ticks']}/{h['target']}" for h in s["habits"]))
    t = s["todos"]
    lines.append(f"To-dos: weekly {t['weekly_done']}/{t['weekly']}, daily {t['daily_done']}/{t['daily']}")
    d = s["deadlines"]
    if d["met"] or d["missed"] or d["upcoming"]:
        lines.append(f"Deadlines: met {[x['title'] for x in d['met']]}, missed {[x['title'] for x in d['missed']]}, "
                     f"next week {[x['title'] + ' ' + x['due'] for x in d['upcoming']]}")
    if s.get("goals"):
        lines.append("Goal pace: " + "; ".join(x["text"] for x in s["goals"]))
    if s["journal"]:
        lines.append(f"Journal entries: {len(s['journal'])}")
    for sec in s.get("sections", []):
        lines.append(f"{sec['title']}: " + "; ".join(sec["lines"]))
    r = s["review"]
    if s["promise"]:
        lines.append(f"The week before, they said they'd do differently: {s['promise']}"
                     + (f" (did they? {r['kept']})" if r.get("kept") else ""))
    if r.get("went_well") or r.get("to_change"):
        lines.append(f"Their reflections: went well: {r.get('went_well') or '-'}; to change: {r.get('to_change') or '-'}")
    return "\n".join(lines)
