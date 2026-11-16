"""Category rules and deleting, the daily tracking numbers, and editing the training plan."""

import importlib
from datetime import date, timedelta
from pathlib import Path

import pytest

APP = str(Path(__file__).resolve().parents[1] / "app.py")


@pytest.fixture
def tools(store):
    from venato import tools as tools_module
    return importlib.reload(tools_module)


@pytest.fixture
def plan(store, tools):
    from venato import training
    first, race, sessions = training.generate(date(2026, 11, 2))
    store.create_plan(training.PLAN_NAME, first.isoformat(), race.isoformat(), sessions)
    return store.active_plan()


def block(store, label, cat="study", id_="b1", day="2026-11-05"):
    store.upsert_blocks([{"id": id_, "date": day, "track": "plan", "start": "10:00", "end": "11:00",
                          "label": label, "category_id": cat, "details": None}])


# --- Rules ---

def test_rule_matches_whole_words_in_any_case(store):
    store.add_rule("run", "chores")
    assert store.rule_category("Morning RUN") == "chores"
    assert store.rule_category("Brunch") is None
    assert store.rule_category(None) is None


def test_longest_rule_wins_and_same_word_replaces(store):
    store.add_rule("gym", "chores")
    store.add_rule("gym class", "classes")
    assert store.rule_category("Gym class at 5") == "classes"
    store.add_rule("GYM", "social")
    assert store.rule_category("Gym") == "social"
    assert len(store.load_rules()) == 2


def test_rules_apply_to_new_events_and_outlook(store):
    store.add_rule("Lecture", "work")
    assert store.resolve_category(label="Maths lecture") == "work"
    assert store.resolve_category(label="Lecture") == "work"       # beats the built-in label default
    assert store.resolve_category(label="Lecture", category="study") == "study"   # asking for one still wins
    assert store.outlook_category("Physics Lecture") == "work"
    assert store.outlook_category("Physics Lecture", teams=True) == "work"
    assert store.outlook_category("Something else") == "classes"


def test_rule_can_change_existing_events(store):
    block(store, "Maths lecture", id_="b1")
    block(store, "Dentist", id_="b2", day="2026-11-06")
    assert store.add_rule("lecture", "work", apply_existing=True) == 1
    assert store.get_block("b1")["category_id"] == "work"
    assert store.get_block("b2")["category_id"] == "study"
    block(store, "Other lecture", id_="b3", day="2026-11-07")
    assert store.add_rule("other", "chores") == 0
    assert store.get_block("b3")["category_id"] == "study"


def test_rule_needs_a_word(store):
    with pytest.raises(ValueError):
        store.add_rule("  ", "work")


# --- Categories ---

def test_deleting_a_category_moves_its_events_and_rules(store):
    block(store, "Essay")
    store.add_rule("essay", "study")
    store.merge_categories("study", "work")
    assert store.get_block("b1")["category_id"] == "work"
    assert store.rule_category("Essay") == "work"
    assert "study" not in store.get_category_ids()


def test_deleted_builtin_category_stays_deleted(store):
    store.teams_category()
    store.todo_category()
    store.merge_categories("teams", "work")
    store.merge_categories("todos", "chores")
    assert store.teams_category() == "work"
    assert store.outlook_category("Standup", teams=True) == "work"
    assert store.todo_category() == "chores"
    store.merge_categories("work", "study")                       # follows a later delete too
    assert store.teams_category() == "study"
    assert "teams" not in store.get_category_ids()


def test_add_category(store):
    assert store.add_category(" Side projects! ", "#112233") == "side_projects"
    with pytest.raises(ValueError):
        store.add_category("side PROJECTS!", "#112233")
    with pytest.raises(ValueError):
        store.add_category("  ", "#112233")
    assert store.add_category("Side projects?", "#112233") == "side_projects_2"


# --- Day trackers: the user's own numbers ---

def test_day_trackers_are_the_users_own(store):
    assert store.day_trackers() == []                                 # nothing until the user makes some
    coffee = store.add_day_tracker("Coffee", "cups", 1)
    reading = store.add_day_tracker("Reading", "hours", 0.5)
    with pytest.raises(ValueError):
        store.add_day_tracker("coffee")                              # taken (any case)
    store.save_journal("2026-11-05", "Dear diary")
    store.set_day_value("2026-11-05", coffee["id"], 0)               # 0 is logged, unlike blank
    store.set_day_value("2026-11-05", reading["id"], 1.5)
    assert store.day_values("2026-11-05") == {coffee["id"]: 0, reading["id"]: 1.5}
    assert store.get_entry("2026-11-05")["notes"] == "Dear diary"   # the journal is untouched
    store.update_day_tracker(reading["id"], name="Books", unit="h")
    assert store.find_day_tracker("books")["unit"] == "h"
    store.delete_day_tracker(coffee["id"])
    assert store.day_values("2026-11-05") == {reading["id"]: 1.5}


