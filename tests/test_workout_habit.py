"""#20: logging a workout counts towards the habit setup made for a fitness goal ("Trained") once the user says
yes, so its target doesn't say 0 this week after a workout. Never linked without asking."""

import importlib
from datetime import timedelta
from pathlib import Path

import pytest
from streamlit.testing.v1 import AppTest
from nav_helpers import goto

APP = str(Path(__file__).resolve().parents[1] / "app.py")


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


def _ticked(store, day):
    return day.isoformat() in store.get_habit_dates(store.find_habit("Trained")[0])


def test_never_linked_without_asking(wk, store):
    _trained_target(store)
    wk.add_workout(store.local_today(), "Legs")
    assert wk.linked_habit() is None and not _ticked(store, store.local_today())
    assert wk.habit_offer()[1] == "Trained"
    from venato import blocks
    assert any("towards Trained" in n["text"] for n in blocks.needs())


def test_yes_counts_this_and_earlier_workouts(wk, store):
    target = _trained_target(store)
    today = store.local_today()
    wk.add_workout(today - timedelta(days=1), "Legs")            # before the goal started: ticked, not counted
    wk.set_habit_link(wk.habit_offer()[1])                       # Yes
    assert _ticked(store, today - timedelta(days=1)) and wk.habit_offer() is None
    wk.add_workout(today, "Push")
    assert _ticked(store, today) and store.get_goal(target)["value"] == 1


def test_moving_a_workout_ticks_its_new_day(wk, store):
    _trained_target(store)
    wk.set_habit_link("Trained")
    today = store.local_today()
    w = wk.add_workout(today - timedelta(days=1), "Legs")
    wk.update_workout(w, date=today.isoformat())
    assert _ticked(store, today)


def test_no_is_remembered(wk, store):
    _trained_target(store)
    wk.add_workout(store.local_today(), "Legs")
    wk.set_habit_link(None)                                      # No
    wk.add_workout(store.local_today(), "Push")
    assert wk.habit_offer() is None and not _ticked(store, store.local_today())


def test_nothing_asked_before_a_workout_or_for_other_habits(wk, store):
    store.add_habit("Meditate")
    wk.add_workout(store.local_today(), "Legs")
    assert wk.habit_offer() is None
    store.delete_habit(store.find_habit("Meditate")[0])
    _trained_target(store)
    with store.db() as conn:
        conn.execute("DELETE FROM wk_workouts")
    assert wk.habit_offer() is None


def test_the_workouts_page_asks(wk, store):
    _trained_target(store)
    wk.add_workout(store.local_today(), "Legs")
    at = goto(AppTest.from_file(APP, default_timeout=60).run(), "Workouts")
    assert not at.exception
    at.button(key="wk_offer_yes").click().run()
    assert not at.exception, at.exception
    assert wk.linked_habit()[1] == "Trained" and _ticked(store, store.local_today())
    assert not [b for b in at.button if b.key == "wk_offer_yes"]
    at.selectbox(key="wk_habit").select("(none)").run()            # Settings tab: changing it still saves
    assert not at.exception and wk.linked_habit() is None
