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


def test_home_tile_shows_goals_and_their_next_target(store):
    today = store.local_today()
    g = store.add_life_goal("Get fit", months=6)
    store.add_goal("Gym", None, today, 40, "sessions", due=store.months_on(today, 2), life_goal_id=g["id"])
    at = AppTest.from_file(APP, default_timeout=60).run()
    assert not at.exception, at.exception
    html = " ".join(h.proto.body for h in at.get("html"))
    assert 'class="gw-line gw-wide"' in html and "Get fit" in html and "Next: Gym · 0 / 40 sessions by" in html


def test_home_tile_without_goals_shows_targets(store):
    store.add_goal("Read", None, store.local_today(), 12, "books", due=store.months_on(store.local_today(), 2))
    at = AppTest.from_file(APP, default_timeout=60).run()
    html = " ".join(h.proto.body for h in at.get("html"))
    assert 'class="gw-line' not in html and '<span class="hg-name">Read</span>' in html


def test_todo_categories_under_goals_come_first(store):
    from venato.ui import todos
    store.add_todo_group("Chores")
    g = store.add_life_goal("Get fit", months=6)
    t = store.add_goal("Gym", None, None, 10, due=store.months_on(store.local_today(), 2), life_goal_id=g["id"])
    groups = list(todos._groups().values())
    assert [x["name"] for x in groups][-1] == "Chores"
    gym = next(x for x in groups if x["goal_id"] == t["id"])
    assert todos.group_name(gym) == "Gym · Get fit"


def _home_goals_tile(size):
    def draw(size):
        from venato.ui import goals
        goals.render_home(size)
    at = AppTest.from_function(draw, args=(size,), default_timeout=60).run()
    assert not at.exception, at.exception
    return at, " ".join(h.proto.body for h in at.get("html"))


def test_home_tile_at_every_size(store):
    today = store.local_today()
    g = store.add_life_goal("Get fit", months=6)
    store.add_goal("Gym", None, today, 40, "sessions", due=store.months_on(today, 2), life_goal_id=g["id"])
    todo = store.add_detailed_todo("Book a class", group_id=store.life_goal_group(g["id"])["id"])
    colour = store.life_goal_colour(g["id"])
    for size in ("small", "wide", "tall", "large", "column"):
        at, html = _home_goals_tile(size)
        assert "Get fit" in html and f"background:{colour}" in html, size     # the goal in its colour
        assert ("Next: Gym" in html) == (size in ("wide", "tall", "column")), size   # small: no room; large: chips
        assert ('class="gw-chip"' in html) == (size == "large"), size
    at, _ = _home_goals_tile("column")
    at.checkbox(key=f"home_goal_todo_{todo['id']}").check().run()              # tick a goal's to-do from Home
    assert store.get_todo(todo["id"])["done"]


def test_home_tile_keeps_the_goals_behind_when_trimming(store):
    from datetime import timedelta
    today = store.local_today()
    for i in range(5):
        store.add_life_goal(f"Goal {i}", start=today - timedelta(days=30), end=today + timedelta(days=30))
    g = store.life_goals(today)[4]
    t = store.add_goal("Late one", None, today - timedelta(days=30), 10, due=today + timedelta(days=30),
                       life_goal_id=g["id"])
    for x in store.life_goals(today)[:4]:                                      # the others are done
        store.add_detailed_todo("x", group_id=store.life_goal_group(x["id"])["id"])
        store.set_todo_done(store.life_goal_todos(x["id"])[0]["id"], True)
    _, html = _home_goals_tile("small")
    assert "Goal 4" in html and "+1 more" in html and t["title"] not in html


def test_todo_rows_get_their_goals_colour(store):
    from venato.ui import todos
    today = store.local_today()
    g = store.add_life_goal("Get fit", months=6)
    t = store.add_goal("Gym", None, None, 10, due=store.months_on(today, 2), life_goal_id=g["id"])
    gym = store.add_todo_group("Gym")
    store.update_todo_group(gym["id"], colour="#123456")
    with store.db() as conn:                                                    # the target's own category
        conn.execute("UPDATE todo_groups SET goal_id = ? WHERE id = ?", (t["id"], gym["id"]))
    loose = store.add_todo_group("Chores")
    rows = [store.add_detailed_todo(n, group_id=gid) for n, gid in
            (("Own", store.life_goal_group(g["id"])["id"]), ("Target's", gym["id"]), ("Loose", loose["id"]))]
    metas = [m["meta"] for m in todos._with_meta(rows, today, todos._groups())]
    colour = store.life_goal_colour(g["id"])
    assert metas[0]["goal"] == {"name": "Get fit", "colour": colour}
    assert metas[1]["goal"] == {"name": "Get fit", "colour": colour}             # a target's to-do: the goal's colour
    assert metas[2]["goal"] is None


