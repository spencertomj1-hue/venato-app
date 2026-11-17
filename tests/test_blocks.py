"""Blocks: finding them, switching them on and off, their order, and what they bring."""

import importlib
import json
from pathlib import Path

from streamlit.testing.v1 import AppTest

APP = str(Path(__file__).resolve().parents[1] / "app.py")


def _blocks():
    from venato import blocks
    return importlib.reload(blocks)


def test_registry_and_defaults(store):
    b = _blocks()
    keys = [x.key for x in b.all_blocks()]
    assert {"timetable", "goals", "log", "focus", "grades", "money", "workouts", "stats"} <= set(keys)
    assert len(keys) == len(set(keys))
    assert b.chosen_keys()[:2] == ["timetable", "goals"]          # never chose: core plus the defaults
    assert all(b.get(k).core or b.get(k).default for k in b.chosen_keys())


def test_switch_order_and_pages(store):
    b = _blocks()
    b.save(["stats", "timetable", "nonsense", "stats", "money"])   # unknown keys and repeats are dropped
    assert b.chosen_keys() == ["goals", "focus", "grades", "stats", "timetable", "money"]   # core first if left out
    assert list(b.pages()) == ["Timetable", "Goals", "Focus", "Grades", "Review", "Money"]   # the sidebar keeps its own order
    assert b.is_on("stats") and not b.is_on("workouts")


def test_leftover_blocks_come_after_optional(store):
    b = _blocks()
    b.save(["health", "food", "workouts", "money", "log"])
    assert list(b.pages()) == ["Timetable", "Goals", "Focus", "Grades", "Review", "Daily Log", "Money", "Workouts",
                               "Food", "Health data"]


def test_app_follows_the_choice(store):
    b = _blocks()
    b.save(["money"])
    at = AppTest.from_file(APP, default_timeout=60).run()
    assert not at.exception
    assert list(at.sidebar.radio[0].options) == ["Home", "Timetable", "Goals", "Focus", "Grades", "Review", "Money", "Settings"]


def test_settings_tab_switches_blocks(store):
    b = _blocks()
    at = AppTest.from_file(APP, default_timeout=60).run()
    at.sidebar.radio[0].set_value("Settings").run()
    at.toggle(key="set_block_money").set_value(True).run()
    assert not at.exception and b.is_on("money")
    assert "Money" in at.sidebar.radio[0].options
    at.toggle(key="set_block_money").set_value(False).run()
    assert not at.exception and not b.is_on("money")
    assert "Money" not in at.sidebar.radio[0].options
    assert not [t for t in at.toggle if t.key in ("set_block_timetable", "set_block_stats")]   # core: always on
    assert any(c.value == "Always on" for c in at.caption)
    at.button(key="set_down_timetable").click().run()                # priority order
    assert b.chosen_keys()[:2] == ["goals", "timetable"]


CORE = ["timetable", "goals", "focus", "grades", "stats"]


def test_core_always_on(store):
    b = _blocks()
    store.save_settings(blocks=[])
    assert b.chosen_keys() == CORE
    assert [x.key for x in b.all_blocks() if x.core] == CORE
    assert b.get("stats").name == "Review"


def test_unknown_saved_keys_ignored(store):
    b = _blocks()
    store.save_settings(blocks=["food", "network", "money"])      # food and network still exist, but are not core
    assert set(b.chosen_keys()) >= {*CORE, "money"}
    store.save_settings(blocks=["gone", "money"])
    assert b.chosen_keys() == [*CORE, "money"]
    at = AppTest.from_file(APP, default_timeout=60).run()
    assert not at.exception


def test_existing_install_keeps_log(store):
    b = _blocks()
    settings = store.load_settings()
    settings.pop("blocks", None)
    (store.DATA_DIR / "settings.json").write_text(json.dumps(settings))
    assert b.is_on("log") and all(k in b.chosen_keys() for k in CORE)
    assert not b.is_on("money") and not b.is_on("workouts")


def _install(monkeypatch, **extra):
    from venato import blocks
    real = list(blocks.all_blocks())
    fake = blocks.Block(key="fake", name="Fake", icon=":material/star:", blurb="A test block", **extra)
    monkeypatch.setattr(blocks, "all_blocks", lambda: [*real, fake])
    return blocks, fake


def _gadgets(store):
    with store.db() as conn:
        conn.execute("CREATE TABLE IF NOT EXISTS gadgets (id INTEGER PRIMARY KEY, name TEXT, notes TEXT, made TEXT)")
        conn.execute("INSERT INTO gadgets (name, notes, made) VALUES ('Sprocket', 'spins fast', '2026-10-01')")


_SEARCH = {"Gadget": ("SELECT id, name, notes, made, NULL FROM gadgets", "name || ' ' || COALESCE(notes, '')")}


def test_block_search_kind_found(store, monkeypatch):
    blocks, _ = _install(monkeypatch, search=_SEARCH, search_icons={"Gadget": "build"})
    blocks.save(["fake"])
    _gadgets(store)
    found = store.search("sprocket")
    assert [(r["kind"], r["title"], r["date"]) for r in found] == [("Gadget", "Sprocket", "2026-10-01")]


def test_disabled_block_not_searched(store, monkeypatch):
    blocks, _ = _install(monkeypatch, search=_SEARCH)
    blocks.save(["timetable"])
    _gadgets(store)
    assert store.search("sprocket") == []


def test_review_sections_from_block(store, monkeypatch):
    from datetime import date
    from venato import review
    blocks, _ = _install(monkeypatch, review=lambda first, last: {"title": "Gadgets", "lines": [f"Made 3 from {first}"]})
    blocks.save(["fake"])
    s = review.summary(date(2026, 10, 26))
    assert {"key": "fake", "title": "Gadgets", "lines": ["Made 3 from 2026-10-26"]} in s["sections"]
    assert "Gadgets: Made 3 from 2026-10-26" in review.as_text(s)
    blocks.save(["timetable"])
    assert all(x["key"] != "fake" for x in review.summary(date(2026, 10, 26))["sections"])
