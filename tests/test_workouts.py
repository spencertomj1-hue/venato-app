"""Workouts block: exercises, sets, plans, PBs / 1RM, volume, units, habit link, tools, page."""

import importlib
from datetime import date
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
    goto(at, "Workouts")
    assert not at.exception


PLAN_TEXT = """\
Monday - Push
- Bench press 3x8 @ 60
- Overhead press 3 sets of 10 40kg
- Tricep pushdown 3x12-15

Day 2: Legs
1. Squat 5x5 @ 100
2. Plank 3x45s
3. Run 5 km

Wed: Pull-up 3x8, Barbell row 4x8 @ 50
Some line we can't read 12/3
"""


def test_parse_plan_text_and_csv(wk, store):
    days, skipped = wk.parse_plan(PLAN_TEXT)
    assert [(d["name"], d["weekday"]) for d in days] == [("Push", 0), ("Legs", None), ("Wednesday", 2)]
    push, legs, pull = days
    assert [(i["exercise"], i["sets"], i["reps"], i["weight"]) for i in push["items"]] == [
        ("Bench press", 3, 8, 60), ("Overhead press", 3, 10, 40), ("Tricep pushdown", 3, 12, None)]
    assert [(i["exercise"], i["sets"], i["reps"], i["kind"]) for i in legs["items"]] == [
        ("Squat", 5, 5, None), ("Plank", 3, None, "timed"), ("Run", 1, None, "cardio")]
    assert (pull["name"], pull["weekday"]) == ("Wednesday", 2)
    assert [i["exercise"] for i in pull["items"]] == ["Pull-up", "Barbell row"]
    assert skipped == ["Some line we can't read 12/3"]

    wk.save_units("lb", "mi")
    days, _ = wk.parse_plan("Upper\nBench 3x5 135\nUpper\nRow 3x8 @ 60kg")
    assert [d["name"] for d in days] == ["Upper", "Upper 2"]
    assert days[0]["items"][0]["weight"] == pytest.approx(135 * wk.LB)
    assert days[1]["items"][0]["weight"] == 60

    days, _ = wk.parse_plan("Day,Exercise,Sets,Reps,Weight\nPush,Bench press,3,8,60 lb\nLegs,Squat,5,5,")
    assert [(d["name"], d["items"][0]["exercise"], d["items"][0]["reps"]) for d in days] == [
        ("Push", "Bench press", 8), ("Legs", "Squat", 5)]
    assert days[0]["items"][0]["weight"] == pytest.approx(60 * wk.LB)


def test_schedule_plan_fits_around_the_week(wk, store):
    from datetime import datetime
    from venato import tools
    tools._now = lambda: datetime(2026, 11, 22, 20, 0)               # Sunday evening
    start = date(2026, 11, 23)                                       # Monday
    store.paint(start.isoformat(), "plan", store.slot_of("07:00"), store.slot_of("12:00"),
                {"label": "Lecture", "category_id": store.resolve_category(label="Lecture"), "details": None})
    days, _ = wk.parse_plan("Monday: Bench 3x8\nLegs\nSquat 5x5\nPull\nPull-up 3x8")
    placed, missed = wk.fit_plan(days, start, weeks=2, minutes=60, earliest="07:00", latest="21:00")
    assert not missed and len(placed) == 6
    first_week = [(d.isoformat(), store.slot_time(s), day["name"]) for d, s, e, day in placed[:3]]
    assert first_week == [("2026-11-23", "12:00", "Monday"), ("2026-11-25", "07:00", "Legs"),
                          ("2026-11-27", "07:00", "Pull")]
    r = wk.schedule_plan(days, start, weeks=1)
    assert r.pending and "Monday" in r.pending.summary and not wk.plans()
    done = r.pending.run()
    assert done.changed and {p["name"] for p in wk.plans()} == {"Monday", "Legs", "Pull"}
    blocks = store.blocks_between("2026-11-23", "2026-11-29", "plan")
    gym = [b for b in blocks if b["label"] in ("Monday", "Legs", "Pull")]
    assert len(gym) == 3 and all(b["category_id"] == "exercise" for b in gym)
    assert next(b for b in gym if b["label"] == "Legs")["details"] == "- Squat 5x5"
    with pytest.raises(tools.ToolError):
        wk.schedule_plan(days, start, minutes=60, earliest="07:00", latest="07:30")


def test_upload_plan_page(wk, store):
    at = AppTest.from_file(APP, default_timeout=60).run()
    goto(at, "Workouts")
    area = next(t for t in at.text_area if t.key == "wk_up_text")
    area.set_value(PLAN_TEXT).run()
    assert not at.exception
    assert any("Found 3 workouts a week" in m.value for m in at.markdown)
    next(b for b in at.button if b.label == "Find times").click().run()
    assert not at.exception
    yes = next(b for b in at.button if b.key == "wk_up_yes")
    assert any("add" in i.value and "workouts to your Plan" in i.value for i in at.info)
    yes.click().run()
    assert not at.exception
    assert {p["name"] for p in wk.plans()} == {"Push", "Legs", "Wednesday"}


def test_plan_with_weeks_progresses(wk, store):
    from datetime import datetime
    from venato import tools
    from venato.ui.workouts import CLAUDE_PROMPT
    tools._now = lambda: datetime(2026, 11, 22, 20, 0)               # Sunday evening
    days, skipped = wk.parse_plan(CLAUDE_PROMPT.split("Example of the format:\n")[1].split("\n\nAbout me")[0])
    assert not skipped and wk.plan_weeks(days) == [1, 2]
    assert [(wk.plan_name(d), d["weekday"]) for d in days] == [
        ("Push · Week 1", 0), ("Legs · Week 1", 3), ("Push · Week 2", 0), ("Legs · Week 2", 3)]
    assert days[2]["items"][0]["weight"] == 62.5
    days, _ = wk.parse_plan("**Week 1**\nPush\nBench 3x8 @ 60kg\n\n## Week 2 (heavier)\nPush\nBench 3x8 @ 65kg")
    assert [(d["week"], d["items"][0]["weight"]) for d in days] == [(1, 60), (2, 65)]
    placed, missed = wk.fit_plan(days, "2026-11-23", weeks=10)       # weeks come from the plan
    assert not missed and [(d.isoformat(), day["week"]) for d, s, e, day in placed] == [
        ("2026-11-23", 1), ("2026-11-30", 2)]
    wk.schedule_plan(days, "2026-11-23").pending.run()
    assert {p["name"] for p in wk.plans()} == {"Push · Week 1", "Push · Week 2"}
    b = [b for b in store.blocks_between("2026-11-30", "2026-11-30", "plan") if b["label"] == "Push"][0]
    assert b["details"] == "Week 2\n- Bench 3x8 @ 65kg"


def test_upload_page_shows_weeks(wk, store):
    from venato.ui.workouts import EXAMPLE
    at = AppTest.from_file(APP, default_timeout=60).run()
    goto(at, "Workouts")
    assert any("Get Claude to write your plan" in m.value for m in at.markdown)
    next(t for t in at.text_area if t.key == "wk_up_text").set_value(EXAMPLE).run()
    assert not at.exception
    assert any("Found 2 weeks, 4 workouts in all" in m.value for m in at.markdown)
    assert [t.label for t in at.tabs if t.label.startswith("Week")] == ["Week 1", "Week 2"]
