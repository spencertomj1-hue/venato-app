"""#20: habits are their own block (page + Home tile), no longer part of the Daily Log."""

from pathlib import Path

from streamlit.testing.v1 import AppTest
from nav_helpers import goto, page_names

APP = str(Path(__file__).resolve().parents[1] / "app.py")


def _blocks():
    import importlib
    from venato import blocks
    return importlib.reload(blocks)


def test_an_install_with_the_daily_log_keeps_its_habits(store):
    b = _blocks()
    store.save_settings(blocks=["timetable", "log", "stats"], blocks_optional=True)   # saved before the split
    assert b.chosen_keys() == ["timetable", "log", "habits", "stats"]
    b.save(["timetable", "log", "stats"])                                             # switched off since: stays off
    assert not b.is_on("habits")


def test_no_daily_log_no_habits_added(store):
    b = _blocks()
    store.save_settings(blocks=["timetable"], blocks_optional=True)
    assert b.chosen_keys() == ["timetable"]


def test_habits_without_the_daily_log(store):
    _blocks().save(["habits"])
    store.add_habit("Stretch")
    assert "Habits" in page_names() and "Daily Log" not in page_names()
    assert [r["kind"] for r in store.search("stretch")] == ["Habit"]


def test_the_habits_page_ticks_this_week(store):
    _blocks().save(["habits"])
    store.add_habit("Stretch", 3)
    hid = store.find_habit("Stretch")[0]
    at = goto(AppTest.from_file(APP, default_timeout=60).run(), "Habits")
    assert not at.exception
    today = store.local_today().isoformat()
    at.checkbox(key=f"habit_{hid}_{today}").check().run()
    assert not at.exception
    assert today in store.get_habit_dates(hid)
    assert any("1 of 3 this week" in c.value for c in at.caption)


def test_the_daily_log_has_no_habit_section(store):
    _blocks().save(["log", "habits"])
    store.add_habit("Stretch")
    at = goto(AppTest.from_file(APP, default_timeout=60).run(), "Daily Log")
    assert not at.exception
    assert not [c for c in at.checkbox if c.key and c.key.startswith("habit_")]
    assert not any(e.label == "Manage habits" for e in at.expander)
