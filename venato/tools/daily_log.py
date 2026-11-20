"""
Tools for the daily log (notes, and sleep and water when switched on), habits, and the stats over them.
"""

import re

from venato import store

from .common import Pending, Result, ToolError, _date_range, _day, nice_day


def log_day(date, notes=None, append_notes=False, confirmed=False, sleep=None, water=None):
    """Set fields of a day's log (notes, and sleep and water if switched on); untouched fields keep their values."""
    day = _day(date)
    for name, value, on in (("sleep", sleep, store.tracks_sleep()), ("water", water, store.tracks_water())):
        if value is not None and not on:
            raise ToolError(f"{name.capitalize()} tracking is off. The user can switch it on in Settings → Daily Log.")
    old = store.get_entry(day)
    new = {k: old.get(k) for k in ("notes", "sleep", "water")}
    changes, overwrites = [], []

    for name, value, lo, hi in (("sleep", sleep, 0, 24), ("water", water, 0, 15)):
        if value is None:
            continue
        value = float(value)
        if not lo <= value <= hi:
            raise ToolError(f"{name} must be between {lo} and {hi}.")
        if name == "water" and old.get(name) is not None and old[name] != value:
            changes.append(f"water {old[name]:g} → {value:g} L")      # a running total: no need to confirm
        elif old.get(name) is not None and old[name] != value:
            overwrites.append(f"{name} {old[name]} → {value}")
        elif old.get(name) != value:
            changes.append(f"{name} {value}")
        new[name] = value

    if notes:
        notes = notes.strip()
        if append_notes and old.get("notes"):
            new["notes"] = f"{old['notes']}\n\n{notes}"
            changes.append("notes added to")
        elif old.get("notes") and old["notes"] != notes:
            overwrites.append(f"notes replaced (were: “{old['notes']}”)")
            new["notes"] = notes
        else:
            new["notes"] = notes
            changes.append("notes")

    if not changes and not overwrites:
        if any(v is not None for v in (notes, sleep, water)):
            return Result(f"Nothing to change: {nice_day(day)} already has those values.")
        raise ToolError("Give at least one of notes" + (", sleep" if store.tracks_sleep() else "")
                        + (", water" if store.tracks_water() else "") + ".")

    summary = f"{nice_day(day)} log: " + ", ".join(overwrites + changes)
    if overwrites and not confirmed:
        return Result(
            "",
            pending=Pending(summary, lambda: log_day(date, notes, append_notes, True, sleep, water)),
        )
    with store.db() as conn:
        store.save_entry(conn, day, new["notes"], new["sleep"], new["water"])
    return Result(f"Saved. {summary}.", changed=True)


def _find_habit(name):
    found = store.find_habit(name)
    if not found:
        names = ", ".join(n for _, n in store.get_habits()) or "none yet"
        raise ToolError(f"There's no habit called '{name}'. Existing habits: {names}. "
                        "Ask the user before adding a new one.")
    return found


def set_habit(date, habit_name, done, confirmed=False):
    day = _day(date)
    habit_id, name = _find_habit(habit_name)
    ticked = day in store.get_habit_dates(habit_id)
    if bool(done) == ticked:
        return Result(f"{name} is already {'ticked' if ticked else 'not ticked'} on {nice_day(day)}.")
    summary = f"{'Tick' if done else 'Untick'} {name} on {nice_day(day)}"
    if not done and not confirmed:
        return Result("", pending=Pending(summary, lambda: set_habit(date, habit_name, done, True)))
    with store.db() as conn:
        store.set_habit_done(conn, habit_id, day, bool(done))
    return Result(f"Done: {summary}.", changed=True)


def _per_week(times_per_week):
    if times_per_week in (None, "", 0):
        return None
    try:
        n = int(times_per_week)
    except (TypeError, ValueError):
        raise ToolError("times_per_week must be a whole number from 1 to 7.")
    if not 1 <= n <= 7:
        raise ToolError("times_per_week must be from 1 to 7 (or leave it out for every day).")
    return n


def _often(per_week):
    return f"{per_week} time{'s' * (per_week > 1)} a week" if per_week else "every day"


