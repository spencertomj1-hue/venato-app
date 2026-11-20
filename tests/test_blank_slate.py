"""A new install starts blank: no categories, no activity defaults. Every page still draws with none,
the chopped blocks (Money, Workouts) are gone without hurting installs that list them, and the
core blocks are marked."""

import importlib
import json
from pathlib import Path

import pytest
from streamlit.testing.v1 import AppTest

APP = str(Path(__file__).resolve().parents[1] / "app.py")


@pytest.fixture
def store(blank_store):
    """Here `store` is the blank slate: no categories made."""
    return blank_store


def _blocks():
    from venato import blocks
    return importlib.reload(blocks)


def test_fresh_database_has_no_categories_or_label_defaults(store):
    assert len(store.load_categories()) == 0
    assert len(store.load_label_map()) == 0
    assert store.groups() == []


def test_examples_are_kept_for_suggestions_only(store):
    assert {c[0] for c in store.categories.EXAMPLE_CATEGORIES} >= {"sleep", "study"}
    assert store.categories.EXAMPLE_LABEL_MAP["Lecture"] == "classes"
    assert not hasattr(store.categories, "DEFAULT_CATEGORIES")


def test_existing_database_keeps_its_categories(store):
    store.save_category("study", "Study", "#00B050", "Work")
    store.save_category("pottery", "Pottery", "#AA5500", "Life")
    store.init_db()                                           # start-up again: nothing added, nothing removed
    assert set(store.load_categories()["id"]) == {"study", "pottery"}


def test_outlook_events_are_grey_with_no_category(store):
    assert store.outlook_category("Lecture") in (None, "")


def test_outlook_category_still_picks_one_when_there_are_some(store):
    store.save_category("study", "Study", "#00B050", "Work")
    assert store.outlook_category("Lecture") == "study"          # the first, when the usual one isn't there
    store.save_category("classes", "Classes", "#00B0F0", "Work")
    assert store.outlook_category("Lecture") == "classes"


def test_core_blocks_and_starter(store):
    b = _blocks()
    core = {x.key for x in b.all_blocks() if x.core}
    assert core == {"timetable", "goals", "stats", "focus", "log", "grades"}
    assert b.STARTER == ["timetable", "goals", "stats", "focus", "log"]
    assert set(b.STARTER) <= core and "grades" not in b.STARTER


def test_money_and_workouts_are_gone(store):
    b = _blocks()
    assert b.get("money") is None and b.get("workouts") is None
    for name in ("money", "workouts"):
        assert importlib.util.find_spec(f"venato.blocks.{name}") is None
        assert importlib.util.find_spec(f"venato.ui.{name}") is None
    assert "Money" not in b.GROUPS


def test_settings_listing_chopped_blocks_load(store):
    b = _blocks()
    store.save_settings(blocks=["timetable", "money", "workouts", "goals"], blocks_optional=True)
    assert b.chosen_keys() == ["timetable", "goals"]
    assert list(b.pages()) == ["Timetable", "Goals"]
    settings = store.load_settings()
    settings.pop("blocks_optional")
    (store.DATA_DIR / "settings.json").write_text(json.dumps({**settings, "blocks": ["money", "workouts"]}))   # an older list
    assert b.chosen_keys() == ["timetable", "goals", "focus", "grades", "stats"]
    at = AppTest.from_file(APP, default_timeout=60).run()
    assert not at.exception
    at.sidebar.radio[0].set_value("Settings").run()
    assert not at.exception


def test_old_settings_keep_the_once_always_on_blocks(store):
    """Saved before blocks could be switched off: the old always-on five stay on, whatever STARTER is."""
    b = _blocks()
    store.save_settings(blocks=["log"])
    assert b.chosen_keys() == ["log", "timetable", "goals", "focus", "grades", "stats"]


def test_every_page_draws_with_zero_categories(store):
    b = _blocks()
    store.save_settings(wizard_done=True, blocks=[x.key for x in b.all_blocks()], blocks_optional=True)
    assert len(store.load_categories()) == 0
    at = AppTest.from_file(APP, default_timeout=90).run()
    assert not at.exception, at.exception
    pages = list(at.sidebar.radio[0].options)
    assert "Timetable" in pages and "Review" in pages and "Settings" in pages
    for page in pages[1:]:
        at.sidebar.radio[0].set_value(page).run()
        assert not at.exception, (page, at.exception)
    at.sidebar.radio[0].set_value("Review").run()
    at.session_state["rv_view_w"] = "Trends"                  # the charts view
    at.run()
    assert not at.exception, at.exception


