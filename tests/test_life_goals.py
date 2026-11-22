"""Long-term goals (store/life_goals.py): 3 / 6 / 12 months, targets and to-dos under them, progress, CSV."""

from datetime import date

import pandas as pd


def test_add_by_months_and_by_end_date(store):
    g = store.add_life_goal("Get fit", months=6, start="2026-08-31", why="Feel better")
    assert (g["start"], g["end_date"], g["why"], g["archived"]) == ("2026-08-31", "2027-02-28", "Feel better", False)
    assert store.horizon_of(g) == 6
    h = store.add_life_goal("Grad job", end="2027-05-01", start="2026-11-22")
    assert store.horizon_of(h) is None
    assert [x["title"] for x in store.life_goals(date(2026, 11, 22))] == ["Get fit", "Grad job"]


def test_needs_title_and_end_after_start(store):
    for kwargs in ({"title": " ", "months": 3}, {"title": "X", "end": "2026-01-01", "start": "2026-01-01"},
                   {"title": "X"}):
        try:
            store.add_life_goal(**kwargs)
        except ValueError:
            continue
        raise AssertionError(kwargs)


def test_goal_is_a_todo_category_and_renames_it(store):
    g = store.add_life_goal("Get fit", months=3)
    grp = store.life_goal_group(g["id"])
    assert grp["name"] == "Get fit" and grp["life_goal_id"] == g["id"]
    store.update_life_goal(g["id"], title="Get strong")
    assert store.life_goal_group(g["id"])["name"] == "Get strong"


def test_targets_and_todos_under_a_goal(store):
    g = store.add_life_goal("Get fit", months=6, start="2026-11-01")
    t = store.add_goal("Gym", None, "2026-11-01", 40, "sessions", due="2027-03-31", life_goal_id=g["id"])
    loose = store.add_goal("Read", None, "2026-11-01", 10, due="2027-03-31")
    assert store.get_goal(t["id"])["life_goal_id"] == g["id"]
    assert [x["id"] for x in store.life_goal_targets(g["id"])] == [t["id"]]
    assert loose["id"] in [x["id"] for x in store.unparented_targets(date(2026, 11, 22))]

    # To-dos in the goal's own category and in its target's category both count.
    own = store.add_detailed_todo("Buy trainers", group_id=store.life_goal_group(g["id"])["id"])
    via = store.add_detailed_todo("Book induction", group_id=store.goal_todo_group(t["id"])["id"])
    store.add_detailed_todo("Unrelated")
    assert {x["id"] for x in store.life_goal_todos(g["id"])} == {own["id"], via["id"]}
    groups = store.group_life_goals()
    assert groups[store.life_goal_group(g["id"])["id"]] == g["id"]
    assert groups[store.goal_todo_group(t["id"])["id"]] == g["id"]


def test_progress_is_targets_mean_else_todos(store):
    g = store.add_life_goal("Get fit", months=6)
    assert store.life_goal_progress(g["id"])["fraction"] == 0
    grp = store.life_goal_group(g["id"])["id"]
    a = store.add_detailed_todo("A", group_id=grp)
    store.add_detailed_todo("B", group_id=grp)
    store.set_todo_done(a["id"], True)
    assert store.life_goal_progress(g["id"])["fraction"] == 0.5           # no targets: to-dos

    t1 = store.add_goal("Gym", None, None, 10, due="2027-01-31", life_goal_id=g["id"])
    t2 = store.add_goal("Run", None, None, 4, due="2027-01-31", life_goal_id=g["id"])
    store.set_goal_progress(t1["id"], 5)
    store.set_goal_progress(t2["id"], 8)                                  # over target: counts as 100%
    p = store.life_goal_progress(g["id"])
    assert p["fraction"] == 0.75 and (p["targets"], p["targets_done"], p["todos"], p["todos_done"]) == (2, 1, 2, 1)


def test_set_target_goal_and_delete_keeps_children(store):
    g = store.add_life_goal("Get fit", months=3)
    t = store.add_goal("Gym", None, None, 10, due="2027-01-31")
    store.set_target_goal(t["id"], g["id"])
    assert store.get_goal(t["id"])["life_goal_id"] == g["id"]
    todo = store.add_detailed_todo("Buy trainers", group_id=store.life_goal_group(g["id"])["id"])
    store.delete_life_goal(g["id"])
    assert store.get_goal(t["id"])["life_goal_id"] is None
    assert store.get_todo(todo["id"]) is not None
    assert store.get_life_goal(g["id"]) is None
    try:
        store.set_target_goal(t["id"], "nope")
    except ValueError:
        pass
    else:
        raise AssertionError


def test_update_months_and_archive(store):
    g = store.add_life_goal("Get fit", months=3, start="2026-01-10")
    g = store.update_life_goal(g["id"], months=12)
    assert g["end_date"] == "2027-01-10"
    store.update_life_goal(g["id"], archived=True)
    assert store.life_goals(date(2026, 6, 1)) == []
    assert [x["id"] for x in store.life_goals_past(date(2026, 6, 1))] == [g["id"]]


def test_time_left(store):
    g = {"start": "2026-11-01", "end_date": "2027-05-01"}
    assert store.time_left(g, date(2026, 11, 22)) == "5 months left"
    assert store.time_left(g, date(2027, 4, 1)) == "4 weeks left"
    assert store.time_left(g, date(2027, 4, 30)) == "1 day left"
    assert store.time_left(g, date(2027, 5, 1)) == "ends today"
    assert store.time_left(g, date(2027, 5, 2)) == "ended"


def test_csv_round_trip_and_targets_keep_their_goal(store):
    g = store.add_life_goal("Get fit", months=6, start="2026-11-01", why="Feel better")
    store.add_goal("Gym", None, "2026-11-01", 40, due="2027-03-31", life_goal_id=g["id"])
    goals_csv, targets_csv = store.load_life_goals(), store.load_goals()
    assert list(targets_csv["life_goal"]) == ["Get fit"]
    store.delete_life_goal(g["id"])
    assert store.save_life_goals(goals_csv) == 1
    store.save_goals(targets_csv)
    assert store.get_goal(targets_csv["id"][0])["life_goal_id"] == g["id"]
    assert store.get_life_goal(g["id"])["why"] == "Feel better"


def test_old_database_gets_the_new_columns(store):
    with store.db() as conn:
        for table in ("goals", "todo_groups"):
            assert "life_goal_id" in {r[1] for r in conn.execute(f"PRAGMA table_info({table})")}
    store.init_db()                                     # running again is safe
    assert isinstance(store.load_life_goals(), pd.DataFrame)
