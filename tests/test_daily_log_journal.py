"""Phase 3: the Daily Log is a journal, with optional sleep and water. Mood, energy and productivity are gone."""

import importlib
from pathlib import Path

import pandas as pd
import pytest
from streamlit.testing.v1 import AppTest
from nav_helpers import goto, page_names

APP = str(Path(__file__).resolve().parents[1] / "app.py")
OLD = ("mood", "energy", "productiv")


def _no_old_words(texts):
    return not any(w in str(t).lower() for t in texts for w in OLD)


def _log_page(store):
    store.save_settings(blocks=["log"])
    at = AppTest.from_file(APP, default_timeout=60).run()
    goto(at, "Daily Log")
    assert not at.exception
    return at


def _labels(at):
    return [*(w.label for w in at.text_area), *(w.label for w in at.number_input), *(w.label for w in at.slider),
            *(m.label for m in at.metric), *(b.label for b in at.button)]


def _seed_old_scores(store, day="2026-10-28"):
    with store.db() as conn:
        conn.execute("INSERT INTO entries (date, mood, energy, productivity, notes) VALUES (?, 7, 6, 8, 'old')", (day,))


# --- the switches ---

def test_new_install_has_sleep_and_water_off(blank_store):
    assert not blank_store.tracks_sleep() and not blank_store.tracks_water()


def test_existing_values_count_as_on_until_chosen(blank_store):
    with blank_store.db() as conn:
        blank_store.save_entry(conn, "2026-10-28", None, 7.0)
    assert blank_store.tracks_sleep() and not blank_store.tracks_water()
    blank_store.set_tracking(sleep=False)                         # an explicit choice wins
    assert not blank_store.tracks_sleep()
    assert blank_store.get_entry("2026-10-28")["sleep"] == 7.0    # and nothing is deleted


# --- the page ---

def test_page_leads_with_journal_and_hides_sleep_and_water_by_default(blank_store):
    at = _log_page(blank_store)
    labels = _labels(at)
    assert "Journal" in labels and not any("Sleep" in l or "Water" in l for l in labels)
    assert _no_old_words(labels)
    assert not at.slider                                          # no mood / energy / productivity sliders


def test_page_saves_notes_sleep_and_water(blank_store):
    blank_store.set_tracking(sleep=True, water=True)
    at = _log_page(blank_store)
    at.text_area[0].set_value("A good day.")
    next(n for n in at.number_input if n.label.startswith("Sleep")).set_value(7.5)
    next(n for n in at.number_input if n.label.startswith("Water")).set_value(2.0)
    next(b for b in at.button if b.label.startswith("Save")).click().run()
    assert not at.exception
    e = blank_store.get_entry(blank_store.local_today().isoformat())
    assert (e["notes"], e["sleep"], e["water"]) == ("A good day.", 7.5, 2.0)


def test_page_saves_notes_alone_when_switches_off(blank_store):
    at = _log_page(blank_store)
    at.text_area[0].set_value("Just words.")
    next(b for b in at.button if b.label.startswith("Save")).click().run()
    e = blank_store.get_entry(blank_store.local_today().isoformat())
    assert e["notes"] == "Just words." and e["sleep"] is None and e["water"] is None


def test_each_switch_shows_only_its_own_field(blank_store):
    blank_store.set_tracking(sleep=True, water=False)
    labels = _labels(_log_page(blank_store))
    assert any(l.startswith("Sleep") for l in labels) and not any(l.startswith("Water") for l in labels)
    blank_store.set_tracking(sleep=False, water=True)
    labels = _labels(_log_page(blank_store))
    assert any(l.startswith("Water") for l in labels) and not any(l.startswith("Sleep") for l in labels)


def test_page_shows_no_old_scores_even_with_old_data(blank_store):
    _seed_old_scores(blank_store, blank_store.local_today().isoformat())
    at = _log_page(blank_store)
    assert _no_old_words(_labels(at))
    assert at.text_area[0].value == "old"


def test_saving_a_day_keeps_old_scores_in_the_database(blank_store):
    day = blank_store.local_today().isoformat()
    _seed_old_scores(blank_store, day)
    blank_store.set_tracking(sleep=True, water=True)
    at = _log_page(blank_store)
    at.text_area[0].set_value("Rewritten.")
    next(n for n in at.number_input if n.label.startswith("Sleep")).set_value(6.0)
    next(b for b in at.button if b.label.startswith("Save")).click().run()
    with blank_store.db() as conn:
        row = conn.execute("SELECT mood, energy, productivity, notes, sleep FROM entries WHERE date = ?", (day,)).fetchone()
    assert row == (7, 6, 8, "Rewritten.", 6.0)


def test_store_writes_never_touch_old_scores(blank_store):
    _seed_old_scores(blank_store)
    with blank_store.db() as conn:
        blank_store.save_entry(conn, "2026-10-28", "new", 5.0, 1.0)
        blank_store.save_entry(conn, "2026-10-28")                   # nothing to set: still untouched
    blank_store.save_journal("2026-10-28", "")                       # clearing the notes keeps the row
    with blank_store.db() as conn:
        assert conn.execute("SELECT mood, energy, productivity FROM entries").fetchone() == (7, 6, 8)


# --- the calendar ---

