"""Merging categories, the training plan, the joint calendar's privacy rule, and code mode's git safety net."""

import importlib
import subprocess
from datetime import date

import pytest


@pytest.fixture
def tools(store):
    from venato import tools as tools_module
    return importlib.reload(tools_module)


# ---------------------------------------------------------------------------
# Merging categories
# ---------------------------------------------------------------------------

def test_merge_categories_moves_blocks_and_needs_confirm(tools, store):
    tools.add_block("2026-11-02", "plan", "09:00", "10:00", "Chat", category="Social")
    store.set_label_default("Party", "social")
    store.save_settings(outlook_category="social")
    r = tools.merge_categories("Social", "Chores")
    assert r.pending and "1 block and 1 activity default" in r.pending.summary
    assert "social" in set(store.load_categories()["id"])          # nothing yet
    done = r.pending.run()
    assert done.changed
    assert "social" not in set(store.load_categories()["id"])
    assert store.blocks_between("2026-11-02", "2026-11-02")[0]["category_id"] == "chores"
    assert store.resolve_category(label="Party") == "chores"
    assert store.load_settings()["outlook_category"] == "chores"


def test_merge_into_itself_or_unknown(tools):
    from venato.tools import ToolError
    with pytest.raises(ToolError):
        tools.merge_categories("Chores", "chores")
    with pytest.raises(ToolError):
        tools.merge_categories("Nope", "Chores")


# ---------------------------------------------------------------------------
# Training plan
# ---------------------------------------------------------------------------

def test_plan_shape_progressive_overload():
    from venato import training
    first, race, sessions = training.generate(date(2026, 11, 2))          # a Monday
    assert first == date(2026, 11, 2) and race == date(2026, 12, 27) and race.weekday() == 6
    per_week = [sum(1 for s in sessions if s["week"] == w) for w in range(1, 9)]
    assert per_week[0] == 3 and max(per_week) == 5
    km = [sum(s["distance_km"] or 0 for s in sessions if s["week"] == w) for w in range(1, 8)]
    assert km[0] < km[1] < km[2] and km[3] < km[2]                       # build, then a cutback
    assert max(km) == km[5] and km[6] < km[5]                            # peak in week 6, then taper
    long_runs = [s["distance_km"] for s in sessions if s["kind"] == "long"]
    assert long_runs[0] == 8 and max(long_runs) == 15
    assert sessions[-1]["kind"] == "race" and sessions[-1]["distance_km"] == 21.1


def test_plan_starting_mid_week_spreads_week_one():
    from venato import training
    first, race, sessions = training.generate(date(2026, 11, 5))          # a Thursday
    week1 = [s["date"] for s in sessions if s["week"] == 1]
    assert first == date(2026, 11, 5)
    assert week1 == ["2026-11-05", "2026-11-07", "2026-11-08"]           # Thu, Sat, Sun (long run)
    assert race == date(2026, 12, 27)
    first, _, _ = training.generate(date(2026, 11, 8))                    # Sunday: too late, start Monday
    assert first == date(2026, 11, 9)


def test_training_tools(tools, store, monkeypatch):
    monkeypatch.setattr(store, "local_today", lambda: date(2026, 11, 4))
    r = tools.create_training_plan()
    assert r.changed and "race day Sun 27 Dec" in r.text
    assert "Week 1 (Base)" in tools.list_training().text
    r = tools.log_session(date="2026-11-05", actual_km=5.5, notes="felt good")
    assert "✓ done (5.5 km)" in r.text
    r = tools.edit_session(date="2026-11-07", new_date="2026-11-06")
    assert "Fri 6 Nov" in r.text
    r = tools.edit_session(date="2026-12-27", new_date="2027-01-03")       # moving the race moves race day
    assert store.active_plan()["race_date"] == "2027-01-03"
    again = tools.create_training_plan()
    assert again.pending                                                  # replacing needs confirmation
    assert tools.delete_training_plan().pending.run().changed
    assert store.active_plan() is None


# ---------------------------------------------------------------------------
# Joint calendar
# ---------------------------------------------------------------------------

ICS = b"""BEGIN:VCALENDAR
VERSION:2.0
BEGIN:VEVENT
UID:a
SUMMARY:Dentist appointment
LOCATION:Secret clinic
DESCRIPTION:private notes
DTSTART:20261105T100000Z
DTEND:20261105T110000Z
END:VEVENT
BEGIN:VEVENT
UID:b
SUMMARY:Dinner with you!
DTSTART:20261105T190000Z
DTEND:20261105T210000Z
END:VEVENT
BEGIN:VEVENT
UID:c
SUMMARY:Late shift
DTSTART:20261105T230000Z
DTEND:20261106T020000Z
END:VEVENT
END:VCALENDAR
"""


