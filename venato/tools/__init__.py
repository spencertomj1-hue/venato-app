"""
The actions Claude can take in Venato, as plain Python functions.

assistant.py exposes each one as an MCP tool; the tests call them directly.
They only use store.py, so the rules are the same as the app's pages.

Anything that deletes data, or overwrites/trims existing data, doesn't run
straight away: it returns a Result with a `pending` preview. The chat panel
shows that preview with Confirm / Cancel, and Confirm calls `pending.run()`,
which re-runs the same tool with confirmed=True (so it re-checks the data).
"""

import re
from datetime import date, datetime, time, timedelta

from venato import facade, store

from .common import (FILLER_WORDS, PERIOD_NAMES, Pending, Result, ToolError, _best_match, _date_range, _day,
    _now, _period, _period_day, nice_day)
from .daily_log import (add_habit, delete_habit, get_stats, list_habits, log_day, query_entries,
    rename_habit, set_habit, set_habit_target)


def _slot(value, is_end):
    """'HH:mm' on the half hour, within the timetable's hours -> slot index."""
    m = re.fullmatch(r"(\d{1,2}):(\d{2})", str(value).strip())
    if not m or int(m.group(1)) > 23 or m.group(2) not in ("00", "30"):
        raise ToolError(f"'{value}' isn't a valid time. Use HH:mm on the hour or half hour, e.g. 09:30.")
    t = f"{int(m.group(1)):02d}:{m.group(2)}"
    s = store.slot_of(t)
    lo, hi = (1, store.SLOTS) if is_end else (0, store.SLOTS - 1)
    if not lo <= s <= hi:
        raise ToolError(f"{t} is outside the timetable, which runs from {store.slot_time(0)} to "
                        f"{store.slot_time(store.SLOTS)}" + (" (next day)." if store.slot_time(store.SLOTS) <= store.slot_time(0) else "."))
    return s


def _track(value):
    v = str(value).strip().lower()
    if v not in store.TRACKS:
        raise ToolError("track must be 'plan' or 'actual'.")
    return v


def _category(label, category):
    cid = store.resolve_category(label=label, category=category)
    if cid is None:
        names = ", ".join(store.load_categories()["name"])
        what = f"category '{category}'" if category else f"default category for '{label}'"
        raise ToolError(f"There's no {what}. Ask the user which category to use: {names}.")
    return cid


def _cat_names():
    cats = store.load_categories()
    return dict(zip(cats["id"], cats["name"]))


def describe_block(b, names=None):
    names = names or _cat_names()
    cat = names.get(b["category_id"], "no category")
    return f"{b['label']} ({cat}) {b['start']}–{b['end']} {b['track']} on {nice_day(b['date'])}"


# ---------------------------------------------------------------------------
# Timetable
# ---------------------------------------------------------------------------

def list_categories():
    cats = store.load_categories()
    lines = []
    for group in store.groups():
        names = [f"{n} {c}" for n, g, c in zip(cats["name"], cats["grp"], cats["colour"]) if g == group]
        lines.append(f"{group}: " + ", ".join(names))
    names = dict(zip(cats["id"], cats["name"]))
    lm = store.load_label_map()
    lines.append("Default categories for activity labels: " + ", ".join(
        f"{lbl} → {names.get(cid, cid)}" for lbl, cid in zip(lm["label"], lm["category_id"])))
    return Result("\n".join(lines))


OUTLOOK_PREFIX = "outlook:"   # ids Claude sees for Outlook events (query_blocks)


def _outlook_event(block_id):
    """The Outlook event behind an "outlook:<uid>" id, or None for ordinary block ids."""
    if not str(block_id).startswith(OUTLOOK_PREFIX):
        return None
    ev = store.get_outlook(str(block_id)[len(OUTLOOK_PREFIX):])
    if not ev or ev["all_day"]:
        raise ToolError(f"There's no Outlook event with id {block_id} on the timetable. Use query_blocks.")
    return ev


