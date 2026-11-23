"""#20: logging a workout counts towards the habit setup made for a fitness goal ("Trained"), so its target
doesn't say 0 this week after a workout."""

import importlib
from datetime import timedelta

import pytest


@pytest.fixture
def wk(store):
    from venato import blocks, tools
    importlib.reload(tools)
    importlib.reload(blocks)
    from venato.blocks import workouts as module
    module = importlib.reload(module)
    blocks.save(blocks.chosen_keys() + ["workouts"])
    return module


def _trained_target(store):
    """What setup makes for "Get fit" with the Trained suggestion picked: a habit and a target counting it."""
    from venato.ui import onboarding
    goal = store.add_life_goal("Get fit", months=3)
    return onboarding.habit_target(goal, "Trained")


def test_a_workout_ticks_setups_fitness_habit(wk, store):
    target = _trained_target(store)
    wk.add_workout(store.local_today(), "Legs")
    assert store.local_today().isoformat() in store.get_habit_dates(store.find_habit("Trained")[0])
    assert store.get_goal(target)["value"] == 1


def test_workouts_logged_before_the_link_are_counted(wk, store):
    today = store.local_today()
    wk.add_workout(today, "Legs")                     # no fitness habit yet: nothing to tick
    _trained_target(store)
    assert wk.linked_habit()[1] == "Trained"
    assert today.isoformat() in store.get_habit_dates(store.find_habit("Trained")[0])


def test_moving_a_workout_ticks_its_new_day(wk, store):
    _trained_target(store)
    today = store.local_today()
    w = wk.add_workout(today - timedelta(days=1), "Legs")
    wk.update_workout(w, date=today.isoformat())
    assert today.isoformat() in store.get_habit_dates(store.find_habit("Trained")[0])


def test_no_link_chosen_stays_off(wk, store):
    """Picking "(none)" in Settings → Workouts is respected: no guessing afterwards."""
    _trained_target(store)
    wk.set_habit_link(None)
    wk.add_workout(store.local_today(), "Legs")
    assert wk.linked_habit() is None
    assert store.local_today().isoformat() not in store.get_habit_dates(store.find_habit("Trained")[0])


def test_an_unrelated_habit_is_never_guessed(wk, store):
    store.add_habit("Meditate")
    wk.add_workout(store.local_today(), "Legs")
    assert wk.linked_habit() is None