def test_joint_hides_titles_without_mark(store):
    from venato import joint
    rows = joint.rows_from(ICS, today=date(2026, 11, 4))
    by_uid = {r["uid"].split("|")[0]: r for r in rows if r["date"] == "2026-11-05"}
    assert by_uid["a"]["title"] is None and (by_uid["a"]["start_min"], by_uid["a"]["end_min"]) == (600, 660)
    assert by_uid["b"]["title"] == "Dinner with you"
    assert "Secret" not in repr(rows) and "private" not in repr(rows) and "Dentist" not in repr(rows)
    late = [r for r in rows if r["uid"].startswith("c|")]
    assert [(r["date"], r["start_min"], r["end_min"]) for r in late] == [("2026-11-05", 1380, 1440), ("2026-11-06", 0, 120)]


def test_joint_connect_and_week(store, monkeypatch):
    from venato import joint
    from tests.conftest import MemoryKeyring
    monkeypatch.setattr(joint, "keyring", MemoryKeyring())
    url = joint.check_link("webcal://outlook.office365.com/owa/calendar/x/y/calendar.html")
    assert url == "https://outlook.office365.com/owa/calendar/x/y/calendar.ics"
    assert joint.connect(url, "Nina", fetcher=lambda _: ICS) == 4
    assert joint.partner_name() == "Nina" and joint.partner_url() == url
    events = joint.events_for_week(date(2026, 11, 2))
    assert {e["who"] for e in events} == {"partner"} and len(events) == 4
    joint.disconnect()
    assert joint.partner_url() is None and joint.events_for_week(date(2026, 11, 2)) == []


def test_joint_page_renders(store, monkeypatch):
    from streamlit.testing.v1 import AppTest
    def page():
        from venato.ui import joint_ui
        joint_ui.render_page()
    at = AppTest.from_function(page)
    at.run(timeout=120)
    assert not at.exception
    assert any("Joint calendar" in h.value for h in at.header)


def test_training_page_renders(store):
    from streamlit.testing.v1 import AppTest
    from venato import training
    first, race, sessions = training.generate(date(2026, 11, 5))
    store.create_plan(training.PLAN_NAME, first.isoformat(), race.isoformat(), sessions)
    def page():
        from venato.ui import training_ui
        training_ui.render_page()
    at = AppTest.from_function(page)
    at.run(timeout=120)
    assert not at.exception
    assert len(at.expander) >= 8


# ---------------------------------------------------------------------------
# Code mode: each message's code changes become one undoable commit
# ---------------------------------------------------------------------------

def test_code_mode_commits_only_what_changed(tmp_path, monkeypatch):
    from venato import code_mode
    repo = tmp_path / "repo"
    repo.mkdir()
    git = lambda *a: subprocess.run(["git", *a], cwd=repo, check=True, capture_output=True)
    git("init", "-q")
    git("config", "user.email", "t@example.com")
    git("config", "user.name", "T")
    (repo / "a.py").write_text("a = 1\n")
    (repo / "mine.py").write_text("x = 1\n")
    git("add", "-A")
    git("commit", "-qm", "start")
    monkeypatch.setattr(code_mode, "APP_DIR", repo)

    (repo / "mine.py").write_text("x = 2\n")          # the user's own unsaved work
    before = code_mode.snapshot()
    (repo / "a.py").write_text("a = 2\n")             # what "Claude" changes
    (repo / "new.py").write_text("n = 1\n")
    changed = code_mode.changed_since(before)
    assert changed == ["a.py", "new.py"]
    sha = code_mode.commit(changed, "make  a two\n please")
    assert sha
    assert code_mode.history()[0][1] == "Venato chat: make a two please"
    assert (repo / "mine.py").read_text() == "x = 2\n"
    status = subprocess.run(["git", "status", "--porcelain"], cwd=repo, capture_output=True, text=True).stdout
    assert status.strip() == "M mine.py"               # the user's work is still uncommitted

    ok, _ = code_mode.undo(sha)
    assert ok and (repo / "a.py").read_text() == "a = 1\n" and not (repo / "new.py").exists()


# ---------------------------------------------------------------------------
# Simple goals, renaming habits, training sessions on the timetable
# ---------------------------------------------------------------------------

