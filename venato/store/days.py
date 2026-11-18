"""
A timetable day's life: its Plan locked at the start of the day, its Actual adjusted, then confirmed.

Before a day starts its Plan is whatever is on the timetable. When the day starts
(day_start, e.g. 07:00) the Plan is *locked*: lock_day copies it (and visible timed
calendar events) into every empty Actual slot of the whole day, never over an
Actual block already there (Focus sessions, hand-entered blocks). From then on the
day's Plan is frozen (what you meant to do) and every change goes to its Actual
(what you did). At the end of the day the user confirms the Actual; only confirmed
days count in stats and goals (Plan vs Actual).

tt_day_status.upto: "HH:mm" of the day's end once locked (older versions locked
part-days; lock_day finishes them); confirmed_at: set only by the user confirming.

The grid's JS (timetable_component.js) mirrors these rules only to show a
change instantly; what gets saved is always computed here.
"""

import uuid
from datetime import datetime, timedelta

from .database import db
from .dates import _as_date, local_now, stamp
from .grid import apply_block_ops, blocks_for, first_min, slot_count, slot_of, slot_time
from .outlook import _as_block, _visible_outlook, outlook_between
from .timetable import blocks_between, paint


def free_runs(day, first=0, last=None, now=None):
    """
    Free stretches of a day between slots first..last-1, as [(start, end)] slot pairs: in its Plan
    (no block of the user's and no visible, timed Outlook event), or once the day has started (its
    Plan locked), in its Actual, where the Plan and its events were copied.
    """
    last = slot_count() if last is None else last
    busy = [False] * slot_count()
    track = live_track(day, now)
    for b in blocks_between(day, day, track):
        for i in range(slot_of(b["start"]), min(slot_of(b["end"]), slot_count())):
            busy[i] = True
    for ev in outlook_between(day, day) if track == "plan" else ():
        if not ev["all_day"]:
            for i in range(slot_of(ev["start"]), min(slot_of(ev["end"]), slot_count())):
                busy[i] = True
    runs, start = [], None
    for i in range(first, last + 1):
        free = i < last and not busy[i]
        if free and start is None:
            start = i
        elif not free and start is not None:
            runs.append((start, i))
            start = None
    return runs


