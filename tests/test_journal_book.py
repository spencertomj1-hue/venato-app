"""
The journal book on the Daily Log: to-dos written into a page, the left page's one-at-a-time
fields (mood, energy, productivity, sleep, water) and the user's own day trackers.
"""

import pytest


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


def test_left_page_fields_keep_the_rest_of_the_day(store):
    day = "2026-11-04"
    store.save_journal(day, "Dear diary")
    store.set_entry_field(day, "mood", 8)
    store.set_entry_field(day, "productivity", 12)               # clamped to 10
    store.set_entry_field(day, "sleep", 7.5)
    store.set_entry_field(day, "water", 1.75)
    e = store.get_entry(day)
    assert (e["mood"], e["productivity"], e["sleep"], e["water"], e["notes"]) == (8, 10, 7.5, 1.75, "Dear diary")
    store.set_entry_field(day, "mood", None)
    assert store.get_entry(day)["mood"] is None and store.get_entry(day)["notes"] == "Dear diary"


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
