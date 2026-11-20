"""
Busy widgets are st.fragments: an interaction reruns just that widget, and the whole app only when
something drawn outside it shows what changed (kit.rerun_app_if). Interactions are run the way the
browser runs them (tests/fragment_run.py), so a fragment-only rerun really leaves Home alone.
"""

from pathlib import Path

from streamlit.testing.v1 import AppTest

import fragment_run

APP = str(Path(__file__).resolve().parents[1] / "app.py")


def app():
    return AppTest.from_file(APP, default_timeout=60).run()


def test_todo_tick_reruns_fragment_only(store):
    store.add_todo("Run", "daily", store.local_today(), todo_id="t1")
    with fragment_run.recording():
        at = app()
        draws = at.session_state["home_draws"]
        fragment_run.trigger(at, "home_todos", "ops", [{"opId": "o1", "kind": "toggle", "id": "t1", "done": True}])
    assert not at.exception
    assert store.get_todo("t1")["done"]
    assert "o1" in at.session_state["todo_acked"]
    assert at.session_state["home_draws"] == draws                  # Home itself wasn't redrawn


def test_todo_delete_reruns_app_for_the_undo_bar(store):
    store.add_todo("Run", "daily", store.local_today(), todo_id="t1")
    with fragment_run.recording():
        at = app()
        draws = at.session_state["home_draws"]
        fragment_run.trigger(at, "home_todos", "ops", [{"opId": "o1", "kind": "delete", "id": "t1"}])
    assert store.get_todo("t1") is None
    assert at.session_state["home_draws"] == draws + 1              # the Undo bar is drawn outside the to-dos
    assert at.button(key="undo_btn")


def test_unlinked_habit_reruns_fragment_only(store):
    store.add_habit("Stretch")
    hid = store.find_habit("stretch")[0]
    with fragment_run.recording():
        at = app()
        draws = at.session_state["home_draws"]
        fragment_run.click(at, at.checkbox(key=f"home_habit_{hid}_{store.local_today()}").check())
    assert not at.exception
    assert store.local_today().isoformat() in store.get_habit_dates(hid)
    assert at.session_state["home_draws"] == draws


def test_rerun_app_if(store, monkeypatch):
    from venato.ui import kit
    store.add_habit("Gym")
    store.add_habit("Read")
    gym, read = store.find_habit("gym")[0], store.find_habit("read")[0]
    store.add_goal("Gym", "monthly", store.local_today(), 12, habit_id=gym)
    assert kit.app_depends_on({f"habit:{gym}"})
    assert not kit.app_depends_on({f"habit:{read}"})
    assert not kit.app_depends_on({"todo:x"}) and not kit.app_depends_on(set())
    assert kit.app_depends_on({"actual"}) and kit.app_depends_on({"undo"}) and kit.app_depends_on({"todo:x", "undo"})
    reruns = []
    monkeypatch.setattr(kit.st, "rerun", lambda scope="app": reruns.append(scope))
    kit.rerun_app_if({f"habit:{read}"})
    kit.rerun_app_if({f"habit:{gym}"})
    assert reruns == ["app"]


def test_review_period_reruns_charts_only(store):
    with fragment_run.recording():
        at = AppTest.from_file(APP, default_timeout=60)
        at.session_state["page"] = "Review"
        at.session_state["rv_view"] = "Trends"
        at.run()
        assert not at.exception
        view = at.segmented_control(key="rv_view_w")
        fragment_run.click(at, at.radio(key="stats_period").set_value("Last 7 days"))
    assert not at.exception
    assert at.radio(key="stats_period").value == "Last 7 days"
    assert not [s for s in at.segmented_control if s.key == "rv_view_w"]   # the page's header wasn't redrawn
    assert view


def test_timetable_rejected_ops_are_acked_with_a_reason(store, monkeypatch):
    """The grid applies an edit at once and keeps it pending until Python acks it. An edit Python can't
    save is acked too, with a reason in `rejected`: the grid then drops it (the block goes back) and says why."""
    from datetime import timedelta
    yesterday = (store.local_today() - timedelta(days=1)).isoformat()
    store.paint(store.local_today().isoformat(), "actual", store.slot_of("09:00"), store.slot_of("10:00"),
                {"label": "Gym", "category_id": "exercise"}, new_id="b1")
    monkeypatch.setattr(store, "move_block", lambda *a, **k: (_ for _ in ()).throw(ValueError("disk full")))
    with fragment_run.recording():
        at = AppTest.from_file(APP, default_timeout=60)
        at.session_state["page"] = "Timetable"
        at.run()
        fragment_run.trigger(at, "timetable", "ops", [
            {"opId": "o1", "kind": "paint", "date": yesterday, "track": "plan", "start": "12:00", "end": "13:00",
             "block": {"label": "Lunch", "categoryId": "rest"}, "newId": "p1"},
            {"opId": "o2", "kind": "move", "id": "b1", "date": store.local_today().isoformat(), "track": "actual",
             "start": "11:00", "end": "12:00"},
            {"opId": "o3", "kind": "paint", "date": store.local_today().isoformat(), "track": "actual",
             "start": "14:00", "end": "15:00", "block": {"label": "Read", "categoryId": "rest"}, "newId": "p3"}])
    assert not at.exception
    grid = fragment_run.component_data(at, "timetable")
    assert {"o1", "o2", "o3"} <= set(grid["acked"])
    assert "locked" in grid["rejected"]["o1"]
    assert grid["rejected"]["o2"] == "Couldn't save that change. It's been put back." and "disk full" not in grid["rejected"]["o2"] and "o3" not in grid["rejected"]
    today = store.local_today().isoformat()
    assert [(b["start"], b["label"]) for b in store.blocks_between(today, today, "actual")] == [
        ("09:00", "Gym"), ("14:00", "Read")]                       # the move didn't save; the paint after it did