def test_calendar_marks_days_with_an_entry_and_hides_switched_off_fields(blank_store):
    from venato.ui import daily_log
    rows = [{"date": "2026-10-27", "notes": "Wrote", "sleep": 7.0, "water": 2.0, "mood": 5},
            {"date": "2026-10-28", "notes": None, "sleep": 6.0, "water": None, "mood": 9}]
    off = daily_log.calendar_days(rows, False, False)
    assert off == {"2026-10-27": {"notes": True}, "2026-10-28": {"notes": False}}
    on = daily_log.calendar_days(rows, True, True)
    assert on["2026-10-27"] == {"notes": True, "sleep": 7.0, "water": 2.0}
    assert not any("mood" in d for d in on.values())
    js = (Path(daily_log.HERE) / "components" / "calendar_component.js").read_text()
    assert "has-entry" in js and "data.showSleep" in js and "data.showWater" in js


# --- tools, assistant, CSV, quick, review ---

def test_tools_and_assistant_have_no_old_fields(blank_store):
    from venato import assistant, tools
    importlib.reload(tools)
    importlib.reload(assistant)
    spec = next(s for s in assistant.tool_specs() if s[0] == "log_day")
    assert set(spec[2]["properties"]) == {"date", "notes", "append_notes"}      # sleep and water are off
    blank_store.set_tracking(sleep=True, water=True)
    spec = next(s for s in assistant.tool_specs() if s[0] == "log_day")
    assert {"sleep", "water"} <= set(spec[2]["properties"])
    assert _no_old_words([str(spec), assistant.system_prompt()])
    blank_store.set_tracking(sleep=False, water=False)
    assert "water" not in assistant.system_prompt().split("What the app tracks")[1].split("- Habits")[0]


def test_csv_export_has_no_old_columns_and_follows_the_switches(blank_store):
    _seed_old_scores(blank_store)
    with blank_store.db() as conn:
        blank_store.save_entry(conn, "2026-10-28", "old", 7.0, 2.0)
    blank_store.set_tracking(sleep=False, water=False)
    assert list(blank_store.load_all_data().columns) == ["date", "notes"]
    blank_store.set_tracking(sleep=True, water=True)
    cols = list(blank_store.load_all_data().columns)
    assert cols == ["date", "notes", "sleep", "water"] and _no_old_words(cols)


def test_import_replace_keeps_old_scores(blank_store):
    _seed_old_scores(blank_store)
    blank_store.save_all_data(pd.DataFrame({"date": ["2026-10-29"], "notes": ["n"]}), replace=True)
    with blank_store.db() as conn:
        assert conn.execute("SELECT mood FROM entries WHERE date = '2026-10-28'").fetchone() == (7,)


def test_settings_page_has_the_switches(blank_store):
    at = AppTest.from_file(APP, default_timeout=60).run()
    goto(at, "Settings")
    assert not at.exception
    sleep = next(t for t in at.toggle if t.key == "log_sleep_on")
    water = next(t for t in at.toggle if t.key == "log_water_on")
    assert not sleep.value and not water.value
    sleep.set_value(True).run()
    assert blank_store.tracks_sleep() and not blank_store.tracks_water()


def test_nothing_user_facing_mentions_old_scores():
    root = Path(__file__).resolve().parents[1] / "venato"
    skip = {"schema.py", "journal.py", "history.py"}                  # the old column names, in comments and SQL
    for f in list(root.rglob("*.py")) + list(root.rglob("*.js")) + list(root.rglob("*.css")) + [root.parent / "app.py"]:
        if f.name in skip:
            continue
        text = f.read_text(encoding="utf-8").lower()
        assert not any(w in text for w in OLD), f


def test_replace_import_keeps_measures_the_csv_does_not_carry(blank_store):
    with blank_store.db() as conn:
        blank_store.save_entry(conn, "2026-10-28", "old", 7.0, 2.0)
    blank_store.set_tracking(sleep=False, water=False)
    df = blank_store.load_all_data()                                   # exported with notes only
    assert "water" not in df.columns
    blank_store.save_all_data(df, replace=True)
    e = blank_store.get_entry("2026-10-28")
    assert (e["notes"], e["sleep"], e["water"]) == ("old", 7.0, 2.0)


def test_rows_with_only_old_scores_are_not_logged_days(blank_store):
    from venato import review
    from datetime import date
    _seed_old_scores(blank_store, "2026-10-28")
    with blank_store.db() as conn:
        conn.execute("UPDATE entries SET notes = NULL")
        conn.execute("INSERT INTO entries (date, water) VALUES ('2026-10-27', 2.0)")
    blank_store.set_tracking(sleep=False, water=False)
    assert blank_store.get_stats(7, today=date(2026, 10, 29))["days_logged"] == 0
    assert review.summary(date(2026, 10, 26))["days_logged"] == 0
    blank_store.set_tracking(water=True)
    assert blank_store.get_stats(7, today=date(2026, 10, 29))["days_logged"] == 1
    assert review.summary(date(2026, 10, 26))["days_logged"] == 1


def test_prompt_mentions_water_only_when_on(blank_store):
    from venato import assistant
    blank_store.set_tracking(water=False)
    assert "water" not in assistant.system_prompt().lower().split("what the app tracks")[0]
    assert "water" not in assistant.system_prompt().lower().split("- habits")[0].split("what the app tracks")[1]
    blank_store.set_tracking(water=True)
    assert "water" in assistant.system_prompt().split("- Habits")[0]


def test_existing_install_check_follows_writes(blank_store):
    assert not blank_store.tracks_water()
    with blank_store.db() as conn:
        blank_store.save_entry(conn, "2026-10-28", water=1.0)
    assert blank_store.tracks_water()