def test_simple_goals(tools, store, monkeypatch):
    monkeypatch.setattr(store, "local_today", lambda: date(2026, 11, 4))
    r = tools.add_goal("Sub 19:30 5 km", period="yearly")
    assert r.changed and "not done yet" in r.text
    g = store.goals_in("yearly", date(2026, 11, 4))[0]
    assert g["kind"] == "simple" and not g["done"]
    from venato.tools import ToolError
    with pytest.raises(ToolError):
        tools.log_goal_progress("Sub 19:30")
    assert "Achieved" in tools.complete_goal("sub 19:30").text
    g = store.get_goal(g["id"])
    assert g["done"] and g["done_at"]
    assert "simple goal, done" in tools.list_goals().text
    tools.add_goal("Gym", target=12, unit="sessions")                    # counting goals still work
    assert store.goals_in("monthly", date(2026, 11, 4))[0]["kind"] == "target"


def test_rename_habit(tools, store):
    tools.add_habit("Gym")
    tools.add_habit("Read")
    tools.set_habit("2026-11-02", "Gym", True)
    assert "Renamed" in tools.rename_habit("gym", "Lift").text
    hid, name = store.find_habit("Lift")
    assert store.get_habit_dates(hid) and store.find_habit("Gym") is None
    from venato.tools import ToolError
    with pytest.raises(ToolError):
        tools.rename_habit("Lift", "read")


def test_training_sessions_go_on_the_timetable_without_covering_anything(tools, store, monkeypatch):
    monkeypatch.setattr(store, "local_today", lambda: date(2026, 11, 4))
    tools.add_block("2026-11-05", "plan", "18:00", "19:00", "Dinner", category="Meals")   # Thu 5 Nov, in the way
    assert "timetable" in tools.create_training_plan().text
    s = [x for x in store.plan_sessions(store.active_plan()["id"]) if x["date"] == "2026-11-05"][0]
    block = store.session_block(s)
    assert block and block["start"] == "19:00" and block["end"] == "20:00"      # next free time, 5 km ≈ 47 min
    assert [b["label"] for b in store.blocks_between("2026-11-05", "2026-11-05")].count("Dinner") == 1
    r = tools.edit_session(date="2026-11-05", new_date="2026-11-06", time="07:00")
    moved = store.session_block(store.get_session(s["id"]))
    assert moved["date"] == "2026-11-06" and moved["start"] == "07:00"
    assert not [b for b in store.blocks_between("2026-11-05", "2026-11-05") if b["id"] == moved["id"]]
    tools.delete_training_plan().pending.run()
    assert not [b for b in store.blocks_between("2026-11-01", "2027-01-31") if b["id"].startswith("tr:")]


# ---------------------------------------------------------------------------
# Autoplan: to-dos and training fill in the timetable by themselves
# ---------------------------------------------------------------------------

from datetime import datetime


def _todo_block(store, todo):
    return store.get_block(store.TODO_BLOCK + todo["id"])


def test_todos_get_slots_and_move_on_until_done(store):
    from venato import autoplan
    wed = date(2026, 11, 4)
    now = datetime(2026, 11, 4, 14, 10)
    with store.db() as conn:                                   # 14:30-15:30 is taken
        store.apply_block_ops(conn, [("upsert", {"id": "x", "date": "2026-11-04", "track": "plan", "start": "14:30",
                                                 "end": "15:30", "label": "Lecture", "category_id": "classes"})])
    daily = store.add_todo("Buy monitors", "daily", wed)
    weekly = store.add_todo("Meal prep", "weekly", wed)
    assert autoplan.schedule_todos(wed, now) == 2
    b = _todo_block(store, daily)
    assert (b["date"], b["start"], b["end"]) == ("2026-11-04", "15:30", "16:00")      # next free half hour
    w = _todo_block(store, weekly)
    assert (w["date"], w["start"]) == ("2026-11-08", "10:00")                         # Sunday morning
    assert "To-dos" in list(store.load_categories()["name"])
    assert autoplan.schedule_todos(wed, now) == 0                                     # nothing changes
    # The slot passes without it being ticked: it waits there for the rest of the day...
    later = datetime(2026, 11, 4, 16, 5)
    autoplan.schedule_todos(wed, later)
    assert _todo_block(store, daily)["start"] == "15:30"
    # ...and moves on the next day.
    thu, morning = date(2026, 11, 5), datetime(2026, 11, 5, 8, 0)
    autoplan.schedule_todos(thu, morning)
    assert (_todo_block(store, daily)["date"], _todo_block(store, daily)["start"]) == ("2026-11-05", "09:00")
    # Ticked: off the timetable.
    store.set_todo_done(daily["id"], True)
    assert _todo_block(store, daily) is None
    assert autoplan.schedule_todos(thu, morning) == 0


