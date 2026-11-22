"""The Timetable asks once when you wake up and go to bed, and the timetable day then runs between them."""

from pathlib import Path

import pytest
from streamlit.testing.v1 import AppTest

from nav_helpers import goto

APP = str(Path(__file__).resolve().parents[1] / "app.py")


def timetable():
    at = AppTest.from_file(APP, default_timeout=60).run()
    goto(at, "Timetable")
    assert not at.exception, at.exception
    return at


def test_saving_wake_and_bed_sets_the_timetable_day(store):
    at = timetable()
    at.selectbox(key="tt_wake").set_value(9).run()
    at.selectbox(key="tt_bed").set_value(2).run()
    at.button(key="tt_sleep_save").click().run()
    assert store.day_hours() == (9, 2) and store.slot_count() == 34
    assert not [b for b in at.button if b.key == "tt_sleep_save"]        # asked once


def test_free_time_is_only_while_awake(store):
    from venato.ui import timetable as tt
    tt.save_sleep_hours(10, 22)
    day = store.local_today()
    from datetime import timedelta
    runs = store.free_runs(day + timedelta(days=14))
    assert runs == [(0, 24)] and store.first_min() == 10 * 60


def test_too_short_a_day_is_refused(store):
    from venato.ui import timetable as tt
    with pytest.raises(ValueError):
        tt.save_sleep_hours(9, 12)
    at = timetable()
    at.selectbox(key="tt_wake").set_value(9).run()
    at.selectbox(key="tt_bed").set_value(12).run()
    at.button(key="tt_sleep_save").click().run()
    assert at.error and "day_start" not in store.load_settings()


def test_not_now_stops_asking_and_keeps_the_hours(store):
    at = timetable()
    at.button(key="tt_sleep_later").click().run()
    assert not [b for b in at.button if b.key == "tt_sleep_save"]
    assert store.day_hours() == (store.DAY_START, store.DAY_END)


def test_hours_already_set_in_settings_are_not_asked_again(store):
    store.save_settings(day_start=8, day_end=0)
    at = timetable()
    assert not [b for b in at.button if b.key == "tt_sleep_save"]