def test_stats_page_with_only_trackers_logged(store):
    """A day with no sleep logged used to crash Stats (NaN)."""
    from streamlit.testing.v1 import AppTest
    t = store.add_day_tracker("Coffee", "cups")
    store.set_day_value(store.local_today().isoformat(), t["id"], 4)
    at = AppTest.from_file(APP, default_timeout=120)
    at.run()
    at.sidebar.radio[0].set_value("Stats").run()
    assert not at.exception
    assert ("Coffee (30 days)", "4 cups") in [(m.label, m.value) for m in at.metric]


# --- Training plan ---

def test_moving_a_session_moves_it_to_that_week(store, plan):
    s = store.plan_sessions(plan["id"])[0]
    store.update_session(s["id"], date="2026-11-18")
    assert store.get_session(s["id"])["week"] == 3
    assert store.plan_week("2026-11-04", "2026-11-01") == 1          # never before week 1


def test_add_and_delete_session(store, tools, plan):
    new = store.add_session(plan["id"], "2026-11-10", "easy", "Extra run", 4)
    session = store.get_session(new)
    assert session["week"] == 2 and session["distance_km"] == 4
    tools.place_session(session)
    block_id = store.get_session(new)["block_id"]
    assert store.get_block(block_id)
    store.delete_session(new)
    assert store.get_session(new) is None and store.get_block(block_id) is None


def _rows(sessions):
    from venato.ui import training_ui
    return [{"id": s["id"], "date": date.fromisoformat(s["date"]), "title": s["title"], "details": s["details"],
             "kind": training_ui.KIND_NAMES[s["kind"]], "distance_km": s["distance_km"]} for s in sessions]


def test_plan_table_changes_adds_and_removes(store, tools, plan):
    from venato.ui import training_ui
    importlib.reload(training_ui)
    tools.put_plan_on_timetable()
    sessions = store.plan_sessions(plan["id"])
    a, b = sessions[0], sessions[1]
    start = store.get_block(a["block_id"])["start"]
    rows = _rows(sessions)
    rows[0].update(date=date.fromisoformat(a["date"]) + timedelta(days=1), distance_km=10.0)
    del rows[1]
    rows.append({"id": None, "date": date(2026, 11, 7), "title": "Parkrun", "kind": "Race pace",
                 "distance_km": 5.0, "details": float("nan")})
    assert training_ui.save_plan_edits(plan, sessions, rows) == 3

    moved = store.get_session(a["id"])
    assert moved["distance_km"] == 10 and moved["date"] != a["date"]
    placed = store.get_block(moved["block_id"])
    assert placed["date"] == moved["date"] and placed["start"] == start
    assert store.slot_of(placed["end"]) - store.slot_of(placed["start"]) == 6          # 80 min, up to the quarter hour
    assert store.get_session(b["id"]) is None
    new = [s for s in store.plan_sessions(plan["id"]) if s["title"] == "Parkrun"][0]
    assert new["kind"] == "race_pace" and new["details"] is None and new["block_id"]
    assert training_ui.save_plan_edits(plan, store.plan_sessions(plan["id"]),
                                       _rows(store.plan_sessions(plan["id"]))) == 0


def test_plan_table_needs_a_day_and_name(store, tools, plan):
    from venato.ui import training_ui
    importlib.reload(training_ui)
    sessions = store.plan_sessions(plan["id"])
    rows = _rows(sessions)
    rows[0]["title"] = " "
    with pytest.raises(ValueError):
        training_ui.save_plan_edits(plan, sessions, rows)
    assert store.get_session(sessions[0]["id"])["title"] == sessions[0]["title"]


def _session_page():
    from venato.ui import training_ui
    training_ui.render_page()


def _widget(widgets, sid, end):
    return next(w for w in widgets if w.key.startswith(f"tr_{sid}_") and w.key.endswith(end))


def test_logging_a_distance_ticks_the_session_and_shows_it(store, tools, plan):
    from streamlit.testing.v1 import AppTest
    s = store.plan_sessions(plan["id"])[0]
    at = AppTest.from_function(_session_page)
    at.run(timeout=120)
    _widget(at.number_input, s["id"], "_km").set_value(7.0)
    _widget(at.button, s["id"], "_save").click()
    at.run(timeout=120)
    assert not at.exception
    saved = store.get_session(s["id"])
    assert saved["actual_km"] == 7 and saved["done"]
    assert any("ran 7 km" in c.label for c in at.checkbox)
    assert ("Distance run", "7 km") in [(m.label, m.value) for m in at.metric]


def test_saving_without_logging_leaves_the_run_unlogged(store, tools, plan):
    from streamlit.testing.v1 import AppTest
    s = store.plan_sessions(plan["id"])[0]
    at = AppTest.from_function(_session_page)
    at.run(timeout=120)
    _widget(at.number_input, s["id"], "_plan").set_value(9.0)
    _widget(at.button, s["id"], "_save").click()
    at.run(timeout=120)
    assert not at.exception
    saved = store.get_session(s["id"])
    assert saved["distance_km"] == 9 and saved["actual_km"] is None and not saved["done"]