def test_unticked_todos_carry_over_and_deleted_blocks_stay_deleted(store):
    from venato import autoplan
    from venato.ui import timetable
    old = store.add_todo("Dakar", "daily", date(2026, 11, 3))
    thu = date(2026, 11, 5)
    autoplan.schedule_todos(thu, datetime(2026, 11, 5, 8, 0))
    assert store.get_todo(old["id"])["period_start"] == "2026-11-05"                  # brought forward
    assert _todo_block(store, old)["start"] == "09:00"
    block_id = store.TODO_BLOCK + old["id"]
    timetable.apply_grid_op({"kind": "delete", "id": block_id})
    import streamlit as st
    st.session_state["timetable"] = {"ops": [{"opId": "o1", "kind": "delete", "id": block_id}]}
    timetable._on_ops("timetable")
    autoplan.schedule_todos(thu, datetime(2026, 11, 5, 8, 0))
    assert _todo_block(store, old) is None                                            # stays off


def test_training_auto_placed(store, monkeypatch):
    from venato import autoplan, training
    monkeypatch.setattr(store, "local_today", lambda: date(2026, 11, 4))
    first, race, sessions = training.generate(date(2026, 11, 5))
    store.create_plan(training.PLAN_NAME, first.isoformat(), race.isoformat(), sessions)
    assert autoplan.schedule_training() == len(sessions)
    s = store.plan_sessions(store.active_plan()["id"])[0]
    assert store.session_block(s)["start"] == "18:00"
    store.unplace_session(s["id"])                                                    # "On my timetable" unticked
    assert autoplan.schedule_training() == 0


def test_dragging_a_training_block_moves_the_session(store, monkeypatch):
    from venato import autoplan, training
    from venato.ui import timetable
    import streamlit as st
    monkeypatch.setattr(store, "local_today", lambda: date(2026, 11, 4))
    first, race, sessions = training.generate(date(2026, 11, 5))
    store.create_plan(training.PLAN_NAME, first.isoformat(), race.isoformat(), sessions)
    autoplan.schedule_training()
    s = store.plan_sessions(store.active_plan()["id"])[0]
    b = store.session_block(s)
    # What the grid sends when the block is dragged to Friday 07:30.
    st.session_state["timetable"] = {"ops": [
        {"opId": "m1", "kind": "delete", "id": b["id"]},
        {"opId": "m2", "kind": "paint", "date": "2026-11-06", "track": "plan", "start": "07:30", "end": "08:30",
         "block": {"label": b["label"], "categoryId": b["category_id"], "details": b["details"]}, "newId": b["id"]}]}
    timetable._on_ops("timetable")
    moved = store.get_session(s["id"])
    assert moved["date"] == "2026-11-06" and not moved["off_timetable"]
    nb = store.session_block(moved)
    assert (nb["date"], nb["start"], nb["end"], nb["details"]) == ("2026-11-06", "07:30", "08:30", b["details"])
    assert autoplan.schedule_training() == 0                     # stays where it was put


def _sunday_lunch(start="12:30", end="14:00"):
    return {"uid": "lunch", "date": "2026-11-08", "start": start, "end": end, "title": "Lunch at Lin",
            "location": None, "all_day": 0, "exact": f"{start}-{end}"}


def test_outlook_event_landing_on_a_todo_moves_it(store):
    """A to-do from the journal sat at Sunday 12:30, then a lunch came in from Outlook and hid it."""
    from venato import autoplan, journal
    thu, now = date(2026, 11, 5), datetime(2026, 11, 5, 21, 0)
    journal.save(thu.isoformat(), "^Act of Service for Nina^")
    assert autoplan.schedule_todos(thu, now) == 1
    todo = store.todos_for("weekly", date(2026, 11, 2))[0]
    block_id = store.TODO_BLOCK + todo["id"]
    block = store.get_block(block_id)
    store.put_block({**block, "start": "12:30", "end": "13:00"})
    assert autoplan.schedule_todos(thu, now) == 0                   # clear, so it stays where it is

    store.replace_outlook([_sunday_lunch()])
    assert autoplan.schedule_todos(thu, now) == 1
    moved = store.get_block(block_id)
    assert moved["date"] == "2026-11-08" and not store.slot_clash(moved)
    assert autoplan.schedule_todos(thu, now) == 0                   # and it stays put once it's clear


def test_slot_clash_ignores_events_that_only_touch(store):
    block = {"id": "b", "date": "2026-11-08", "track": "plan", "start": "12:00", "end": "12:30",
             "label": "x", "category_id": "study", "details": None}
    store.put_block(block)
    store.replace_outlook([_sunday_lunch()])
    assert not store.slot_clash(block)
    store.put_block({**block, "id": "c", "start": "11:30", "end": "12:30"})
    assert store.slot_clash(block)
