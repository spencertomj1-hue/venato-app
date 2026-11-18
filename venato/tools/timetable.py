"""
Tools for the timetable: categories, blocks in the Plan and the Actual, confirming days, and
fitting time into free slots (plan_time; the slot-finding helpers are shared with goal_time.py).
"""

import re
from datetime import date, datetime, time, timedelta

from venato import store

from .common import Pending, Result, ToolError, _date_range, _day, _now, nice_day


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
