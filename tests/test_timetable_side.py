"""The Timetable's side panel: pick a to-do or goal, paint it onto the week, and finishing the block counts."""

from pathlib import Path

from streamlit.testing.v1 import AppTest

import fragment_run
from nav_helpers import goto

APP = str(Path(__file__).resolve().parents[1] / "app.py")


def timetable():
    at = AppTest.from_file(APP, default_timeout=60).run()
    goto(at, "Timetable")
    assert not at.exception, at.exception
    return at


def paint(at, date, start, end, pick, op="p1"):
    ops = [{"opId": op, "kind": "paint", "date": date, "track": "plan", "start": start, "end": end,
            "block": {"label": pick["label"], "categoryId": pick["categoryId"] or "study"}, "newId": f"b-{op}",
            "link": {"kind": pick["kind"], "id": pick["id"]}}]
    fragment_run.trigger(at, "timetable", "ops", ops)
    assert not at.exception, at.exception


def future_day(store):
    from datetime import timedelta
    return (store.week_start_of(store.local_today()) + timedelta(days=13)).isoformat()   # never started


def test_panel_lists_todos_and_goals(store):
    t = store.add_todo("Prep for Redwave meeting", "daily", store.local_today())
    g = store.add_goal("Revision", "monthly", store.local_today(), 20, "h", category_id="study")
    at = timetable()
    assert at.button(key=f"tt_pick_todo_{t['id']}")
    assert at.button(key=f"tt_pick_goal_{g['id']}")
    assert not any(b.key == "tt_plan_goals" for b in at.button)                  # no "Plan this week"
    at.button(key=f"tt_pick_todo_{t['id']}").click().run()
    pick = fragment_run.component_data(at, "timetable")["pick"]
    assert pick["kind"] == "todo" and pick["id"] == t["id"] and pick["label"] == "Prep for Redwave meeting"
    at.button(key=f"tt_pick_todo_{t['id']}").click().run()                       # again: put down
    assert fragment_run.component_data(at, "timetable")["pick"] is None


def test_placing_a_todo_links_it_and_done_ticks_it(store):
    t = store.add_todo("Prep for Redwave meeting", "daily", store.local_today())
    at = timetable()
    at.button(key=f"tt_pick_todo_{t['id']}").click().run()
    pick = fragment_run.component_data(at, "timetable")["pick"]
    day = future_day(store)
    paint(at, day, "10:00", "11:00", pick)
    block = next(b for b in store.blocks_between(day, day, "plan"))
    assert block["label"] == "Prep for Redwave meeting"
    assert store.block_link(block["id"]) == ("todo", t["id"])
    assert store.get_todo(t["id"])["due"] == day                                # it had none: the block's day
    assert fragment_run.component_data(at, "timetable")["pick"] is None           # a to-do is placed once
    store.on_block_status(block["id"], None, "done")
    assert store.get_todo(t["id"])["done"]
    store.on_block_status(block["id"], "done", "missed")
    assert not store.get_todo(t["id"])["done"]


def test_count_goal_goes_up_when_a_sitting_is_done(store):
    g = store.add_goal("Show 5 people round", "monthly", store.local_today(), 5)
    store.link_block("blk", "goal", g["id"])
    store.on_block_status("blk", None, "done")
    store.on_block_status("blk", "done", "done")                                 # never twice
    assert store.get_goal(g["id"])["value"] == 1
    store.on_block_status("blk", "done", None)
    assert store.get_goal(g["id"])["value"] == 0


def test_hours_goal_block_counts_by_its_category(store):
    g = store.add_goal("Revision", "monthly", store.local_today(), 20, "h", category_id="study")
    at = timetable()
    at.button(key=f"tt_pick_goal_{g['id']}").click().run()
    pick = fragment_run.component_data(at, "timetable")["pick"]
    assert pick["categoryId"] == "study" and not pick["once"]
    day = future_day(store)
    paint(at, day, "09:00", "11:00", pick)
    b = store.blocks_between(day, day, "plan")[0]
    assert b["category_id"] == "study" and store.block_link(b["id"]) == ("goal", g["id"])
    assert store.goal_hours(store.get_goal(g["id"]), day, day, "plan") == 2
    assert fragment_run.component_data(at, "timetable")["pick"]["id"] == g["id"]   # still picked
