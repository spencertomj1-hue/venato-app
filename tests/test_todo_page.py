"""To-dos block: due days, minutes, the user's own to-do categories, and the To-dos page."""

from datetime import timedelta
from pathlib import Path

from streamlit.testing.v1 import AppTest

APP = str(Path(__file__).resolve().parents[1] / "app.py")


def test_detailed_todos_and_categories(store):
    today = store.local_today()
    home = store.add_todo_group("At home repairs")
    assert store.add_todo_group("at home repairs")["id"] == home["id"]          # same name: the same one
    soon = store.add_detailed_todo("Fix the tap", due=today, group_id=home["id"], minutes=45)
    later = store.add_detailed_todo("Paint the shed", due=today + timedelta(days=30))
    assert (soon["period"], soon["minutes"], soon["group_id"]) == ("daily", 45, home["id"])
    assert later["period"] == "weekly" and store.todo_due(later) == today + timedelta(days=30)
    assert [t["title"] for t in store.all_open_todos(today)] == ["Fix the tap", "Paint the shed"]
    store.update_todo(later["id"], due=today, minutes=None)
    assert store.get_todo(later["id"])["period"] == "daily"                     # due now: today's list
    store.set_todo_done(soon["id"], True)
    assert [t["title"] for t in store.done_todos(today)] == ["Fix the tap"]
    store.update_todo_group(home["id"], "Home", "#000000")
    assert store.todo_groups() == [{"id": home["id"], "name": "Home", "colour": "#000000"}]
    store.delete_todo_group(home["id"])
    assert store.todo_groups() == [] and store.get_todo(soon["id"])["group_id"] is None


def test_unticked_todos_come_forward(store):
    today = store.local_today()
    old = store.add_todo("Call the bank", "daily", today - timedelta(days=3))
    store.add_todo("Done already", "daily", today - timedelta(days=3))
    store.set_todo_done(store.todos_for("daily", today - timedelta(days=3))[1]["id"], True)
    assert [t["title"] for t in store.all_open_todos(today)] == ["Call the bank"]
    assert store.get_todo(old["id"])["period_start"] == today.isoformat()


def test_todos_page(store):
    from venato import blocks
    blocks.save(blocks.chosen_keys() + ["todo_page"])
    g = store.add_todo_group("Coding")
    store.add_detailed_todo("Ship it", due=store.local_today(), group_id=g["id"], minutes=60)
    at = AppTest.from_file(APP, default_timeout=60).run()
    at.sidebar.radio[0].set_value("To-dos").run()
    assert not at.exception, at.exception
    assert any("Today" in m.value for m in at.markdown)
    assert [c.label for c in at.checkbox if c.label == "Ship it"] == ["Ship it"]
    at.button(key="td_new").click().run()
    assert not at.exception, at.exception