def edit_category(name, colour=None, new_name=None, group=None, create=False):
    """Change a category's colour / name / group, or create a new one (create=True)."""
    cats = store.load_categories()
    match = [r for r in cats.to_dict("records") if r["name"].lower() == str(name).strip().lower()]
    if colour is not None and not re.fullmatch(r"#[0-9A-Fa-f]{6}", str(colour).strip()):
        raise ToolError("colour must be a hex code like #00B0F0.")
    if group is not None:
        group = next((g for g in store.groups() if g.lower() == str(group).strip().lower()), None)
        if group is None:
            raise ToolError(f"group must be one of: {', '.join(store.groups())}.")
    if new_name and new_name.strip().lower() != str(name).strip().lower() and \
            any(r["name"].lower() == new_name.strip().lower() for r in cats.to_dict("records")):
        raise ToolError(f"There's already a category called '{new_name}'.")

    if not match:
        if not create:
            raise ToolError(f"There's no category called '{name}'. Existing: {', '.join(cats['name'])}. "
                            "Set create=true to make a new one (ask the user first).")
        if colour is None:
            raise ToolError("A new category needs a colour (hex, e.g. #00B0F0).")
        cid = re.sub(r"[^a-z0-9]+", "_", str(name).strip().lower()).strip("_") or "category"
        group = group or store.groups()[0]
        store.save_category(cid, str(name).strip(), colour.strip(), group)
        return Result(f"Created category {str(name).strip()} ({colour.upper()}) in {group}.",
                      changed=True)

    cat = match[0]
    final_name = new_name.strip() if new_name else cat["name"]
    final_colour = colour.strip() if colour else cat["colour"]
    final_group = group or cat["grp"]
    if (final_name, final_colour.upper(), final_group) == (cat["name"], cat["colour"].upper(), cat["grp"]):
        return Result("Nothing to change.")
    store.save_category(cat["id"], final_name, final_colour, final_group, cat["text_colour"])
    changes = [f"{k} {v}" for k, v, old in (("name", final_name, cat["name"]),
                                            ("colour", final_colour.upper(), cat["colour"].upper()),
                                            ("group", final_group, cat["grp"])) if v != old]
    return Result(f"Updated {cat['name']}: " + ", ".join(changes) + ".", changed=True)


def set_outlook_category(category):
    """Which category Outlook events use (their colour on the timetable)."""
    cid = _category(None, category)
    store.save_settings(outlook_category=cid)
    return Result(f"Outlook events now use {_cat_names()[cid]}.", changed=True)


def set_activity_default(label, category):
    """Make an activity label (e.g. 'Lecture') default to a category."""
    label = str(label).strip()
    if not label:
        raise ToolError("Give the activity label.")
    cid = _category(None, category)
    store.set_label_default(label, cid)
    return Result(f"'{label}' now defaults to {_cat_names()[cid]}.", changed=True)


def add_block(date, track, start, end, label, category=None, details=None, confirmed=False):
    day, track = _day(date), _track(track)
    s, e = _slot(start, False), _slot(end, True)
    if e <= s:
        raise ToolError(f"end must be after start (the day runs {store.slot_time(0)} → {store.slot_time(store.SLOTS)}; "
                        "times after midnight count as the same day).")
    label = str(label).strip()
    if not label:
        raise ToolError("The block needs a label.")
    block = {"label": label, "category_id": _category(label, category), "details": (details or "").strip() or None}
    if track == "plan" and store.day_started(day, _now()):
        track = "actual"                            # that day's Plan is locked: changes are to what happens
    store.lock_day(day, now=_now())                 # a started day's Plan copied into its Actual first (no-op later)
    names = _cat_names()
    what = f"{label} ({names[block['category_id']]}) {store.slot_time(s)}–{store.slot_time(e)} {track} on {nice_day(day)}"

    affected = store.preview_paint(day, track, s, e, block)
    if affected and not confirmed:
        summary = f"Add {what}. This overwrites: " + "; ".join(describe_block(b, names) for b in affected)
        return Result("", pending=Pending(
            summary, lambda: add_block(date, track, start, end, label, category, details, True)))
    store.paint(day, track, s, e, block)
    return Result(f"Added {what}.", changed=True)


def _get_block(block_id):
    b = store.get_block(str(block_id))
    if not b:
        raise ToolError(f"There's no block with id {block_id}. Use query_blocks to find it.")
    return b


