"""Effort-weighted goal progress (store/life_goals.py): efforts on targets and to-dos, milestone targets,
self-ratings, and the weighted pace tick."""

import sqlite3
from datetime import timedelta

import pytest


def _goal(store):
    return store.add_life_goal("Launch the app", months=6, start="2026-11-01")


def _close(a, b):
    return abs(a - b) < 1e-9


def test_effort_is_read_as_5_when_unset_and_kept_in_1_to_10(store):
    assert store.effort({}) == 5
    assert store.effort({"effort": None}) == 5
    assert store.effort({"effort": 8}) == 8
    assert store.effort({"effort": 0}) == 5          # (0 isn't a real effort: read as unset)
    assert store.effort({"effort": 14}) == 10
    g = _goal(store)
    t = store.add_goal("Users", None, "2026-11-01", 50, due="2027-01-31", life_goal_id=g["id"])
    assert t["effort"] is None and store.effort(t) == 5
    todo = store.add_detailed_todo("Write the blurb")
    assert todo["effort"] is None and store.effort(todo) == 5


def test_equal_efforts_match_the_plain_mean(store):
    g = _goal(store)
    t1 = store.add_goal("Users", None, "2026-11-01", 10, due="2027-01-31", life_goal_id=g["id"])
    t2 = store.add_goal("Reviews", None, "2026-11-01", 4, due="2027-01-31", life_goal_id=g["id"])
    store.set_goal_progress(t1["id"], 5)
    store.set_goal_progress(t2["id"], 8)                 # over target: 100%
    assert _close(store.life_goal_progress(g["id"])["fraction"], 0.75)


def test_a_big_target_outweighs_a_small_one(store):
    g = _goal(store)
    big = store.add_goal("Users", None, "2026-11-01", 10, due="2027-01-31", life_goal_id=g["id"], effort=8)
    small = store.add_goal("Licence", None, "2026-11-01", 1, due="2027-01-31", life_goal_id=g["id"], effort=2)
    store.set_goal_progress(small["id"], 1)              # the small one done, the big one not started
    assert _close(store.life_goal_progress(g["id"])["fraction"], 2 / 10)
    store.update_goal(small["id"], effort=None)          # unset: read as 5
    assert _close(store.life_goal_progress(g["id"])["fraction"], 5 / 13)
    store.set_goal_progress(big["id"], 10)
    store.set_goal_progress(small["id"], 0)
    assert _close(store.life_goal_progress(g["id"])["fraction"], 8 / 13)


def test_goal_level_todos_count_at_their_effort(store):
    g = _goal(store)
    grp = store.life_goal_group(g["id"])["id"]
    t = store.add_goal("Users", None, "2026-11-01", 10, due="2027-01-31", life_goal_id=g["id"], effort=6)
    store.set_goal_progress(t["id"], 5)                  # 0.5 × 6 = 3
    a = store.add_detailed_todo("Pick a name", group_id=grp, effort=2)
    store.add_detailed_todo("Make a logo", group_id=grp, effort=2)
    store.set_todo_done(a["id"], True)                   # 1 × 2
    p = store.life_goal_progress(g["id"])
    assert _close(p["fraction"], (3 + 2) / (6 + 2 + 2))
    # The parts behind it, for the header's breakdown.
    assert [(x["title"], x["effort"], round(x["fraction"], 2)) for x in p["parts"]] == [
        ("Users", 6, 0.5), ("Make a logo", 2, 0.0), ("Pick a name", 2, 1.0)]     # (open to-dos first)


def test_a_number_targets_todos_add_nothing(store):
    g = _goal(store)
    t = store.add_goal("Users", None, "2026-11-01", 10, due="2027-01-31", life_goal_id=g["id"])
    step = store.add_detailed_todo("Post on forums", group_id=store.ensure_target_group(t["id"]), effort=9)
    store.set_todo_done(step["id"], True)
    assert store.life_goal_progress(g["id"])["fraction"] == 0


def test_a_milestone_is_its_todos_effort_done(store):
    g = _goal(store)
    m = store.add_goal("Launch on the App Store", None, "2026-11-01", None, due="2027-01-31",
                       life_goal_id=g["id"], milestone=True)
    assert m["milestone"] and m["target"] == 1 and m["value"] == 0 and m["kind"] == "count"
    grp = store.ensure_target_group(m["id"])
    a = store.add_detailed_todo("Apple licence", group_id=grp, effort=2)
    b = store.add_detailed_todo("Screenshots", group_id=grp, effort=3)
    store.add_detailed_todo("Review", group_id=grp, effort=5)
    store.set_todo_done(a["id"], True)
    store.set_todo_done(b["id"], True)
    m = store.get_goal(m["id"])
    assert _close(m["value"], 0.5) and m["steps"] == (2, 3)
    assert _close(store.target_progress(m), 0.5)
    assert _close(store.life_goal_progress(g["id"])["fraction"], 0.5)


def test_a_milestone_with_no_todos_is_a_tick(store):
    g = _goal(store)
    m = store.add_goal("Pick a name", None, "2026-11-01", None, due="2027-01-31", life_goal_id=g["id"],
                       milestone=True)
    assert store.target_progress(store.get_goal(m["id"])) == 0
    store.set_goal_progress(m["id"], 1)
    m = store.get_goal(m["id"])
    assert store.target_progress(m) == 1 and m["steps"] == (0, 0)
    assert store.life_goal_progress(g["id"])["targets_done"] == 1


