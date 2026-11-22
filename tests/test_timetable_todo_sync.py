"""To-dos <-> timetable: a to-do scheduled into a slot, and ticked from either side."""

import importlib
from datetime import datetime

DAY = "2099-03-04"                      # far ahead: its Plan isn't locked


def _todo(store, title="Essay", minutes=None, day=DAY):
    return store.add_todo(title, "daily", day, minutes=minutes)


def _block(store, day=DAY, track="plan", start="09:00"):
    return next(b for b in store.blocks_between(day, day, track) if b["start"] == start)


def _schedule(store, todo, day=DAY, start="09:00"):
    from venato.ui import timetable
    return timetable.apply_grid_op({"kind": "schedule_todo", "todoId": todo["id"], "date": day, "start": start})


def test_schedule_todo_paints_a_plan_block_of_its_length(store):
    t = _todo(store, minutes=75)                       # 75 min -> 3 slots (rounded up)
    assert _schedule(store, t) is None
    b = _block(store)
    assert (b["label"], b["start"], b["end"]) == ("Essay", "09:00", "10:30")
    assert store.todo_links(DAY, DAY)[t["id"]] == {"date": DAY, "start": "09:00", "end": "10:30"}


def test_schedule_todo_defaults_to_thirty_minutes_and_moves_the_link(store):
    t = _todo(store)
    _schedule(store, t)
    assert _block(store)["end"] == "09:30"
    _schedule(store, t, start="14:00")                 # one block per to-do: scheduling again moves the link
    assert store.todo_links(DAY, DAY)[t["id"]]["start"] == "14:00"


def test_block_marked_done_ticks_the_todo(store):
    from venato.ui import timetable
    t = _todo(store)
    _schedule(store, t)
    b = _block(store)
    timetable.apply_grid_op({"kind": "set_status", "id": b["id"], "status": "done", "date": DAY,
                             "start": b["start"], "end": b["end"], "label": b["label"]})
    assert store.get_todo(t["id"])["done"]
    timetable.apply_grid_op({"kind": "set_status", "id": b["id"], "status": None, "date": DAY})
    assert not store.get_todo(t["id"])["done"]


def test_ticking_the_todo_marks_its_block(store):
    t = _todo(store)
    _schedule(store, t)
    b = _block(store)
    store.set_todo_done(t["id"], True)
    assert store.block_statuses(DAY, DAY)[b["id"]] == "done"
    store.set_todo_done(t["id"], False)
    assert b["id"] not in store.block_statuses(DAY, DAY)


def test_link_survives_the_day_locking(store):
    day = "2026-11-10"
    t = _todo(store, day=day)
    store.paint(day, "plan", store.slot_of("09:00"), store.slot_of("10:00"), {"label": "Essay", "category_id": None})
    store.link_todo(t["id"], day, "09:00", "10:00")
    store.lock_day(day, now=datetime(2026, 11, 11, 10, 0))
    a = _block(store, day, "actual")
    assert a["id"] != _block(store, day, "plan")["id"]  # the Actual copy has a new id
    store.set_todo_done(t["id"], True)
    assert store.block_statuses(day, day)[a["id"]] == "done"
    from venato.ui import timetable
    timetable.apply_grid_op({"kind": "set_status", "id": a["id"], "status": None, "date": day, "start": "09:00"})
    assert not store.get_todo(t["id"])["done"]


def test_moving_a_block_moves_the_link(store):
    t = _todo(store)
    _schedule(store, t)
    store.move_block(_block(store)["id"], "2099-03-05", "plan", store.slot_of("11:00"), store.slot_of("11:30"))
    assert store.todo_links(DAY, "2099-03-05")[t["id"]] == {"date": "2099-03-05", "start": "11:00", "end": "11:30"}


def test_deleting_a_todo_removes_its_link(store):
    t = _todo(store)
    _schedule(store, t)
    store.delete_todo(t["id"])
    assert store.todo_links(DAY, DAY) == {}


def test_grid_data_lists_the_days_todos_with_links(store, monkeypatch):
    from venato.ui import timetable
    t = store.add_detailed_todo("Essay", due=DAY)
    other = store.add_detailed_todo("Later", due="2099-03-06")
    _schedule(store, t)
    todos = timetable.grid_todos([DAY, "2099-03-05"])
    assert [(x["id"], x["date"], x["link"]["start"]) for x in todos] == [(t["id"], DAY, "09:00")]
    assert other["id"] not in {x["id"] for x in todos}


def test_tool_schedules_a_todo_and_completing_it_marks_the_block(store):
    from venato import tools
    tools = importlib.reload(tools)
    t = store.add_detailed_todo("Write essay", due=DAY)
    r = tools.schedule_todo("write essay", DAY, "10:00")
    assert r.changed and _block(store, start="10:00")["label"] == "Write essay"
    tools.complete_todo(t["id"])
    assert store.block_statuses(DAY, DAY)[_block(store, start="10:00")["id"]] == "done"
    tools.uncomplete_todo(t["id"])
    assert store.block_statuses(DAY, DAY) == {}


def test_home_done_list_picks_up_a_tick_from_the_timetable(store):
    from venato.ui import timetable
    today = store.local_today().isoformat()
    t = store.add_todo("Call mum", "daily", today)
    timetable.apply_grid_op({"kind": "schedule_todo", "todoId": t["id"], "date": "2099-01-01", "start": "09:00"})
    b = _block(store, "2099-01-01")
    timetable.apply_grid_op({"kind": "set_status", "id": b["id"], "status": "done", "date": "2099-01-01",
                             "start": "09:00"})
    assert t["id"] in {x["id"] for x in store.done_todos()}
    assert t["id"] not in {x["id"] for x in store.open_todos()}