def update_block(block_id, label=None, category=None, date=None, track=None, start=None, end=None,
                 details=None, confirmed=False):
    """
    Change a block's label/category/description, or move/resize it. Always previewed
    first. An Outlook event ("outlook:<uid>") becomes the user's own block when changed.
    """
    ev = _outlook_event(block_id)
    if ev:
        old = store._as_block(ev)           # how it will look once it's the user's own block
    else:
        old = _get_block(block_id)
    names = _cat_names()
    new_label = str(label).strip() if label else old["label"]
    if category:
        cid = _category(new_label, category)
    elif label:
        # A new label may imply a new category; keep the old one if there's no default.
        cid = store.resolve_category(label=new_label) or old["category_id"]
    else:
        cid = old["category_id"]

    day = _day(date) if date else old["date"]
    trk = _track(track) if track else old["track"]
    if old["track"] == "plan" and store.day_started(old["date"], _now()):
        raise ToolError(f"The Plan for {nice_day(old['date'])} is locked (the day has started). "
                        "Change that day's actual blocks instead (query_blocks with track 'actual').")
    if trk == "plan" and store.day_started(day, _now()):
        trk = "actual"                              # moving into a started day: it goes in the Actual
    s = _slot(start, False) if start else store.slot_of(old["start"])
    e = _slot(end, True) if end else store.slot_of(old["end"])
    if e <= s:
        raise ToolError("end must be after start.")
    moved = (day, trk, s, e) != (old["date"], old["track"], store.slot_of(old["start"]), store.slot_of(old["end"]))
    new_details = old.get("details") if details is None else (details.strip() or None)
    new = {**old, "date": day, "track": trk, "start": store.slot_time(s), "end": store.slot_time(e),
           "label": new_label, "category_id": cid, "details": new_details}
    if not moved and (new_label, cid, new_details) == (old["label"], old["category_id"], old.get("details")):
        return Result("Nothing to change.")

    block = {"label": new_label, "category_id": cid, "details": new_details}
    summary = f"Change {describe_block(old, names)} → {describe_block(new, names)}"
    if ev:
        summary += " (it becomes your own block; Outlook itself isn't changed)"
    for d in {old["date"], day}:
        store.lock_day(d, now=_now())               # before working out what it overwrites
    affected = store.preview_paint(day, trk, s, e, block, exclude=old["id"]) if moved else []
    if moved and affected:
        summary += ". This overwrites: " + "; ".join(describe_block(b, names) for b in affected)
    if not confirmed:
        return Result("", pending=Pending(
            summary, lambda: update_block(block_id, label, category, date, track, start, end, details, True)))

    if ev:
        old_id = store.detach_outlook(ev["uid"])
    else:
        old_id = old["id"]
    if moved:
        with store.db() as conn:
            store.apply_block_ops(conn, [("delete", old_id)])
            store.paint(day, trk, s, e, block, conn=conn)
    else:
        store.set_block_label(old_id, new_label, cid, new_details)
    return Result(f"Done: {summary}.", changed=True)


def delete_block(block_id, confirmed=False):
    ev = _outlook_event(block_id)
    if ev and store.day_started(ev["date"], _now()):
        raise ToolError(f"The Plan for {nice_day(ev['date'])} is locked (the day has started), calendar events included. "
                        "Delete the matching actual block instead (query_blocks with track 'actual').")
    if ev:   # an Outlook event: remove it from the timetable only
        what = f"Remove the Outlook event {ev['title']} ({ev['exact']}) on {nice_day(ev['date'])} from the timetable"
        if not confirmed:
            return Result("", pending=Pending(what + " (it stays in Outlook)", lambda: delete_block(block_id, True)))
        store.hide_outlook(ev["uid"])
        return Result(f"Done: {what}.", changed=True)
    b = _get_block(block_id)
    if b["track"] == "plan" and store.day_started(b["date"], _now()):
        raise ToolError(f"The Plan for {nice_day(b['date'])} is locked (the day has started). "
                        "Delete the matching actual block instead (query_blocks with track 'actual').")
    summary = f"Delete {describe_block(b)}"
    if not confirmed:
        return Result("", pending=Pending(summary, lambda: delete_block(block_id, True)))
    store.delete_block(b["id"])
    return Result(f"Done: {summary}.", changed=True)


def _passed(day, s, e):
    """Slots s..e of a day cut to the part that has passed; None if none of it has."""
    gone = store.slots_gone(day, _now())
    return (s, min(e, gone)) if s < gone else None