def test_a_self_rating_overrides_todos_and_tick(store):
    g = _goal(store)
    m = store.add_goal("Get good at Swift", None, "2026-11-01", None, due="2027-01-31", life_goal_id=g["id"],
                       milestone=True)
    grp = store.ensure_target_group(m["id"])
    a = store.add_detailed_todo("Course", group_id=grp)
    store.set_todo_done(a["id"], True)
    store.set_goal_progress(m["id"], 1)
    store.update_goal(m["id"], self_rating=0.3)
    m = store.get_goal(m["id"])
    assert _close(store.target_progress(m), 0.3) and m["self_rated"]
    store.update_goal(m["id"], self_rating=None)
    assert store.target_progress(store.get_goal(m["id"])) == 1
    with pytest.raises(ValueError):
        store.update_goal(m["id"], self_rating=1.5)


def test_ticking_a_milestones_last_todo_finishes_it(store):
    g = _goal(store)
    n = store.add_goal("Users", None, "2026-11-01", 10, due="2027-01-31", life_goal_id=g["id"])
    m = store.add_goal("Launch", None, "2026-11-01", None, due="2027-01-31", life_goal_id=g["id"], milestone=True)
    grp = store.ensure_target_group(m["id"])
    a = store.add_detailed_todo("Build", group_id=grp)
    b = store.add_detailed_todo("Ship", group_id=grp)
    store.set_todo_done(a["id"], True)
    before = store.life_goal_progress(g["id"])
    store.set_todo_done(b["id"], True)
    after = store.life_goal_progress(g["id"])
    assert after["fraction"] > before["fraction"] and _close(after["fraction"], 0.5)
    assert store.target_progress(store.get_goal(m["id"])) == 1 and after["targets_done"] == 1
    # It's no longer the next thing to do: the number target is.
    assert store.next_step(g["id"], "2026-11-20")["target"]["id"] == n["id"]


def test_a_number_target_can_become_a_milestone_and_back(store):
    t = store.add_goal("Users", None, "2026-11-01", 50, "users", due="2027-01-31")
    store.update_goal(t["id"], milestone=True)
    m = store.get_goal(t["id"])
    assert m["milestone"] and m["target"] == 1 and m["unit"] is None and m["progress"] == 0
    store.update_goal(t["id"], milestone=False, target=50, unit="users")
    t = store.get_goal(t["id"])
    assert not t["milestone"] and t["target"] == 50


def test_old_database_reads_null_effort_and_keeps_its_numbers(store):
    g = _goal(store)
    t1 = store.add_goal("A", None, "2026-11-01", 10, due="2027-01-31", life_goal_id=g["id"])
    t2 = store.add_goal("B", None, "2026-11-01", 4, due="2027-01-31", life_goal_id=g["id"])
    store.set_goal_progress(t1["id"], 3)
    store.set_goal_progress(t2["id"], 1)
    # An old database: no effort, milestone or self_rating columns.
    with store.db() as conn:
        for col in ("effort", "milestone", "self_rating"):
            conn.execute(f"ALTER TABLE goals DROP COLUMN {col}")
        conn.execute("ALTER TABLE todos DROP COLUMN effort")
    store.init_db()                                      # start-up adds them back, empty
    with store.db() as conn:
        conn.row_factory = sqlite3.Row
        assert {r["effort"] for r in conn.execute("SELECT effort FROM goals")} == {None}
        assert {r["milestone"] for r in conn.execute("SELECT milestone FROM goals")} == {0}
    store.bump_version()
    assert _close(store.life_goal_progress(g["id"])["fraction"], (0.3 + 0.25) / 2)


def test_expected_for_a_milestone_halfway_is_half(store):
    from venato import pace
    from venato.ui import life_goals
    today = store.local_today()
    g = store.add_life_goal("Launch", start=today - timedelta(days=10), end=today + timedelta(days=200))
    m = store.add_goal("Ship", None, today - timedelta(days=50), None, due=today + timedelta(days=49),
                       life_goal_id=g["id"], milestone=True)
    m = store.get_goal(m["id"])
    assert _close(pace.expected(m, today), 0.5)
    assert _close(life_goals.expected_fraction(g, [m], today), 0.5)


def test_expected_is_weighted_by_effort(store):
    from venato.ui import life_goals
    today = store.local_today()
    g = store.add_life_goal("Launch", start=today - timedelta(days=10), end=today + timedelta(days=200))
    done_by_now = store.add_goal("Old", None, today - timedelta(days=20), None, due=today - timedelta(days=1),
                                 life_goal_id=g["id"], milestone=True, effort=2)     # its span is all gone
    fresh = store.add_goal("New", None, today, None, due=today + timedelta(days=99),
                           life_goal_id=g["id"], milestone=True, effort=8)            # none of its span yet
    targets = store.life_goal_targets(g["id"])
    assert {t["id"] for t in targets} == {done_by_now["id"], fresh["id"]}
    assert _close(life_goals.expected_fraction(g, targets, today), 2 / 10)


def test_repeats_and_carry_over_keep_their_effort(store):
    from datetime import date
    t = store.add_todo("Stretch", "daily", date(2026, 11, 20), repeat=True, effort=3)
    store.roll_todos(date(2026, 11, 21))
    copy = [x for x in store.todos_for("daily", date(2026, 11, 21)) if x["title"] == "Stretch"][0]
    assert copy["effort"] == 3 and copy["id"] != t["id"]
    store.add_todo("Tidy", "weekly", date(2026, 11, 16), effort=7)
    store.carry_over("weekly", date(2026, 11, 16))
    assert [x["effort"] for x in store.todos_for("weekly", date(2026, 11, 23)) if x["title"] == "Tidy"] == [7]


def test_effort_outside_1_to_10_is_refused(store):
    with pytest.raises(ValueError):
        store.add_detailed_todo("Big", effort=11)
    with pytest.raises(ValueError):
        store.add_goal("Users", None, "2026-11-01", 10, due="2027-01-31", effort=0)
