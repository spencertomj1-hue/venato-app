"""Workouts block: exercises, sets, plans, PBs / 1RM, volume, units, habit link, tools, page."""

import importlib
from datetime import date
from pathlib import Path

import pytest
from streamlit.testing.v1 import AppTest

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


def test_sets_pbs_and_progress(wk, store):
    bench = wk.find_exercise("bench")
    assert bench["name"] == "Bench press"
    w1 = wk.add_workout("2026-11-02", "Push")
    wk.add_sets(w1, bench["id"], 1, 10, 40, warmup=True)
    wk.add_sets(w1, bench["id"], 3, 8, 60)
    w2 = wk.add_workout("2026-11-05", "Push")
    wk.add_sets(w2, bench["id"], 3, 5, 70)
    assert wk.summary(w1) == "Bench press 3×8 @ 60 kg"           # warm-ups don't count
    pb = wk.personal_bests()["Bench press"]
    assert pb["heaviest"] == (70, "2026-11-05")
    assert pb["best_1rm"][0] == pytest.approx(70 * (1 + 5 / 30))
    rows = wk.progress(bench["id"])
    assert [r[0] for r in rows] == ["2026-11-02", "2026-11-05"] and rows[0][3] == 24
    assert wk.one_rep_max(100, 1) == 100 and wk.one_rep_max(100, 20) is None
    vol = wk.weekly_volume(date(2026, 11, 2), date(2026, 11, 8))
    assert vol["Chest"] == {"sets": 6, "tonnage": 3 * 8 * 60 + 3 * 5 * 70}


def test_plans_units_and_habit(wk, store):
    from venato import tools
    tools.add_habit("Gym")
    wk.set_habit_link("Gym")
    w = wk.add_workout(store.local_today(), "Legs")
    assert store.local_today().isoformat() in store.get_habit_dates(store.find_habit("Gym")[0])
    wk.add_sets(w, wk.find_exercise("squat")["id"], 5, 5, 100)
    pid = wk.save_plan_from(w, "Legs A")
    w2 = wk.start_from_plan(pid, "2026-12-01")
    assert wk.summary(w2) == "Squat 5×5 @ 100 kg"
    wk.save_units("lb", "mi")
    assert wk.weight_text(100) == "220.5 lb" and wk.kg_in(220.5) == pytest.approx(100.02, abs=0.01)
    with pytest.raises(wk.WorkoutError):
        wk.add_sets(w, wk.find_exercise("squat")["id"], 0)


def test_tools_and_quick(wk, store):
    from venato import quick
    importlib.reload(quick)
    r = wk.tool_log([{"name": "Bench press", "sets": 3, "reps": 8, "weight": 60},
                     {"name": "Running", "distance": 5, "minutes": 28}])
    assert r.changed and "Bench press 3×8 @ 60 kg" in r.text and "Running 5 km" in r.text
    q = quick.handle("squat 5x5 at 100")
    assert q and "Squat 5×5 @ 100 kg" in q.reply
    assert quick.handle("zorbing 3x8") is None                    # unknown exercise: Claude decides
    today = store.local_today()
    assert len(wk.workouts(today, today)) == 1                    # all went into today's workout
    assert "Squat" in wk.tool_bests().text and "Bench press" in wk.tool_progress("bench").text
    assert "1 workout(s) this week" in wk._context()


def test_page(wk, store):
    wid = wk.add_workout(store.local_today(), "Push")
    wk.add_sets(wid, wk.find_exercise("bench")["id"], 3, 8, 60)
    at = AppTest.from_file(APP, default_timeout=60).run()
    at.sidebar.radio[0].set_value("Workouts").run()
    assert not at.exception