def test_target_todos_sit_on_the_target_row_and_offer_plus_one(store):
    today = store.local_today()
    g = store.add_life_goal("Venato", months=6)
    t = store.add_goal("Users", None, today, 50, "users", due=store.months_on(today, 1), life_goal_id=g["id"])
    own = store.add_detailed_todo("Write the README", group_id=store.ensure_life_goal_group(g["id"]))
    at = goals_page()
    at.text_input(key=f"target_{t['id']}_newtodo").input("Post on Reddit").run()
    at.button(key=f"target_{t['id']}_newtodo_add").click().run()
    todo = store.target_todos(t["id"])[0]
    assert todo["title"] == "Post on Reddit"
    assert {x["title"] for x in store.life_goal_todos(g["id"])} == {"Write the README", "Post on Reddit"}
    keys = [c.key for c in at.checkbox]
    assert f"target_todo_{todo['id']}" in keys and f"life_todo_{todo['id']}" not in keys   # on the row, not the goal
    assert f"life_todo_{own['id']}" in keys
    at.checkbox(key=f"target_todo_{todo['id']}").check().run()
    assert store.get_todo(todo["id"])["done"]
    at.button(key=f"plus_offer_yes_{t['id']}").click().run()
    assert store.get_goal(t["id"])["value"] == 1


def test_goal_header_shows_next_step_and_pace(store):
    from datetime import timedelta
    today = store.local_today()
    g = store.add_life_goal("Venato", months=6)
    store.update_life_goal(g["id"], start=today - timedelta(days=30), months=6)
    t = store.add_goal("Users", None, today - timedelta(days=30), 50, "users", due=today + timedelta(days=6),
                       life_goal_id=g["id"])
    store.add_detailed_todo("Post on Reddit", group_id=store.ensure_target_group(t["id"]))
    words = text(goals_page())
    assert "Next: **Users** · 6 days left · Post on Reddit" in words
    assert "should be" in words and "by today" in words


def test_add_a_milestone_target(store):
    g = store.add_life_goal("Venato", months=6)
    at = goals_page()
    key = f"new_goal_{g['id']}"
    at.segmented_control(key=f"{key}_kind").set_value("Milestone").run()
    keys = [x.key for x in at.number_input]
    assert f"{key}_target" not in keys and f"{key}_unit" not in [x.key for x in at.text_input]   # no amount or unit
    at.text_input(key=f"{key}_title").input("Launch on the App Store").run()
    at.button(key=f"{key}_add").click().run()
    m = store.life_goal_targets(g["id"])[0]
    assert m["title"] == "Launch on the App Store" and m["milestone"] and m["target"] == 1


def test_milestone_row_shows_steps_and_a_tick(store):
    today = store.local_today()
    g = store.add_life_goal("Venato", months=6)
    m = store.add_goal("Launch", None, today, None, due=store.months_on(today, 2), life_goal_id=g["id"],
                       milestone=True)
    bare = store.add_goal("Pick a name", None, today, None, due=store.months_on(today, 1), life_goal_id=g["id"],
                          milestone=True)
    grp = store.ensure_target_group(m["id"])
    todos = [store.add_detailed_todo(x, group_id=grp) for x in ("Build", "Test", "Screens", "Licence", "Submit")]
    for t in todos[:3]:
        store.set_todo_done(t["id"], True)
    at = goals_page()
    assert "3 of 5 steps · 60%" in " ".join(h.body for h in at.get("html"))
    assert not [b for b in at.button if b.key in (f"plus_{m['id']}", f"minus_{m['id']}")]    # no − / +
    assert at.checkbox(key=f"milestone_{m['id']}_False").disabled                           # its to-dos decide
    at.checkbox(key=f"milestone_{bare['id']}_False").check().run()                          # no to-dos: a tick
    assert store.target_progress(store.get_goal(bare["id"])) == 1
    at.checkbox(key=f"target_todo_{todos[3]['id']}").check().run()                          # no "+1?" offer
    assert not [b for b in at.button if b.key == f"plus_offer_yes_{m['id']}"]


def test_rate_a_milestone_yourself(store):
    today = store.local_today()
    g = store.add_life_goal("Venato", months=6)
    m = store.add_goal("Get good at Swift", None, today, None, due=store.months_on(today, 2), life_goal_id=g["id"],
                       milestone=True)
    at = goals_page()
    key = f"edit_{m['id']}"
    assert at.segmented_control(key=f"{key}_kind").value == "Milestone"
    at.toggle(key=f"{key}_rate").set_value(True).run()
    at.slider(key=f"{key}_rating").set_value(40).run()
    at.button(key=f"{key}_save").click().run()
    m = store.get_goal(m["id"])
    assert m["self_rated"] and abs(store.target_progress(m) - 0.4) < 1e-9
    assert "Self-rated · 40%" in " ".join(h.body for h in at.get("html"))
