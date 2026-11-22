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
