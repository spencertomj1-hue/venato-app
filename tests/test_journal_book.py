"""
The journal book on the Daily Log: to-dos written into a page, sleep and water set one at a time,
the user's own day trackers, and the page (closed: the journal box; open: the book instead).
"""

from pathlib import Path

import pytest
from streamlit.testing.v1 import AppTest

APP = str(Path(__file__).resolve().parents[1] / "app.py")


def test_quoted_and_marked_text_become_todos_once(store):
    from venato import journal
    text = 'Long day. Need to "buy monitors" and “call the bank”. This week: ^meal prep^, and ^Meal prep^ again.'
    assert journal.extract(text) == [("daily", "Buy monitors"), ("daily", "Call the bank"), ("weekly", "Meal prep")]
    day = "2026-11-04"
    assert journal.save(day, 'Felt good. "Buy monitors" and ^Meal prep^') == [("daily", "Buy monitors"),
                                                                             ("weekly", "Meal prep")]
    assert [t["title"] for t in store.todos_for("daily", day)] == ["Buy monitors"]
    assert [t["title"] for t in store.todos_for("weekly", day)] == ["Meal prep"]
    assert store.get_journal(day).startswith("Felt good")
    # Saving again, or after the to-do was deleted, never adds it twice; only new ones are added.
    store.delete_todo(store.todos_for("daily", day)[0]["id"])
    assert journal.save(day, 'Felt good. "Buy monitors" and ^Meal prep^ "Gym"') == [("daily", "Gym")]
    # While typing (not final) nothing is added.
    assert journal.save(day, 'Felt good. "Stretch"', make_todos=False) == []


def test_sleep_and_water_one_at_a_time_keep_the_rest_of_the_day(store):
    day = "2026-11-04"
    store.save_journal(day, "Dear diary")
    store.set_entry_field(day, "sleep", 30)                       # clamped to 24
    store.set_entry_field(day, "water", 1.75)
    e = store.get_entry(day)
    assert (e["sleep"], e["water"], e["notes"]) == (24, 1.75, "Dear diary")
    store.set_entry_field(day, "sleep", None)
    assert store.get_entry(day)["sleep"] is None and store.get_entry(day)["notes"] == "Dear diary"
    assert set(store.ENTRY_FIELDS) == {"sleep", "water"}          # no mood / energy / productivity


def test_day_trackers(store):
    reading = store.add_day_tracker("Reading", "hours", 0.5)
    assert store.find_day_tracker("reading")["id"] == reading["id"]
    with pytest.raises(ValueError):
        store.add_day_tracker("READING")
    store.set_day_value("2026-11-04", reading["id"], 1.5)
    store.set_day_value("2026-11-05", reading["id"], 0)                 # logged as none, not blank
    assert store.day_values("2026-11-04") == {reading["id"]: 1.5}
    assert [r[2] for r in store.day_values_between("2026-11-01", "2026-11-30")] == [1.5, 0]
    store.update_day_tracker(reading["id"], name="Books", step=1)
    assert store.day_trackers()[0]["name"] == "Books" and store.day_trackers()[0]["step"] == 1
    store.set_day_value("2026-11-04", reading["id"], None)
    assert store.day_values("2026-11-04") == {}
    store.delete_day_tracker(reading["id"])
    assert store.day_trackers() == [] and store.day_values_between("2026-11-01", "2026-11-30") == []


def _log_page():
    from nav_helpers import goto
    at = AppTest.from_file(APP, default_timeout=60).run()
    goto(at, "Daily Log")
    assert not at.exception, at.exception
    return at


def _book(at):
    from fragment_run import component_data
    return component_data(at, "journal")


def test_page_book_closed_keeps_the_journal_box(store):
    store.set_tracking(sleep=True, water=False)
    store.add_day_tracker("Reading", "hours", 0.5)
    at = _log_page()
    book = _book(at)
    assert book["open"] is False and book["showSleep"] is True and book["showWater"] is False
    assert [t["name"] for t in book["trackers"]] == ["Reading"]
    assert book["prompt"]                                           # Tom's prompt of the day
    assert "Journal" in [w.label for w in at.text_area]            # the journal box is there


def test_page_book_open_replaces_the_journal_box(store):
    at = AppTest.from_file(APP, default_timeout=60)
    at.session_state["journal_open"] = True
    at.run()
    from nav_helpers import goto
    goto(at, "Daily Log")
    assert not at.exception, at.exception
    assert _book(at)["open"] is True
    assert "Journal" not in [w.label for w in at.text_area]
    assert any("journal book above" in c.value for c in at.caption)