def test_pages_with_zero_categories_and_some_data(store):
    """Goals that count hours, deadlines and a plan: the pages that read categories still draw."""
    b = _blocks()
    store.save_settings(wizard_done=True, blocks=[x.key for x in b.all_blocks()], blocks_optional=True)
    today = store.local_today()
    store.add_goal("Read", "monthly", today, 4, "books")
    store.add_deadline("Essay", today)
    store.add_habit("Gym")
    at = AppTest.from_file(APP, default_timeout=90).run()
    assert not at.exception, at.exception
    for page in list(at.sidebar.radio[0].options)[1:]:
        at.sidebar.radio[0].set_value(page).run()
        assert not at.exception, (page, at.exception)


def test_timetable_says_how_to_add_a_category(store):
    at = AppTest.from_file(APP, default_timeout=60).run()
    at.sidebar.radio[0].set_value("Timetable").run()
    assert not at.exception, at.exception
    assert at.button(key="tt_addcat").label == "Add a category"
    assert at.button(key="tt_btn_cats").label == "Adjust categories"


def test_focus_note_with_no_category(store):
    from venato.blocks import focus
    from datetime import datetime, timedelta
    now = datetime(2026, 11, 2, 10, 0)
    session = {"id": "s1", "kind": "focus", "minutes": 25, "label": "Read", "category_id": None,
               "started": now.isoformat(), "ended": (now + timedelta(minutes=25)).isoformat()}
    note = focus._maybe_timetable(session)
    assert "category" in note.lower() and "Add a category" in note


def test_the_first_category_can_be_made_and_names_the_first_group(store):
    from venato import tools
    assert tools.edit_category("Study", colour="#00B050", create=True).changed
    assert list(store.load_categories()["grp"]) == ["General"]
    assert tools.edit_category("Exercise", colour="#FFC000", group="General", create=True).changed
    assert store.outlook_category("Lecture") == "study"
    with pytest.raises(tools.ToolError):
        tools.edit_category("Music", colour="#112233", group="Nope", create=True)


def test_add_a_category_button_takes_you_to_the_editor(store):
    b = _blocks()
    store.save_settings(wizard_done=True, blocks=[x.key for x in b.all_blocks()], blocks_optional=True)
    at = AppTest.from_file(APP, default_timeout=60).run()
    at.sidebar.radio[0].set_value("Focus").run()
    assert not at.exception, at.exception
    for page in ("Review", "Goals"):
        at.sidebar.radio[0].set_value(page).run()
        assert not at.exception, (page, at.exception)
    at.sidebar.radio[0].set_value("Review").run()
    next(b for b in at.button if (b.key or "").endswith("_addcat")).click().run()
    assert not at.exception, at.exception
    assert at.sidebar.radio[0].value == "Timetable"
    assert "tt_open_categories" not in at.session_state              # used up
    assert any(t.label == "Name" for t in at.text_input)             # the "Adjust categories" dialog is open
    assert not store.load_categories().shape[0]


def test_assistant_errors_with_no_categories_say_what_to_do(store):
    from venato import tools
    for call in (lambda: tools.add_block("2026-11-02", "plan", "09:00", "10:00", "Read", category="Study"),
                 lambda: tools.add_goal("Read", 4, period="monthly", unit="h", category="Study")):
        with pytest.raises(tools.ToolError) as e:
            call()
        assert "no categories yet" in str(e.value) and "edit_category" in str(e.value)
        assert ": ." not in str(e.value)


def test_focus_note_follows_the_timetable_block(store):
    from datetime import datetime, timedelta
    from venato.blocks import focus
    now = datetime(2026, 11, 2, 10, 0)
    session = {"id": "s1", "kind": "focus", "minutes": 25, "label": "Read", "category_id": None,
               "started": now.isoformat(), "ended": (now + timedelta(minutes=25)).isoformat()}
    assert "Adjust categories" in focus._maybe_timetable(session)
    _blocks().save(["focus"])
    assert "Switch the Timetable on" in focus._maybe_timetable(session)
