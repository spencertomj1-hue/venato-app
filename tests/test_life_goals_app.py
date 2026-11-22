"""The Goals page with long-term goals (AppTest): cards, targets and to-dos under them, New goal, edit."""

from pathlib import Path

from streamlit.testing.v1 import AppTest
from nav_helpers import goto

APP = str(Path(__file__).resolve().parents[1] / "app.py")


def goals_page():
    at = AppTest.from_file(APP, default_timeout=60).run()
    goto(at, "Goals")
    assert not at.exception, at.exception
    return at


def text(at):
    return " ".join([m.value for m in at.markdown] + [c.value for c in at.caption] + [s.value for s in at.subheader])


def test_card_shows_targets_todos_and_progress(store):
    today = store.local_today()
    g = store.add_life_goal("Get fit", months=6, why="Feel strong")
    t = store.add_goal("Gym", None, today, 10, "sessions", due=store.months_on(today, 2), life_goal_id=g["id"])
    store.set_goal_progress(t["id"], 5)
    loose = store.add_goal("Read", None, today, 12, "books", due=store.months_on(today, 3))
    todo = store.add_detailed_todo("Buy trainers", group_id=store.life_goal_group(g["id"])["id"])
    at = goals_page()
    words = text(at)
    assert "Get fit" in words and "Feel strong" in words and "50%" in words
    assert "0 of 1 target hit · 0 of 1 to-do done" in words
    assert "Targets not under a goal" in words                                # the loose one, under its own heading
    assert at.container(key=f"goal_card_{t['id']}") and at.container(key=f"goal_card_{loose['id']}")
    at.checkbox(key=f"life_todo_{todo['id']}").check().run()                  # ticking it on the card
    assert store.get_todo(todo["id"])["done"]


def test_add_a_todo_to_a_goal(store):
    g = store.add_life_goal("Grad job", months=12)
    at = goals_page()
    at.text_input(key=f"life_{g['id']}_newtodo").input("Update CV").run()
    at.button(key=f"life_{g['id']}_newtodo_add").click().run()
    assert [t["title"] for t in store.life_goal_todos(g["id"])] == ["Update CV"]


def test_new_goal_form(store):
    at = goals_page()
    assert "No goals yet" in text(at)
    at.text_input(key="new_life_title").input("Learn Spanish").run()
    at.segmented_control(key="new_life_horizon").set_value("3 months").run()
    at.button(key="new_life_add").click().run()
    g = store.life_goals()[0]
    assert g["title"] == "Learn Spanish" and store.horizon_of(g) == 3


def test_add_target_under_a_goal(store):
    g = store.add_life_goal("Get fit", months=6)
    at = goals_page()
    key = f"new_goal_{g['id']}"
    at.text_input(key=f"{key}_title").input("Run").run()
    assert at.selectbox(key=f"{key}_life").value == g["id"]                  # the card's goal, picked already
    at.button(key=f"{key}_add").click().run()
    assert [t["title"] for t in store.life_goal_targets(g["id"])] == ["Run"]


def test_archive_and_delete(store):
    g = store.add_life_goal("Get fit", months=6)
    t = store.add_goal("Gym", None, None, 10, due=store.months_on(store.local_today(), 2), life_goal_id=g["id"])
    at = goals_page()
    at.button(key=f"life_{g['id']}_archive").click().run()
    assert store.get_life_goal(g["id"])["archived"]
    assert "Past goals (1)" in [e.label for e in at.expander]
    at.button(key=f"life_{g['id']}_delete").click().run()
    assert store.get_life_goal(g["id"]) is None and store.get_goal(t["id"])["life_goal_id"] is None