def skip_block(block_id, confirmed=False):
    """
    "It didn't happen": a planned block (or calendar event, "outlook:<uid>") or an Actual block that has
    passed. The day's Actual becomes the truth (materialised) with nothing in those slots. Previewed first.
    The Timetable's "Didn't happen" button does the same.
    """
    ev = _outlook_event(block_id)
    b = store._as_block(ev) if ev else _get_block(block_id)
    span = _passed(b["date"], store.slot_of(b["start"]), store.slot_of(b["end"]))
    if not span:
        raise ToolError(f"{b['label']} on {nice_day(b['date'])} hasn't happened yet: change the Plan instead.")
    s, e = span
    summary = (f"Mark {b['label']} {store.slot_time(s)}–{store.slot_time(e)} on {nice_day(b['date'])} as not "
               "having happened (the Plan stays as it was)")
    if not confirmed:
        return Result("", pending=Pending(summary, lambda: skip_block(block_id, True)))
    store.correct(b["date"], s, e, None, now=_now())
    return Result(f"Done: {summary}.", changed=True)


def confirm_day(date=None, end_date=None, confirmed=False, preview=False):
    """
    Confirm that a day's Actual (or every unconfirmed day's from date to end_date) is what the user did, so it
    counts in stats and goals. A day not locked yet is locked first (its Plan copied into the empty Actual).
    Several days are previewed first. The same as "Confirm" on Home and "Confirm week" on the Timetable.
    """
    first = _day(date) if date else _now().date().isoformat()
    last = _day(end_date) if end_date else first
    if last < first:
        first, last = last, first
    today = _now().date().isoformat()
    if first > today:
        raise ToolError("That day hasn't happened yet.")
    days = store.unconfirmed_days(first, min(last, today), now=_now())
    if first == last == today and today not in days:
        days = [today]                                    # today, as it stands
    if not days:
        return Result(f"Nothing to confirm: every day from {nice_day(first)} to {nice_day(last)} is confirmed already.")
    summary = "Confirm " + ", ".join(nice_day(d) for d in days) + " as what you did"
    if (len(days) > 1 or preview) and not confirmed:
        return Result("", pending=Pending(summary, lambda: confirm_day(date, end_date, True)))
    for d in days:
        store.confirm_day(d, now=_now())
    return Result(f"Done: {summary}.", changed=True)


def confirm_all(confirmed=False):
    """
    Confirm every past day that isn't confirmed yet and has something on it, in one go: each one's Actual
    as it stands is what the user did. Always previewed first. "Confirm all" on the Timetable.
    """
    days = store.unconfirmed_days_with_blocks(now=_now())
    if not days:
        return Result("Nothing to confirm: every day that has passed is confirmed already.")
    n = len(days)
    summary = (f"Confirm {n} day{'s' if n > 1 else ''} as what you did: " + ", ".join(nice_day(d) for d in days) if n <= 7
               else f"Confirm {n} days as what you did, {nice_day(days[0])} to {nice_day(days[-1])}")
    if not confirmed:
        return Result("", pending=Pending(summary, lambda: confirm_all(True)))
    for d in days:
        store.confirm_day(d, now=_now())
    return Result(f"Done: {summary}.", changed=True)


def _days_between(first, last, weekdays_only):
    d, out = date.fromisoformat(first), []
    while d <= date.fromisoformat(last):
        if not weekdays_only or d.weekday() < 5:
            out.append(d.isoformat())
        d += timedelta(days=1)
    return out


def _in_day(t, is_end=False):
    try:
        _slot(t, is_end)
        return True
    except ToolError:
        return False