def test_timetable_page_has_the_category_editor(store):
    from streamlit.testing.v1 import AppTest

    def page():
        from venato.ui import timetable
        timetable.render_page()
    store.add_rule("gym", "chores")
    at = AppTest.from_function(page)
    at.run(timeout=120)
    assert not at.exception
    assert "Categories and rules" in [e.label for e in at.expander]
    name = next(t for t in at.text_input if t.key == "cat_name_chores")
    name.set_value("Housework").run(timeout=120)
    assert not at.exception
    assert store.load_categories().set_index("id").loc["chores", "name"] == "Housework"


def test_plan_table_appears_behind_its_switch(store, tools, plan):
    from streamlit.testing.v1 import AppTest
    at = AppTest.from_function(_session_page)
    at.run(timeout=120)
    assert "Save plan changes" not in [b.label for b in at.button]
    at.toggle(key="tr_plan_edit").set_value(True).run(timeout=120)
    assert not at.exception
    assert "Save plan changes" in [b.label for b in at.button]


# --- Marking past events done / not done ---

def _todo_slot(store):
    from datetime import datetime
    from venato import autoplan
    wed = date(2026, 11, 4)
    todo = store.add_todo("Buy monitors", "daily", wed)
    autoplan.schedule_todos(wed, datetime(2026, 11, 4, 14, 10))
    return todo, store.TODO_BLOCK + todo["id"], wed


def test_todo_marked_done_stays_green_and_ticks_it(store):
    from datetime import datetime
    from venato import autoplan
    todo, block_id, wed = _todo_slot(store)
    start = store.get_block(block_id)["start"]
    store.mark_event(block_id, True)
    assert store.get_todo(todo["id"])["done"]
    assert store.get_block(block_id) is None
    past = [b for b in store.blocks_between("2026-11-04", "2026-11-04") if b["id"].startswith(store.TODO_PAST)]
    assert len(past) == 1 and past[0]["start"] == start
    assert store.event_statuses()[past[0]["id"]] is True
    autoplan.schedule_todos(wed, datetime(2026, 11, 4, 18, 0))
    assert store.get_block(block_id) is None                        # not put back


def test_todo_marked_not_done_stays_black_and_gets_a_new_slot(store):
    from datetime import datetime
    from venato import autoplan
    todo, block_id, wed = _todo_slot(store)
    old = store.get_block(block_id)
    store.mark_event(block_id, False)
    assert not store.get_todo(todo["id"])["done"]
    past_id = next(b["id"] for b in store.blocks_between("2026-11-04", "2026-11-04")
                   if b["id"].startswith(store.TODO_PAST))
    assert store.event_statuses()[past_id] is False
    autoplan.schedule_todos(wed, datetime(2026, 11, 4, 18, 0))
    new = store.get_block(block_id)
    assert new and new["start"] > old["start"]

    store.mark_event(past_id, True)                                 # changed my mind
    assert store.get_todo(todo["id"])["done"] and store.get_block(block_id) is None
    store.mark_event(past_id, False)
    assert not store.get_todo(todo["id"])["done"]


def test_training_marked_done_and_not_done(store, tools, plan):
    tools.put_plan_on_timetable()
    s = store.plan_sessions(plan["id"])[0]
    store.mark_event(s["block_id"], True)
    assert store.get_session(s["id"])["done"]
    assert store.event_statuses()[s["block_id"]] is True
    store.mark_event(s["block_id"], False)
    assert not store.get_session(s["id"])["done"]
    assert store.event_statuses()[s["block_id"]] is False
    store.update_session(s["id"], done=True)                        # ticked elsewhere wins: it goes green
    assert store.event_statuses()[s["block_id"]] is True


def test_training_page_says_missed(store, tools, plan):
    from streamlit.testing.v1 import AppTest
    tools.put_plan_on_timetable()
    s = store.plan_sessions(plan["id"])[0]
    store.mark_event(s["block_id"], False)
    at = AppTest.from_function(_session_page)
    at.run(timeout=120)
    assert not at.exception
    assert any("missed" in c.label for c in at.checkbox)


def test_marking_other_events(store):
    block(store, "Dentist")
    store.mark_event("b1", True)
    store.mark_event("ol:abc", False)
    assert store.event_statuses() == {"b1": True, "ol:abc": False}
    store.mark_event("b1", None)
    assert store.event_statuses() == {"ol:abc": False}


def test_grid_op_saves_status_and_moving_a_block_clears_it(store):
    from venato.ui import timetable
    block(store, "Dentist")
    timetable.apply_grid_op({"kind": "status", "id": "b1", "done": True})
    assert store.event_statuses()["b1"] is True
    store.clear_event_status("b1")
    assert "b1" not in store.event_statuses()
