"""The journal (to-dos from "quotes" and ^carets^), the gym log, and training ticks showing on the timetable."""

import importlib
from datetime import date

import pytest


@pytest.fixture
def journal(store):
    from venato import journal as module
    return importlib.reload(module)


def test_extract_marks():
    from venato import journal
    text = 'Long day. Need to "buy monitors" and “call the bank”. This week: ^meal prep^, and ^Meal prep^ again. "buy monitors"'
    assert journal.extract(text) == [("daily", "Buy monitors"), ("daily", "Call the bank"), ("weekly", "Meal prep")]
    assert journal.extract("No marks here, it's fine.") == []
    assert journal.extract('An unfinished "quote') == []


def test_journal_makes_todos_once(journal, store):
    day = "2026-11-05"                                         # a Thursday
    with store.db() as conn:
        store.save_entry(conn, day, 4, 7.5, 3, None)
    added = journal.save(day, 'Felt good. "Buy monitors" and ^Meal prep^')
    assert added == [("daily", "Buy monitors"), ("weekly", "Meal prep")]
    assert [t["title"] for t in store.todos_for("daily", day)] == ["Buy monitors"]
    assert [t["title"] for t in store.todos_for("weekly", day)] == ["Meal prep"]
    assert not store.todos_for("weekly", day)[0]["repeat"]    # journal to-dos are one-offs
    entry = store.get_entry(day)
    assert entry["notes"].startswith("Felt good") and entry["mood"] == 4 and entry["sleep"] == 7.5   # kept
    # Saving again (or after deleting the to-do) doesn't add it again.
    store.delete_todo(store.todos_for("daily", day)[0]["id"])
    assert journal.save(day, 'Felt good. "Buy monitors" and ^Meal prep^ "Gym"') == [("daily", "Gym")]
    assert [t["title"] for t in store.todos_for("daily", day)] == ["Gym"]
    # While typing (not final), nothing is made.
    assert journal.save(day, 'more "half typed', make_todos=False) == []


def test_journal_page_renders(store):
    from streamlit.testing.v1 import AppTest

    def page():
        from venato.ui import daily_log
        daily_log.page_daily_log()
    at = AppTest.from_function(page)
    at.run(timeout=120)
    assert not at.exception
    assert any("Jump to a day" in e.label for e in at.expander)


def test_gym_log(store):
    sid = store.save_gym_session("2026-11-05", "Push day", [
        {"exercise": "Bench press", "weight_kg": 60, "sets": 3, "reps": 8},
        {"exercise": "  ", "weight_kg": 10},                           # blank rows are skipped
        {"exercise": "Dips", "weight_kg": None, "sets": 3, "reps": 12},
    ])
    s = store.gym_sessions()[0]
    assert s["id"] == sid and s["title"] == "Push day"
    assert s["exercises"] == [{"exercise": "Bench press", "sets": 3, "reps": 8, "weight_kg": 60.0},
                              {"exercise": "Dips", "sets": 3, "reps": 12, "weight_kg": None}]
    store.save_gym_session("2026-11-08", "Push day", [{"exercise": "bench press", "weight_kg": 62.5, "sets": 3, "reps": 8}])
    assert store.last_lift("Bench Press")[2:] == (62.5, "2026-11-08")
    store.save_gym_session("2026-11-05", "Push", [{"exercise": "Bench press", "weight_kg": 65, "sets": 3, "reps": 5}],
                           session_id=sid)                             # edited in place
    assert len(store.gym_sessions()) == 2
    store.delete_gym_session(sid)
    assert [x["date"] for x in store.gym_sessions()] == ["2026-11-08"]


def test_gym_tool_ticks_strength_session(store, monkeypatch):
    from venato import tools, training
    tools = importlib.reload(tools)
    monkeypatch.setattr(store, "local_today", lambda: date(2026, 11, 4))
    first, race, sessions = training.generate(date(2026, 11, 2))
    store.create_plan(training.PLAN_NAME, first.isoformat(), race.isoformat(), sessions)
    strength = next(s for s in store.plan_sessions(store.active_plan()["id"]) if s["kind"] == "strength")
    r = tools.log_gym_session(strength["date"], "Legs", [{"exercise": "Squat", "weight_kg": 80, "sets": 5, "reps": 5}])
    assert "Squat 80 kg 5×5" in r.text and "Ticked off" in r.text
    assert store.get_session(strength["id"])["done"]
    assert "80 kg, 5×5" in tools.last_lift("squat").text


def test_ticked_training_shows_on_its_block(store, monkeypatch):
    from venato import autoplan, training
    monkeypatch.setattr(store, "local_today", lambda: date(2026, 11, 4))
    first, race, sessions = training.generate(date(2026, 11, 5))
    store.create_plan(training.PLAN_NAME, first.isoformat(), race.isoformat(), sessions)
    autoplan.schedule_training()
    s = store.plan_sessions(store.active_plan()["id"])[0]
    store.update_session(s["id"], done=True)
    assert store.session_block(s)["label"] == "✓ " + s["title"]
    store.update_session(s["id"], done=False)
    assert store.session_block(s)["label"] == s["title"]
