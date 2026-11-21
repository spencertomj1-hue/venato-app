"""
The few words in each Home tile's header ("1 of 4 done today", "2 behind", "Now: Study"). No Streamlit here.
Each takes today's date (and the time, where it matters) so the tests can pin them; each returns "" when
there's nothing worth saying.
"""

from datetime import timedelta

from venato import store


def todos(today=None):
    today = today or store.local_today()
    items = store.todos_for("daily", today)
    if not items:
        return "Nothing for today"
    return f"{sum(1 for t in items if t['done'])} of {len(items)} done today"


def _label(item):
    return (item.get("label") or item.get("title") or item.get("category_id") or "").strip()


def timetable(now=None):
    """What's on now, else what's next today, else nothing planned."""
    now = now or store.local_now()
    day, hm = now.date().isoformat(), now.strftime("%H:%M")
    slots = [(b["start"], b["end"], _label(b)) for b in store.blocks_between(day, day, track="plan")]
    slots += [(e["start"], e["end"], _label(e)) for e in store.outlook_between(day, day)
              if not e["all_day"] and e["start"]]
    slots.sort()
    for start, end, label in slots:
        if start <= hm < end:
            return f"Now: {label}" if label else "Something on now"
    later = [s for s in slots if s[0] > hm]
    if later:
        start, _, label = later[0]
        from venato import regional
        return f"Next: {label} at {regional.time(start)}" if label else f"Next at {regional.time(start)}"
    return "Nothing more today" if slots else "Nothing planned today"


def goals(ctx=None):
    from venato import pace
    try:
        rows = pace.pace_all(ctx)
    except Exception:
        return ""
    if not rows:
        return "No goals running"
    behind = sum(1 for p in rows if p["state"] in ("behind", "slipping", "unreachable"))
    return f"{behind} behind" if behind else "On track"


def deadlines(today=None):
    today = today or store.local_today()
    rows = [d for d in store.deadlines() if not d.get("done")]
    if not rows:
        return "Nothing due"
    first = min(rows, key=lambda d: str(d["due"]))
    days = (store._as_date(first["due"]) - today).days
    if days < 0:
        return "Overdue"
    return "Due today" if days == 0 else "Due tomorrow" if days == 1 else f"Next in {days} days"


def habits(today=None):
    today = (today or store.local_today()).isoformat()
    rows = store.get_habits()
    if not rows:
        return "No habits yet"
    done = sum(1 for habit_id, _ in rows if today in store.get_habit_dates(habit_id))
    return f"{done} of {len(rows)} today"


def journal(today=None):
    today = (today or store.local_today()).isoformat()
    return "Written today" if (store.get_entry(today).get("notes") or "").strip() else "Not written yet"


def journal_week(today=None):
    """This week's journal at a glance: {"days": [(ISO date, written?)], first day of the week first,
    "streak": days written in a row up to today (or yesterday, until today's is written: the Daily Log's rule)}."""
    from venato import pace
    today = today or store.local_today()
    written = {e["date"] for e in store.journal_entries(last=today)}
    week = pace.week_days(today)
    return {"days": [(d.isoformat(), d.isoformat() in written) for d in week],
            "streak": store.streaks(written, today)[0]}


def habit_streak(habit_id, today=None):
    """A habit's current streak (days, or weeks for a habit with a weekly target): the Daily Log's own rule."""
    return store.habit_progress(habit_id, store.get_habit_dates(habit_id), today or store.local_today())[1]


def focus(today=None):
    from venato.blocks import focus as f
    r = f.running()
    if r:
        return "Paused" if r["paused_at"] else "Running"
    today = today or store.local_today()
    mins = f.totals(today, today)[1].get(today.isoformat(), 0)
    return f"{mins:.0f} min today" if mins else ""


def hours(h):
    """3, 4.5 (hours, to the half hour)."""
    h = round(h * 2) / 2
    return f"{h:g}"


def module_week(ctx=None):
    """[(module, {"done", "planned", "goal", "term"} hours)] for every module, this week (grades.module_hours)."""
    from venato import pace
    from venato.blocks import grades as gr
    ctx = ctx or pace.Ctx()
    return [(m, gr.module_hours(m, ctx)) for m in gr.modules()]


def modules(ctx=None):
    """This week's study hours across the modules: "4 of 12 h this week"."""
    rows = module_week(ctx)
    if not rows:
        return "No modules yet"
    done, goal = sum(h["done"] for _, h in rows), sum(h["goal"] for _, h in rows)
    return f"{hours(done)} of {hours(goal)} h this week"


def review(today=None, now=None):
    p = week_followed(today, now)["pct"]
    return "" if p is None else f"{p}% of plan followed"


def needs_you():
    from venato.ui import goal_time
    items = goal_time.needs_items()
    n = sum(len(items[k]) for k in ("days", "goals", "deadlines", "blocks")) + bool(items["assistant"]) + bool(items["feedback"])
    return f"{n} thing{'s' * (n != 1)}" if n else "All clear"


def week_followed(today=None, now=None):
    """This week's Plan followed so far: {"pct": the week's % (None: nothing confirmed yet),
    "days": [% or None per day, Monday first]}."""
    from venato import pace
    from venato import review as rv
    now = now or store.local_now()
    first = pace.week_days(today or now.date())[0]
    days = [(first + timedelta(days=i)).isoformat() for i in range(7)]
    per_day = []
    for d in days:
        _, planned, matched, _ = rv._time([d], now)
        per_day.append(round(100 * matched / planned) if planned else None)
    _, planned, matched, _ = rv._time(days, now)
    return {"pct": round(100 * matched / planned) if planned else None, "days": per_day}