def _first_future_slot(day):
    """The first slot on a timetable day that hasn't started yet (SLOTS if the day is over)."""
    start = datetime.combine(date.fromisoformat(day), time(store.FIRST_MIN // 60, store.FIRST_MIN % 60))
    gone = (_now() - start).total_seconds() / 60
    return min(store.SLOTS, max(0, -(-int(gone) // 30)))


def _place(days, free, need, chunk):
    """
    Put `need` slots into the free runs ({day: [(start, end)]}, used up as it goes), one sitting of up
    to `chunk` slots per day per round so it spreads out, with a half-hour break after each sitting.
    Returns [(day, start slot, end slot)].
    """
    placed, left = [], need
    while left > 0:
        progress = False
        for d in days:                                       # one block per day per round: spreads it out
            if left <= 0 or not free[d]:
                continue
            want = min(chunk, left)
            # The earliest gap that fits the whole block, else the biggest gap there is.
            a, b = next((r for r in free[d] if r[1] - r[0] >= want), max(free[d], key=lambda r: r[1] - r[0]))
            s, e = a, min(b, a + want)
            placed.append((d, s, e))
            left -= e - s
            # Use up that gap, keeping a half-hour break after the block before the next one that day.
            rest = [(e + 1, b)] if e + 1 < b else []
            free[d] = sorted([r for r in free[d] if r != (a, b)] + rest)
            progress = True
        if not progress:
            break
    return placed


def _spaced(days, need, chunk):
    """If it needs fewer sittings than there are days, try evenly spaced days first
    (6 h in 2 h sittings over a week: Mon, Wed, Fri rather than Mon, Tue, Wed)."""
    sittings = -(-need // chunk)
    if sittings < len(days):
        spaced = [days[round(i * (len(days) - 1) / max(sittings - 1, 1))] for i in range(sittings)]
        days = list(dict.fromkeys(spaced + days))
    return days


def _window(earliest, latest):
    """Slots for earliest..latest; the default 09:00-21:00 is cut to the timetable's hours if they're shorter."""
    lo = _slot(earliest, False) if earliest != "09:00" or _in_day("09:00") else 0
    hi = _slot(latest, True) if latest != "21:00" or _in_day("21:00", True) else store.SLOTS
    if hi <= lo:
        raise ToolError("latest must be after earliest.")
    return lo, hi


def plan_time(label, hours, start_date, end_date, category=None, earliest="09:00", latest="21:00",
              max_block_hours=2, weekdays_only=False, confirmed=False):
    """
    Fit `hours` of an activity into the free gaps of the Plan between two dates,
    around the user's blocks and Outlook events, spread across the days (one
    block per day per round, up to max_block_hours each). Always previewed first.
    """
    label = str(label).strip()
    if not label:
        raise ToolError("Say what to plan (a label, e.g. 'Revision').")
    try:
        need = round(float(hours) * 2)                       # in 30-minute slots
    except (TypeError, ValueError):
        raise ToolError("hours must be a number, e.g. 6.")
    if need < 1:
        raise ToolError("hours must be at least 0.5.")
    first_day, last_day = _date_range(start_date, end_date, max_days=31)
    lo, hi = _window(earliest, latest)
    chunk = max(1, round(float(max_block_hours) * 2))
    cid = _category(label, category)
    days = _days_between(first_day, last_day, bool(weekdays_only))
    if not days:
        raise ToolError("There are no days in that range (check weekdays_only).")
    days = [d for d in days if _first_future_slot(d) < hi]           # nothing in the past
    if not days:
        raise ToolError("Those days are already over; pick days from today on.")

    days = _spaced(days, need, chunk)
    free = {d: store.free_runs(d, max(lo, _first_future_slot(d)), hi, now=_now()) for d in days}
    placed = _place(days, free, need, chunk)

    if not placed:
        return Result(f"There's no free time in the Plan between {earliest} and {latest} on those days.")
    placed.sort()
    names = _cat_names()
    got = sum(e - s for _, s, e in placed) / 2
    lines = "; ".join(f"{nice_day(d)} {store.slot_time(s)}–{store.slot_time(e)}" for d, s, e in placed)
    short = f" (only {got:g} of {need / 2:g} hours fit)" if got < need / 2 else ""
    summary = f"Plan {got:g} h of {label} ({names[cid]}){short}: {lines}"
    if not confirmed:
        return Result("", pending=Pending(summary, lambda: plan_time(
            label, hours, start_date, end_date, category, earliest, latest, max_block_hours, weekdays_only, True)))
    for d, s, e in placed:
        store.paint(d, store.live_track(d, _now()), s, e, {"label": label, "category_id": cid, "details": None})
    return Result(f"Done: {summary}.", changed=True)


def query_blocks(start_date, end_date, track=None):
    first, last = _date_range(start_date, end_date)
    trk = _track(track) if track else None
    names = _cat_names()
    rows = store.blocks_between(first, last, trk)
    lines = [
        f"- id {b['id']}: {nice_day(b['date'])} ({b['date']}) {b['track']} {b['start']}–{b['end']} "
        f"{b['label']} ({names.get(b['category_id'], 'no category')})"
        for b in rows
    ]
    if trk in (None, "plan"):
        for ev in store.outlook_between(first, last):
            where = f" at {ev['location']}" if ev["location"] else ""
            if ev["all_day"]:
                lines.append(f"- Outlook all-day: {nice_day(ev['date'])} ({ev['date']}) {ev['title']}{where}")
            else:
                lines.append(f"- id {OUTLOOK_PREFIX}{ev['uid']}: {nice_day(ev['date'])} ({ev['date']}) plan "
                             f"{ev['start']}–{ev['end']} (exactly {ev['exact']}) {ev['title']} (from Outlook){where}")
    return Result("\n".join(lines) or f"No timetable blocks between {first} and {last}.")


# ---------------------------------------------------------------------------
# To-dos: tick-off lists for a day, a week or a month
# ---------------------------------------------------------------------------


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


def add_todo(title, period, date=None, repeat=False, notes=None):
    """Add a to-do to the period containing `date` (default today)."""
    title, per = str(title).strip(), _period(period)
    if not title:
        raise ToolError("The to-do needs a title.")
    day = _period_day(date)
    store.roll_todos()
    start = store.start_of_period(per, day)
    if any(t["title"].lower() == title.lower() for t in store.todos_for(per, start)):
        return Result(f"'{title}' is already in {todo_list_name(per, start)}.")
    t = store.add_todo(title, per, day, notes=notes, repeat=bool(repeat))
    extra = f", repeating every {PERIOD_NAMES[per]}" if repeat else ""
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


# --- Deadlines ---

def describe_deadline(d, today=None):
    return f"'{d['title']}' due {nice_day(d['due'])} ({store.countdown(d['due'], today)})"


def _find_deadline(deadline, include_done=False):
    found = store.get_deadline(str(deadline).strip())
    if found:
        return found
    matches = _best_match(store.deadlines(include_done), deadline)
    if len(matches) == 1:
        return matches[0]
    if matches:
        options = "; ".join(f"id {d['id']}: {describe_deadline(d)}" for d in matches)
        raise ToolError(f"More than one deadline matches '{deadline}': {options}. Ask the user which one, or pass its id.")
    raise ToolError(f"There's no deadline matching '{deadline}'. Use list_deadlines to see them.")


def add_deadline(title, due, notes=None):
    try:
        did = store.add_deadline(title, _day(due), notes)
    except ValueError as e:
        raise ToolError(str(e))
    return Result(f"Added deadline {describe_deadline(store.get_deadline(did))}.", changed=True)


def list_deadlines(include_done=False):
    rows = store.deadlines(bool(include_done))
    if not rows:
        return Result("No deadlines.")
    return Result("\n".join(f"- id {d['id']}: {describe_deadline(d)}" + (" [done]" if d["done"] else "")
                            + (f" — {d['notes']}" if d["notes"] else "") for d in rows))


def complete_deadline(deadline, done=True):
    d = _find_deadline(deadline, include_done=True)
    store.set_deadline_done(d["id"], bool(done))
    return Result(f"{'Ticked off' if done else 'Reopened'} {describe_deadline(d)}.", changed=True)


def edit_deadline(deadline, title=None, due=None, notes=None):
    d = _find_deadline(deadline, include_done=True)
    try:
        store.update_deadline(d["id"], title=title if title is not None else store.KEEP,
                              due=_day(due) if due else store.KEEP, notes=notes if notes is not None else store.KEEP)
    except ValueError as e:
        raise ToolError(str(e))
    return Result(f"Updated: {describe_deadline(store.get_deadline(d['id']))}.", changed=True)


def delete_deadline(deadline, confirmed=False):
    d = _find_deadline(deadline, include_done=True)
    if not confirmed:
        return Result("", pending=Pending(f"Delete the deadline {describe_deadline(d)}",
                                          lambda: delete_deadline(d["id"], True)))
    store.delete_deadline(d["id"])
    return Result(f"Deleted the deadline '{d['title']}'.", changed=True)


def edit_todo(todo, period=None, date=None, title=None, notes=None, repeat=None, move_to=None):
    """Change a to-do's title / notes / repeat, and/or move it to the day, week or month list."""
    t = _find_todo(todo, period, date)
    changes = {k: v for k, v in (("title", title), ("notes", notes), ("repeat", repeat)) if v is not None}
    try:
        store.update_todo(t["id"], **changes)
    except ValueError as e:
        raise ToolError(str(e))
    if move_to:
        store.move_todo(t["id"], _period(move_to))
    if not changes and not move_to:
        return Result("Nothing to change: give a new title, notes, repeat or move_to.")
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
