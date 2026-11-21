"""
To-dos with a due day, a length and one of the user's own to-do categories: the store, the list's
row details, and the To-dos page's "By due date" view (AppTest). Uses the `store` fixture's data folder.
"""

from datetime import timedelta
from pathlib import Path

import pandas as pd
from streamlit.testing.v1 import AppTest
from nav_helpers import goto

APP = str(Path(__file__).resolve().parents[1] / "app.py")


def test_due_day_picks_the_list(store):
    today = store.local_today()
    week_end = store.end_of_period("weekly", store.start_of_period("weekly", today))
    assert store.list_for_due(today - timedelta(days=3), today)[0] == "daily"      # overdue: today's list
    assert store.list_for_due(today, today) == ("daily", today.isoformat())
    if week_end > today:
        assert store.list_for_due(week_end, today)[0] == "weekly"
    later = week_end + timedelta(days=40)
    assert store.list_for_due(later, today) == ("monthly", store.start_of_period("monthly", later).isoformat())


def test_detailed_todo_and_changing_its_details(store):
    today = store.local_today()
    home = store.add_todo_group("At home repairs")
    assert store.add_todo_group("at home repairs")["id"] == home["id"]          # same name: the same category
    t = store.add_detailed_todo("Fix the tap", due=today, group_id=home["id"], minutes=45)
    assert (t["period"], t["due"], t["group_id"], t["minutes"]) == ("daily", today.isoformat(), home["id"], 45)
    later = store.end_of_period("weekly", store.start_of_period("weekly", today)) + timedelta(days=40)
    store.update_todo(t["id"], due=later)                                         # moves to that month's list
    got = store.get_todo(t["id"])
    assert (got["period"], got["period_start"]) == ("monthly", store.start_of_period("monthly", later).isoformat())
    assert [x["id"] for x in store.open_todos(today)] == [t["id"]]                # still listed by due date
    store.update_todo(t["id"], due=None, minutes=None, group_id=None)
    got = store.get_todo(t["id"])
    assert (got["due"], got["minutes"], got["group_id"]) == (None, None, None)
    plain = store.add_todo("Plain", "weekly", today)                              # Tom's lists still work as before
    assert (plain["due"], plain["minutes"], plain["group_id"]) == (None, None, None)


def test_open_todos_most_urgent_first_and_done(store):
    today = store.local_today()
    soon = store.add_todo("Month thing", "monthly", today)
    urgent = store.add_detailed_todo("Overdue thing", due=today - timedelta(days=2))
    store.set_todo_done(store.add_todo("Ticked", "daily", today)["id"], True)
    order = [t["title"] for t in store.open_todos(today)]
    assert order[0] == "Overdue thing" and "Month thing" in order and "Ticked" not in order
    assert [t["title"] for t in store.done_todos(today)] == ["Ticked"]
    assert store.todo_due(soon) == store.end_of_period("monthly", today)
    assert store.todo_due(urgent) == today - timedelta(days=2)


def test_deleting_a_category_keeps_its_todos(store):
    today = store.local_today()
    g = store.add_todo_group("Uni")
    t = store.add_todo("Essay", "daily", today, group_id=g["id"])
    store.update_todo_group(g["id"], name="University", colour="#000000")
    assert store.todo_groups() == [{"id": g["id"], "name": "University", "colour": "#000000"}]
    store.delete_todo_group(g["id"])
    assert store.todo_groups() == [] and store.get_todo(t["id"])["group_id"] is None


def test_repeats_and_carry_over_keep_category_and_length(store):
    today = store.local_today()
    g = store.add_todo_group("Health")
    last_week = store.shift_period("weekly", store.start_of_period("weekly", today), -1)
    store.add_todo("Stretch", "weekly", last_week, repeat=True, group_id=g["id"], minutes=15)
    store.roll_todos(today)
    copy = next(t for t in store.todos_for("weekly", today) if t["title"] == "Stretch")
    assert (copy["group_id"], copy["minutes"]) == (g["id"], 15)
    store.add_todo("Call bank", "daily", today, group_id=g["id"], minutes=30)
    assert store.carry_over("daily", today) == 1
    moved = store.todos_for("daily", today + timedelta(days=1))[0]
    assert (moved["group_id"], moved["minutes"]) == (g["id"], 30)


def test_export_and_import_keep_the_details(store):
    today = store.local_today()
    g = store.add_todo_group("Admin")
    store.add_detailed_todo("Pay rent", due=today, group_id=g["id"], minutes=15)
    df = store.load_todos()
    assert {"due", "minutes", "group_id"} <= set(df.columns)
    assert store.save_todos(df, replace=True) == 1
    t = store.todos_for("daily", today)[0]
    assert (t["due"], t["minutes"], t["group_id"]) == (today.isoformat(), 15, g["id"])
    assert store.save_todos(pd.DataFrame([{"title": "Old export", "period": "daily"}])) == 1   # older exports too


def test_list_ops_details_opens_the_popup(store):
    from venato.ui import todos
    import streamlit as st
    todos.apply_op({"kind": "details", "id": "abc"})
    assert st.session_state["todo_details"] == "abc"


def test_rows_carry_their_details(store):
    from venato.ui import todos
    today = store.local_today()
    g = store.add_todo_group("Uni")
    store.add_detailed_todo("Essay", due=today - timedelta(days=1), group_id=g["id"], minutes=90)
    sec = todos._section("daily", today)
    assert sec["goals"][0]["meta"] == {"due": "Overdue (yesterday)", "late": True,
                                       "group": {"name": "Uni", "colour": g["colour"]}, "length": "1½ hours"}
    store.add_todo("Plain", "daily", today)
    plain = todos._section("daily", today)["goals"][1]["meta"]
    assert plain == {"due": None, "late": False, "group": None, "length": None}


def test_page_by_due_date_view(store):
    today = store.local_today()
    g = store.add_todo_group("At home repairs")
    store.add_detailed_todo("Fix the tap", due=today, group_id=g["id"], minutes=60)
    store.add_detailed_todo("Old bill", due=today - timedelta(days=3))
    at = AppTest.from_file(APP, default_timeout=60).run()
    goto(at, "To-dos")
    assert not at.exception, at.exception
    assert [b.label for b in at.button if b.key == "td_new"] == ["Add to-do"]
    at.segmented_control(key="todos_tab").set_value("By due date").run()
    assert not at.exception, at.exception
    heads = [m.value for m in at.markdown]
    assert any(h.startswith("**Overdue**") for h in heads) and any(h.startswith("**Today**") for h in heads)
    assert {c.label for c in at.checkbox} >= {"Fix the tap", "Old bill"}
    assert any("At home repairs" in c.value and "1 hour" in c.value for c in at.caption)
    at.button(key="td_new").click().run()                                  # the Add to-do pop-up opens
    assert not at.exception, at.exception
    assert any(t.key == "tdn_title" for t in at.text_input)
