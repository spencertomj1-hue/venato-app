"""
Home's to-do cards and goal bars, and the Goals page (AppTest), plus the ops
the to-do list component sends. Uses the throwaway data folder from the `store` fixture.
"""

from pathlib import Path

from streamlit.testing.v1 import AppTest
from nav_helpers import goto, page_names

APP = str(Path(__file__).resolve().parents[1] / "app.py")


def app():
    return AppTest.from_file(APP, default_timeout=60).run()


def open_page(at, name):
    goto(at, name)
    assert not at.exception, at.exception


def test_home_shows_todos_and_goals_tiles(store):
    """The default Home: a To-dos tile and a Goals tile, each opening its own page."""
    today = store.local_today()
    for i in range(9):                                       # more than a list shows at first
        store.add_todo(f"Task {i}", "daily", today)
    store.add_goal("Gym", "monthly", today, 12, "sessions")
    at = app()
    assert not at.exception
    assert at.session_state["page"] == "Home"
    keys = home_keys(at)
    assert "home_todos_card" in keys and "home_todos" in keys
    assert {"hw_todos", "hw_goals", "go_tile_todos", "go_tile_goals"} <= keys


def home_keys(at):
    """The keys of everything drawn on the page (blocks, widgets and components)."""
    keys, todo = set(), [at.main]
    while todo:
        node = todo.pop()
        keys.add(getattr(node, "key", None))
        todo += list(getattr(node, "children", {}).values())
    return keys - {None}


def test_home_widgets_with_nothing_say_so(store):
    """Widgets you add to Home show a short empty state when there's nothing in them yet (and none are on
    Home until added). Once there's something, it shows."""
    store.save_settings(blocks=["timetable", "goals", "log", "stats", "focus", "grades"])
    at = app()
    assert not at.exception
    shown = [m.value for m in at.markdown]
    for title in ("**Habits**", "**Focus**", "**Grades**", "**Deadlines**", "**Goals**", "**Journal**"):
        assert title not in shown, title                          # hidden until added
    assert "home_todos_card" in home_keys(at)
    store.save_settings(home=[{"w": k, "size": "s"} for k in ("habits", "focus", "modules", "deadlines", "goals",
                                                               "journal")])
    at.run()
    assert not at.exception
    captions = " ".join(c.value for c in at.caption)
    for empty in ("No habits yet", "No marks yet", "Nothing due", "No goals running", "Nothing yet today"):
        assert empty in captions, empty
    assert at.button(key="home_focus_go")                         # Focus: start one from Home
    store.add_habit("Gym")
    store.add_deadline("Essay", store.local_today())
    at.run()
    assert "No habits yet" not in " ".join(c.value for c in at.caption)
    assert any("Essay" in m.value for m in at.markdown)


def test_see_all_opens_goals_page(store):
    store.add_deadline("Essay", store.local_today())
    store.save_settings(home=[{"w": "deadlines", "size": "s"}])
    at = app()
    at.button(key="home_deadlines_all").click().run()
    assert not at.exception
    assert at.header[0].value == "Goals"


def test_goals_page_plus_minus_and_past_goals(store):
    today = store.local_today()
    g = store.add_goal("Read", "monthly", today, 4, "books")
    store.add_habit("Gym")
    store.add_goal("Gym", "yearly", today, 100, habit_id=store.find_habit("gym")[0])
    at = app()
    open_page(at, "Goals")
    at.button(key=f"plus_{g['id']}").click().run()
    at.button(key=f"plus_{g['id']}").click().run()
    at.button(key=f"minus_{g['id']}").click().run()
    assert store.get_goal(g["id"])["value"] == 1
    assert not [b for b in at.button if b.key and b.key.startswith("plus_") and b.key != f"plus_{g['id']}"]
    assert "Past goals" not in [e.label.split(" (")[0] for e in at.expander]
    from datetime import timedelta
    store.add_goal("Old", None, today - timedelta(days=40), 3, due=today - timedelta(days=10))
    at.run()
    assert any(e.label.startswith("Past goals (0/1") for e in at.expander)       # a past deadline: folded away


def test_deadline_marks_and_default(store):
    from datetime import date
    from venato.ui import goals
    today = date(2026, 11, 17)
    assert [(d.isoformat(), t) for d, t in goals.handy_deadlines(today)] == [
        ("2026-11-30", "End of the month"), ("2026-12-01", "2 weeks from now"), ("2026-12-17", "A month from now"),
        ("2026-12-31", "End of the year"), ("2027-11-17", "A year from now")]
    assert goals.default_due(today) == date(2026, 11, 30)
    assert goals.default_due(date(2026, 11, 27)) == date(2026, 12, 27)         # its last week: a month on
    assert goals._months_on(date(2027, 1, 31), 1) == date(2027, 2, 28)


def test_settings_has_todo_and_goal_exports(store):
    at = app()
    open_page(at, "Settings")
    headings = [h.value for h in at.subheader]
    assert "To-dos" in headings and "Goals" in headings


def test_todo_component_ops(store):
    from venato.ui import todos
    week = "2026-10-26"
    add = lambda tid, title: todos.apply_op(
        {"kind": "add", "goal": {"id": tid, "title": title, "period": "weekly", "period_start": week}})
    add("t1", "Run")
    add("t1", "Run")                                         # a resent op adds nothing
    add("t2", "Swim")
    todos.apply_op({"kind": "reorder", "ids": ["t2", "t1"]})
    todos.apply_op({"kind": "edit", "id": "t1", "title": "Run 5k"})
    todos.apply_op({"kind": "edit", "id": "t1", "notes": "Park"})
    todos.apply_op({"kind": "edit", "id": "t1", "title": "  "})          # blank titles are ignored
    todos.apply_op({"kind": "repeat", "id": "t1", "repeat": True})
    todos.apply_op({"kind": "toggle", "id": "t2", "done": True})
    assert [(t["id"], t["title"], t["notes"], t["done"], t["repeat"]) for t in store.todos_for("weekly", week)] == [
        ("t2", "Swim", None, True, False), ("t1", "Run 5k", "Park", False, True)]
    todos.apply_op({"kind": "move", "id": "t1", "period": "monthly"})
    assert store.get_todo("t1")["period"] == "monthly"
    todos.apply_op({"kind": "delete", "id": "t2"})
    assert store.get_todo("t2") is None


def test_home_habits_tick_today(store):
    from datetime import date
    store.add_habit("Stretch")
    hid = store.find_habit("stretch")[0]
    store.save_settings(home=[{"w": "habits", "size": "m"}])
    at = app()
    key = f"home_habit_{hid}_{date.today().isoformat()}"
    at.checkbox(key=key).check().run()
    assert not at.exception
    assert date.today().isoformat() in store.get_habit_dates(hid)
    at.button(key="home_habits_manage").click().run()
    assert at.session_state["page"] == "Daily Log"


def test_deadlines_read_as_numbers(store):
    from datetime import date
    from venato import regional
    today = date(2026, 11, 17)
    assert regional.short_date(date(2026, 12, 31), today) == "31/12"
    assert regional.short_date(date(2027, 1, 4), today) == "04/01/27"
    assert store.goal_title_due("2027-01-04", today) == "by 04/01/27"
