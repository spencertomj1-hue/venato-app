"""Goals that count timetable hours (Phase 0): the goal mode, goal_hours, and the tools/CSV around them."""

from io import StringIO

import pandas as pd
import pytest


def block(store, day, start, end, label, cat, track="actual"):
    store.paint(day, track, store.slot_of(start), store.slot_of(end), {"label": label, "category_id": cat})


def test_hours_goal_counts_actual_hours_in_the_period(store):
    g = store.add_goal("Study", "monthly", "2026-11-10", 20, "h", category_id="study")
    assert (g["kind"], g["category"], g["value"]) == ("hours", "Study", 0)
    block(store, "2026-10-31", "09:00", "11:00", "Revision", "study")        # last month: not counted
    block(store, "2026-11-02", "09:00", "11:00", "Revision", "study")
    block(store, "2026-11-03", "14:00", "15:30", "Homework", "study")
    block(store, "2026-11-03", "16:00", "17:00", "Revision", "study", track="plan")   # Plan doesn't count
    block(store, "2026-11-04", "09:00", "10:00", "Gym", "exercise")
    assert store.get_goal(g["id"])["value"] == 3.5


def test_label_narrows_it_to_one_activity(store):
    g = store.add_goal("Revise", "monthly", "2026-11-01", 10, category_id="study", label="revision")
    block(store, "2026-11-02", "09:00", "11:00", "Revision", "study")
    block(store, "2026-11-02", "12:00", "13:00", "Homework", "study")
    assert store.get_goal(g["id"])["value"] == 2                             # any case, exact label
    assert store.get_goal(g["id"])["label"] == "revision"


def test_goal_hours_counts_calendar_events_in_the_plan_but_not_detached_ones(store):
    g = store.add_goal("Classes", "monthly", "2026-11-01", 10, category_id="classes")
    store.replace_outlook([
        {"uid": "a", "date": "2026-11-02", "start": "09:00", "end": "11:00", "title": "Lecture", "location": None,
         "all_day": 0, "exact": "09:00–11:00"},
        {"uid": "b", "date": "2026-11-03", "start": "09:00", "end": "10:00", "title": "Seminar", "location": None,
         "all_day": 0, "exact": "09:00–10:00"},
        {"uid": "c", "date": "2026-11-04", "start": None, "end": None, "title": "Open day", "location": None,
         "all_day": 1, "exact": None},
    ])
    assert store.goal_hours(g, "2026-11-01", "2026-11-30", "plan") == 3
    store.detach_outlook("b")                                                # detached: fixed time from now on
    assert store.goal_hours(g, "2026-11-01", "2026-11-30", "plan") == 2
    assert store.goal_hours(g, "2026-11-01", "2026-11-30", "actual") == 0
    # a window cuts each day to some slots
    nine = store.slot_of("10:00")
    assert store.goal_hours(g, "2026-11-02", "2026-11-02", "plan", window=lambda d: (nine, store.SLOTS)) == 1


def test_habit_and_hours_are_mutually_exclusive(store):
    store.add_habit("Gym")
    hid = store.find_habit("gym")[0]
    with pytest.raises(ValueError):
        store.add_goal("Gym", "monthly", "2026-11-01", 12, habit_id=hid, category_id="exercise")
    g = store.add_goal("Gym", "monthly", "2026-11-01", 12, habit_id=hid)
    store.update_goal(g["id"], category_id="exercise", label="Gym")          # switching unlinks the habit
    got = store.get_goal(g["id"])
    assert (got["habit_id"], got["category_id"], got["kind"]) == (None, "exercise", "hours")
    store.update_goal(g["id"], habit_id=hid)                                 # and the other way round
    got = store.get_goal(g["id"])
    assert (got["habit_id"], got["category_id"], got["label"], got["kind"]) == (hid, None, None, "habit")


def test_deleting_the_category_unlinks_the_goal(store):
    store.save_category("guitar", "Guitar", "#123456", "Life")
    g = store.add_goal("Guitar", "monthly", "2026-11-01", 8, category_id="guitar")
    store.set_goal_progress(g["id"], 3)
    with store.db() as conn:
        conn.execute("DELETE FROM tt_categories WHERE id = 'guitar'")
    got = store.get_goal(g["id"])
    assert (got["category_id"], got["kind"], got["value"]) == (None, "count", 3)   # back to the hand-kept number


def test_hours_goals_with_non_default_day_hours(store):
    store.save_settings(day_start=6, day_end=22)
    g = store.add_goal("Run", "monthly", "2026-11-01", 5, category_id="exercise")
    block(store, "2026-11-02", "06:00", "07:30", "Run", "exercise")
    assert store.get_goal(g["id"])["value"] == 1.5


def test_csv_keeps_the_category_and_label(store):
    g = store.add_goal("Revise", "monthly", "2026-11-01", 10, "h", category_id="study", label="Revision")
    csv = store.load_goals().to_csv(index=False)
    assert store.save_goals(pd.read_csv(StringIO(csv)), replace=True) == 1
    got = store.get_goal(g["id"])
    assert (got["category_id"], got["label"]) == ("study", "Revision")


def test_tools_add_and_edit_hours_goals(store):
    import importlib
    from venato import tools
    tools = importlib.reload(tools)
    r = tools.add_goal("Revision", 20, category="Study", label="Revision", date="2026-11-05")
    assert "Actual hours of Revision (Study)" in r.text
    g = store.goals_in("monthly", "2026-11-05")[0]
    assert (g["unit"], g["kind"]) == ("h", "hours")
    with pytest.raises(tools.ToolError):
        tools.log_goal_progress(g["id"], 1)
    with pytest.raises(tools.ToolError):
        tools.add_goal("X", 2, category="Nope")
    tools.edit_goal(g["id"], unlink_category=True)
    assert store.get_goal(g["id"])["kind"] == "count"