def slots_gone(day, now=None):
    """How many of a timetable day's slots have ended by `now` (all of them for a past day, 0 for a future one)."""
    now = now or local_now()
    start = datetime.combine(_as_date(day), datetime.min.time()) + timedelta(minutes=first_min())
    return max(0, min(slot_count(), int((now - start).total_seconds() // 1800)))


def day_started(day, now=None):
    """Has the timetable day begun (its first slot, day_start, reached)? Then its Plan is locked."""
    start = datetime.combine(_as_date(day), datetime.min.time()) + timedelta(minutes=first_min())
    return (now or local_now()) >= start


def live_track(day, now=None):
    """Where changes to a day go: its Plan until the day starts, then its Actual (the Plan is locked)."""
    return "actual" if day_started(day, now) else "plan"


def day_status(first, last):
    """{date: {"confirmed": bool, "upto": slots of Actual that are the truth}} for days with a status row."""
    with db() as conn:
        rows = conn.execute("SELECT date, confirmed_at, upto FROM tt_day_status WHERE date BETWEEN ? AND ?",
                            (_as_date(first).isoformat(), _as_date(last).isoformat())).fetchall()
    return {d: {"confirmed": bool(c), "upto": min(slot_count(), slot_of(u)) if u else 0} for d, c, u in rows}


def confirmed_days(first, last):
    """The confirmed timetable days between two dates (inclusive), as a sorted list of ISO dates."""
    return sorted(d for d, st in day_status(first, last).items() if st["confirmed"])


def _upto(conn, day):
    row = conn.execute("SELECT upto FROM tt_day_status WHERE date = ?", (day,)).fetchone()
    return min(slot_count(), slot_of(row[0])) if row and row[0] else 0


def _plan_items(conn, day):
    """The day's Plan as blocks: the user's own, and visible timed calendar events (as they'd be copied)."""
    items = blocks_for(conn, day, "plan") + [_as_block(r) for r in _visible_outlook(conn, day)]
    return sorted(items, key=lambda b: slot_of(b["start"]))


def materialise_ops(day, plan, actual, done, upto):
    """
    The blocks that materialising slots done..upto-1 of a day adds to its Actual: each Plan item (block or
    calendar event) copied into the runs of those slots where the Actual is empty. Ids are "m:<day>:<slot>"
    so the grid's JS (which mirrors this) and Python agree on them. Returns [("upsert", block)].
    """
    taken = [False] * slot_count()
    ids = {b["id"] for b in actual}
    for b in actual:
        for i in range(max(0, slot_of(b["start"])), min(slot_of(b["end"]), slot_count())):
            taken[i] = True
    ops = []
    for p in plan:
        s, e = max(slot_of(p["start"]), done), min(slot_of(p["end"]), upto, slot_count())
        i = s
        while i < e:
            if taken[i]:
                i += 1
                continue
            j = i
            while j < e and not taken[j]:
                taken[j] = True
                j += 1
            bid = f"m:{day}:{slot_time(i)}"
            if bid in ids:                                   # (a copy made earlier, since moved)
                bid = uuid.uuid4().hex
            ids.add(bid)
            ops.append(("upsert", {"id": bid, "date": day, "track": "actual", "start": slot_time(i),
                                   "end": slot_time(j), "label": p["label"], "category_id": p["category_id"],
                                   "details": p.get("details")}))
            i = j
    return ops


def lock_day(day, conn=None, now=None, confirm=False):
    """
    Lock a day's Plan once the day has started: copy the whole Plan (own blocks + visible timed calendar
    events) into the empty Actual slots, and remember it's done (upto = the whole day). From then on the
    Plan for that day is frozen (what you meant to do, as it was at the start of the day) and the Actual
    is what you change. Only with confirm=True does the day become confirmed: the user's own say-so.
    Idempotent (a part-materialised day from older versions gets the rest). Returns the blocks it added.
    """
    if conn is None:
        with db() as conn:
            return lock_day(day, conn, now, confirm)
    day = _as_date(day).isoformat()
    done = _upto(conn, day)
    if not day_started(day, now) or (done >= slot_count() and not confirm):   # not started (the Plan is still the Plan), or done
        return []
    ops = materialise_ops(day, _plan_items(conn, day), blocks_for(conn, day, "actual"), done, slot_count()) if done < slot_count() else []
    apply_block_ops(conn, ops)
    conn.execute(
        "INSERT INTO tt_day_status (date, confirmed_at, upto) VALUES (?, ?, ?) ON CONFLICT(date) DO UPDATE SET "
        "upto = excluded.upto, confirmed_at = COALESCE(confirmed_at, excluded.confirmed_at)",
        (day, stamp() if confirm else None, slot_time(slot_count())))
    return [b for _, b in ops]


def lock_started(first, last, now=None):
    """Lock every day from first to last (inclusive) that has started. Used before showing or changing them."""
    d, end = _as_date(first), min(_as_date(last), (now or local_now()).date())
    with db() as conn:
        while d <= end:
            lock_day(d, conn, now)
            d += timedelta(days=1)


def confirm_day(day, now=None):
    """The user says this is what they actually did: lock it (if not yet) and mark it confirmed."""
    return lock_day(day, now=now, confirm=True)


def unconfirm_day(day):
    """Undo a confirm: the day's Actual stays as it is, it just isn't confirmed (or counted) any more."""
    with db() as conn:
        conn.execute("UPDATE tt_day_status SET confirmed_at = NULL WHERE date = ?", (_as_date(day).isoformat(),))


def mark_confirmed(day):
    """Mark a started day locked and confirmed with its Actual exactly as it is (no Plan copied in): for an
    Actual that was filled in by hand or imported. Not for a day that hasn't started."""
    if not day_started(day):
        return
    with db() as conn:
        conn.execute("INSERT INTO tt_day_status (date, confirmed_at, upto) VALUES (?, ?, ?) ON CONFLICT(date) DO UPDATE "
                     "SET confirmed_at = COALESCE(confirmed_at, excluded.confirmed_at), upto = excluded.upto",
                     (_as_date(day).isoformat(), stamp(), slot_time(slot_count())))


def unconfirmed_days(first, last, now=None):
    """Past (or today's finished) timetable days between two dates that aren't confirmed yet."""
    status = day_status(first, last)
    out, d = [], _as_date(first)
    while d <= _as_date(last):
        iso = d.isoformat()
        if slots_gone(iso, now) >= slot_count() and not status.get(iso, {}).get("confirmed"):
            out.append(iso)
        d += timedelta(days=1)
    return out


def unconfirmed_days_with_blocks(now=None):
    """Every past (or today's finished) unconfirmed day that has something on it: a Plan or Actual
    block, or a visible timed calendar event. What "Confirm all" covers."""
    today = (now or local_now()).date().isoformat()
    with db() as conn:
        days = [r[0] for r in conn.execute(
            "SELECT date FROM tt_entries WHERE date <= ? UNION SELECT date FROM tt_outlook WHERE date <= ? "
            "AND all_day = 0 AND uid NOT IN (SELECT uid FROM tt_outlook_hidden) ORDER BY date",
            (today, today))]
    if not days:
        return []
    status = day_status(days[0], days[-1])
    return [d for d in days if slots_gone(d, now) >= slot_count() and not status.get(d, {}).get("confirmed")]


def correct(day, s, e, block, new_id=None, now=None):
    """
    A change to what happened: lock the day, then put `block` in Actual slots s..e-1
    (None = "didn't happen": nothing there). Returns the Actual blocks it overwrote.
    """
    with db() as conn:
        lock_day(day, conn, now)
        return paint(_as_date(day).isoformat(), "actual", s, e, block, new_id=new_id, conn=conn)


def retime(day, s0, e0, s, e, block, new_id=None, now=None):
    """'Change times' on the one timeline: what was in Actual slots s0..e0-1 happened at s..e-1 instead."""
    with db() as conn:
        lock_day(day, conn, now)
        day = _as_date(day).isoformat()
        paint(day, "actual", s0, e0, None, conn=conn)
        return paint(day, "actual", s, e, block, new_id=new_id, conn=conn)


def day_ended(day, now=None):
    """Has the day's last Plan block (or calendar event) ended? (Days with no Plan: once the day is over.)"""
    with db() as conn:
        items = _plan_items(conn, _as_date(day).isoformat())
    last = max((min(slot_of(b["end"]), slot_count()) for b in items), default=slot_count())
    return slots_gone(day, now) >= last
