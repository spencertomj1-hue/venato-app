"""
Keeps the timetable filled in by itself (runs on every page load, cheap when nothing changed):

- Training: every session of the plan that isn't done and isn't in the past goes on the
  timetable (training.py's time, or the nearest free time that day), unless the user took
  it off (deleted its block, or unticked "On my timetable").

- To-dos (switched off in run(): to-dos stay off the timetable): every unticked to-do in today's and this week's lists that's in the diary gets a slot
  as long as it should take (30 minutes if not set), and keeps one until it's ticked off:
    - one with a due date, and daily ones, in the next free time from now (09:00-22:00);
    - weekly ones on Sunday if there's room (10:00-20:00), else Saturday, else the next free time.
  When a to-do's slot has passed it stays there for the rest of that day, so it can be marked
  done or not done on the timetable; not done, or not answered by the next day, and it moves
  to the next free slot.
  So does one that something has landed on, such as a new Outlook event, which would hide it.
  A slot the user moved is otherwise kept as long as it's still ahead. Unticked to-dos from earlier
  days and weeks are brought forward into today's / this week's list.
  Deleting a to-do's block from the timetable takes that to-do off the timetable for good.

Nothing here ever covers the user's own blocks or Outlook events: only free time is used.
SQL lives in store.py.
"""

from datetime import datetime, timedelta

from venato import store

DAY_HOURS = ("09:00", "22:00")          # when daily to-dos go
SUNDAY_HOURS = ("10:00", "20:00")       # when weekly to-dos go, preferably on Sunday
LOOK_AHEAD = 7                          # days to search for a free slot


def _now():
    return store.local_now()


def _next_slot(now):
    """The first slot of today's timetable that starts at or after `now`."""
    minutes = now.hour * 60 + now.minute - store.FIRST_MIN
    if now.hour < 1:                    # 00:00-01:00 belongs to the day before; treat as end of day
        return store.SLOTS
    return max(0, -(-minutes // store.SLOT_MIN))


def _slot_range(day, today, now, hours):
    lo, hi = store.slot_of(hours[0]), store.slot_of(hours[1])
    if day == today:
        lo = max(lo, _next_slot(now))
    return lo, hi


def _length(todo):
    """How many timetable slots a to-do takes."""
    return max(1, -(-(todo.get("minutes") or store.TODO_MINUTES) // store.SLOT_MIN))


def _find_place(todo, today, now):
    """(date, slot) for a to-do's block, or None if there's no room in the next week."""
    days = [today + timedelta(days=i) for i in range(LOOK_AHEAD)]
    length = _length(todo)
    if todo.get("due"):
        # Its own date: the first free time from today up to that day, else the first after it.
        tries = [(d, DAY_HOURS) for d in days]
    elif todo["period"] == "weekly":
        sunday = store.start_of_period("weekly", today) + timedelta(days=6)
        saturday = sunday - timedelta(days=1)
        preferred = [(sunday, SUNDAY_HOURS), (saturday, SUNDAY_HOURS)]
        tries = [(d, h) for d, h in preferred if d >= today] + [(d, DAY_HOURS) for d in days]
    else:
        tries = [(d, DAY_HOURS) for d in days]
    for day, hours in tries:
        lo, hi = _slot_range(day, today, now, hours)
        s = store.free_slot(day.isoformat(), lo, hi, length)
        if s is not None:
            return day, s
    return None


def _still_ahead(block, now):
    return block and store.slot_start(block["date"], store.slot_of(block["end"])) > now


def schedule_todos(today=None, now=None):
    """Give every open to-do a slot (or a new one, if its slot has passed). Returns how many were placed."""
    now = now or _now()
    today = today or now.date()
    store.bring_forward_todos(today)
    todos = store.open_todos(today)
    if not todos:
        return 0
    category = store.todo_category()
    placed = 0
    for t in todos:
        block_id = store.TODO_BLOCK + t["id"]
        block = store.get_block(block_id)
        waiting = block and block["date"] == today.isoformat()     # passed today: wait for an answer
        if (_still_ahead(block, now) or waiting) and not store.slot_clash(block):
            continue
        if block:
            store.delete_block(block_id)          # its time passed or it's covered: free it before looking again
        place = _find_place(t, today, now)
        if not place:
            continue
        day, s = place
        due = store.todo_due(t)
        store.put_block({"id": block_id, "date": day.isoformat(), "track": "plan",
                         "start": store.slot_time(s), "end": store.slot_time(s + _length(t)),
                         "label": t["title"],
                         "category_id": category,
                         "details": f"To-do, due {due:%a} {due.day} {due:%b}. "
                                    "It moves to the next free time until you tick it off."})
        placed += 1
    return placed


def schedule_training(today=None):
    """Put every upcoming, unfinished session on the timetable if it isn't there. Returns how many."""
    from venato import tools
    plan = store.active_plan()
    if not plan:
        return 0
    today = (today or store.local_today()).isoformat()
    times = store.load_settings().get("training_times")
    placed = 0
    for s in store.plan_sessions(plan["id"]):
        if s["done"] or s["off_timetable"] or s["date"] < today or store.session_block(s):
            continue
        tools.place_session(s, times)
        placed += 1
    return placed


def run(now=None):
    """
    Training onto the timetable. To-dos no longer go on it (the user didn't want them there):
    they're only brought forward on their lists, and any to-do blocks are cleared away.
    schedule_todos is kept, unused, in case that's ever wanted back.
    Returns True if the timetable changed.
    """
    try:
        store.bring_forward_todos((now or _now()).date())
        return bool(schedule_training() + store.clear_todo_blocks())
    except Exception:
        return False                      # never let scheduling stop the app from opening
