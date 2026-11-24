"""Claude's tools for long-term goals, and targets / to-dos put under them."""

import pytest


@pytest.fixture
def tools(store):
    from venato import tools as t
    return t


def test_add_list_edit_delete(store, tools):
    r = tools.add_life_goal("Get fit", months=6, why="Rugby season")
    assert r.changed and "Get fit" in r.text
    assert not tools.add_life_goal("get fit", months=3).changed               # already there
    g = store.life_goals()[0]
    tools.add_goal("Gym", 40, unit="sessions", due=store.months_on(store.local_today(), 3).isoformat(),
                   life_goal="fit")
    tools.add_todo("Buy trainers", "weekly", life_goal="Get fit")
    text = tools.list_life_goals().text
    assert "Get fit" in text and "target Gym" in text and "to-do Buy trainers" in text
    assert "under the goal Get fit" in tools.list_goals().text
    tools.edit_life_goal("Get fit", months=12)
    assert store.horizon_of(store.get_life_goal(g["id"])) == 12
    tools.edit_goal("Gym", life_goal="none")
    assert store.life_goal_targets(g["id"]) == []
    r = tools.delete_life_goal("Get fit")
    assert r.pending and store.get_life_goal(g["id"])
    r.pending.run()
    assert store.get_life_goal(g["id"]) is None


def test_errors(store, tools):
    with pytest.raises(tools.ToolError):
        tools.add_life_goal("Get fit")                                        # no length
    with pytest.raises(tools.ToolError):
        tools.add_todo("X", "daily", life_goal="nothing like it")
    with pytest.raises(tools.ToolError):
        tools.edit_life_goal("missing", months=3)


def test_milestones_and_effort_through_the_tools(store, tools):
    due = store.months_on(store.local_today(), 3).isoformat()
    tools.add_life_goal("Launch the app", months=6)
    r = tools.add_goal("Launch on the App Store", due=due, milestone=True, effort=8, life_goal="Launch")
    assert r.changed and "milestone" in r.text
    m = store.life_goal_targets(store.life_goals()[0]["id"])[0]
    assert m["milestone"] and m["effort"] == 8
    tools.add_todo("Apple licence", "weekly", target="Launch on the App Store", effort=2)
    tools.add_todo("Screenshots", "weekly", target="Launch on the App Store", effort=2)
    tools.complete_todo("Apple licence")
    text = tools.list_life_goals().text
    assert "milestone Launch on the App Store" in text and "50% (1 of 2 steps)" in text and "effort 8" in text
    with pytest.raises(tools.ToolError):
        tools.log_goal_progress("Launch on the App Store")
    tools.edit_goal("Launch on the App Store", self_rating=30, effort=6)
    m = store.get_goal(m["id"])
    assert m["self_rated"] and abs(m["value"] - 0.3) < 1e-9 and m["effort"] == 6
    tools.edit_goal("Launch on the App Store", clear_self_rating=True)
    assert not store.get_goal(m["id"])["self_rated"]
    tools.edit_todo("Screenshots", effort=9)
    assert [t["effort"] for t in store.target_todos(m["id"]) if t["title"] == "Screenshots"] == [9]
    with pytest.raises(tools.ToolError):
        tools.add_goal("Users", 50, due=due, effort=12)
    with pytest.raises(tools.ToolError):
        tools.edit_goal("Launch on the App Store", milestone=False, self_rating=20)