def add_habit(name, times_per_week=None):
    name = str(name).strip()
    if not name:
        raise ToolError("The habit needs a name.")
    if store.find_habit(name):
        return Result(f"A habit called '{name}' already exists.")
    per_week = _per_week(times_per_week)
    store.add_habit(name, per_week)
    return Result(f"Added habit '{name}' ({_often(per_week)}).", changed=True)


def set_habit_target(habit_name, times_per_week=None):
    """How often a habit is meant to happen: N times a week, or every day (None / 0)."""
    habit_id, name = _find_habit(habit_name)
    per_week = _per_week(times_per_week)
    store.set_habit_target(habit_id, per_week)
    return Result(f"{name} is now {_often(per_week)}.", changed=True)


def rename_habit(habit_name, new_name):
    habit_id, name = _find_habit(habit_name)
    try:
        store.rename_habit(habit_id, new_name)
    except ValueError as e:
        raise ToolError(str(e))
    return Result(f"Renamed the habit {name} to {str(new_name).strip()}.", changed=True)


def delete_habit(habit_name, confirmed=False):
    habit_id, name = _find_habit(habit_name)
    ticks = len(store.get_habit_dates(habit_id))
    if not confirmed:
        return Result("", pending=Pending(f"Delete the habit {name} and its {ticks} tick{'s' * (ticks != 1)}",
                                          lambda: delete_habit(name, True)))
    store.delete_habit(habit_id)
    return Result(f"Deleted the habit {name}.", changed=True)


def list_habits(today=None):
    today = today or store.local_today()
    lines = []
    for habit_id, name in store.get_habits():
        dates = store.get_habit_dates(habit_id)
        progress, _, per_week = store.habit_progress(habit_id, dates, today)
        done_today = "done today" if today.isoformat() in dates else "not done today"
        lines.append(f"- {name} ({_often(per_week)}): {done_today}, {progress}")
    return Result("\n".join(lines) or "No habits yet.")


def query_entries(start_date, end_date):
    first, last = _date_range(start_date, end_date)
    entries = {e["date"]: e for e in store.entries_between(first, last).to_dict("records")}
    ticks = store.habit_ticks_between(first, last)
    sleep_on, water_on = store.tracks_sleep(), store.tracks_water()
    lines = []
    for day in sorted(set(entries) | set(ticks)):
        e = entries.get(day, {})
        parts = []
        if sleep_on and e.get("sleep") is not None:
            parts.append(f"sleep {e['sleep']:g} h")
        if water_on and e.get("water") is not None:
            parts.append(f"water {e['water']:g} L")
        if e.get("notes"):
            parts.append(f"notes: “{e['notes']}”")
        if ticks.get(day):
            parts.append("habits: " + ", ".join(ticks[day]))
        if parts:
            lines.append(f"- {day} ({nice_day(day)}): " + "; ".join(parts))
    return Result("\n".join(lines) or f"Nothing logged between {first} and {last}.")


def get_stats(period="30d", today=None):
    """period: '7d', '30d', '90d', 'all', or a number of days."""
    p = str(period).strip().lower()
    if p == "all":
        days = None
    else:
        m = re.fullmatch(r"(\d+)\s*d?", p)
        if not m or int(m.group(1)) < 1:
            raise ToolError("period must be like '7d', '30d', '90d' or 'all'.")
        days = int(m.group(1))
    s = store.get_stats(days, today)
    hours = {track: ", ".join(f"{k} {v:g}h" for k, v in sorted(h.items(), key=lambda kv: -kv[1])) or "none"
             for track, h in s["timetable_hours"].items()}
    habits = ", ".join(f"{k} {v:g}%" for k, v in s["habit_completion_pct"].items()) or "no habits"
    averages = ", ".join(([f"sleep {s['avg_sleep']}h"] if store.tracks_sleep() else [])
                         + ([f"water {s['avg_water']} L/day"] if store.tracks_water() else []))
    averages = f"Averages: {averages}\n" if averages else ""
    return Result(
        f"{s['start']} to {s['end']} ({s['days']} days, {s['days_logged']} logged)\n"
        f"{averages}"
        f"Habit completion: {habits}\n"
        f"Timetable (only the {s['days_confirmed']} confirmed days of {s['days']}; unconfirmed days are only assumed) "
        f"plan hours: {hours['plan']}\n"
        f"Timetable actual hours: {hours['actual']}"
    )
