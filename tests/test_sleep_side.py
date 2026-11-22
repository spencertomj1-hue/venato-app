"""The Timetable panel asks today's wake-up and bed time and fills Sleep blocks to the ends of the day."""

from datetime import datetime, time, timedelta
from pathlib import Path

from streamlit.testing.v1 import AppTest

from nav_helpers import goto

APP = str(Path(__file__).resolve().parents[1] / "app.py")


def _sleeps(store, day, track):
    return [(b["start"], b["end"]) for b in store.blocks_between(day.isoformat(), day.isoformat(), track)
            if b["label"] == "Sleep"]


def test_wake_and_bed_fill_from_the_day_start_and_to_the_day_end(store):
    from venato.ui import sleep_side
    day = store.local_today() + timedelta(days=14)               # not started: its Plan
    n = sleep_side.record(day, "09:30", "23:00")
    assert _sleeps(store, day, "plan") == [("07:00", "09:30"), ("23:00", "01:00")]
    assert n == 5 + 4 and sleep_side.answered(day) == {"wake": True, "bed": True}


def test_a_started_day_gets_it_in_its_actual_and_keeps_other_blocks(store):
    from venato.ui import sleep_side
    day = store.local_today() - timedelta(days=1)
    now = datetime.combine(store.local_today(), time(12))
    store.paint(day, "actual", 1, 2, {"label": "Run", "category_id": "exercise"})   # 07:30-08:00
    sleep_side.record(day, "08:30", now=now)
    assert _sleeps(store, day, "actual") == [("07:00", "07:30"), ("08:00", "08:30")]
    assert any(b["label"] == "Run" for b in store.blocks_between(day.isoformat(), day.isoformat(), "actual"))
    assert sleep_side.answered(day, now) == {"wake": True, "bed": False}


def test_times_outside_the_day_fill_nothing_but_count_as_answered(store):
    from venato.ui import sleep_side
    day = store.local_today() + timedelta(days=14)
    assert sleep_side.record(day, "06:00", "02:00") == 0
    assert _sleeps(store, day, "plan") == [] and sleep_side.answered(day) == {"wake": True, "bed": True}


def test_the_sleep_category_is_made_if_missing(blank_store):
    from venato.ui import sleep_side
    day = blank_store.local_today() + timedelta(days=14)
    sleep_side.record(day, "08:00")
    assert "Sleep" in set(blank_store.load_categories()["name"])


def test_the_panel_asks_then_goes_once_both_are_in(store):
    at = AppTest.from_file(APP, default_timeout=60).run()
    goto(at, "Timetable")
    assert not at.exception, at.exception
    assert {t.key for t in at.time_input} >= {"tt_wake", "tt_bed"}
    at.time_input(key="tt_wake").set_value(time(8)).run()
    at.time_input(key="tt_bed").set_value(time(23, 30)).run()
    at.button(key="tt_sleep_add").click().run()
    assert not at.exception, at.exception
    assert not [t for t in at.time_input if t.key in ("tt_wake", "tt_bed")]
    assert store.load_settings()["sleep_times"][store.local_today().isoformat()] == {"wake": "08:00", "bed": "23:30"}
