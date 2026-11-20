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
    assert {"timetable", "goals", "log", "focus", "grades", "stats"} <= set(keys)
    assert len(keys) == len(set(keys))
    settings = store.load_settings()
    settings.pop("blocks", None)
    (store.DATA_DIR / "settings.json").write_text(json.dumps(settings))
    assert b.chosen_keys()[:2] == ["timetable", "goals"]          # never chose: the defaults
    assert all(b.get(k).default for k in b.chosen_keys())


def test_switch_order_and_pages(store):
    b = _blocks()
    b.save(["stats", "timetable", "nonsense", "stats", "grades"])   # unknown keys and repeats are dropped
    assert b.chosen_keys() == ["stats", "timetable", "grades"]
    assert list(b.pages()) == ["Timetable", "Grades", "Review"]       # the sidebar keeps its own order
    assert b.is_on("stats") and not b.is_on("focus") and not b.is_on("goals")


def test_every_block_can_be_switched_off(store):
    b = _blocks()
    b.save([])
    assert b.chosen_keys() == [] and b.pages() == {}
    store.search("anything")                                        # no built-in kinds without their blocks
    at = AppTest.from_file(APP, default_timeout=60).run()
    assert not at.exception
    assert list(at.sidebar.radio[0].options) == ["Home", "Settings"]


def test_app_follows_the_choice(store):
    b = _blocks()
    b.save(["grades"])
    at = AppTest.from_file(APP, default_timeout=60).run()
    assert not at.exception
    assert list(at.sidebar.radio[0].options) == ["Home", "Grades", "Settings"]


def test_settings_tab_switches_blocks(store):
    b = _blocks()
    b.save(b.STARTER)
    at = AppTest.from_file(APP, default_timeout=60).run()
    at.sidebar.radio[0].set_value("Settings").run()
    at.toggle(key="set_block_grades").set_value(True).run()
    assert not at.exception and b.is_on("grades")
    assert "Grades" in at.sidebar.radio[0].options
    at.toggle(key="set_block_grades").set_value(False).run()
    assert not at.exception and not b.is_on("grades")
    assert "Grades" not in at.sidebar.radio[0].options
    at.toggle(key="set_block_timetable").set_value(False).run()       # nothing is always on
    assert not at.exception and not b.is_on("timetable")
    assert "Timetable" not in at.sidebar.radio[0].options
    assert not any(c.value == "Always on" for c in at.caption)
    at.button(key="set_down_goals").click().run()                    # priority order
    assert b.chosen_keys()[:2] == ["stats", "goals"]


def test_saved_before_blocks_were_optional_keeps_the_starter(store):
    b = _blocks()
    store.save_settings(blocks=["log"])                               # an older install's list, no blocks_optional
    assert b.chosen_keys() == ["log", "timetable", "goals", "focus", "grades", "stats"]   # the once always-on ones stay
    assert b.get("stats").name == "Review"
    b.save(["log"])                                                   # once saved now, it's exactly the list
    assert b.chosen_keys() == ["log"]


def test_unknown_saved_keys_ignored(store):
    b = _blocks()
    b.save(["gone", "no_such_block", "log"])                        # e.g. blocks a later version removed
    assert b.chosen_keys() == ["log"]
    store.save_settings(blocks=["gone", "log"])
    assert b.chosen_keys() == ["log"]
    at = AppTest.from_file(APP, default_timeout=60).run()
    assert not at.exception


def test_existing_install_keeps_log(store):
    b = _blocks()
    settings = store.load_settings()
    settings.pop("blocks", None)
    (store.DATA_DIR / "settings.json").write_text(json.dumps(settings))
    assert b.is_on("log") and all(k in b.chosen_keys() for k in b.STARTER)


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


def test_old_saved_order_keeps_its_order(store):
    """A list saved before blocks were optional: its order stays first, the once always-on ones follow."""
    b = _blocks()
    store.save_settings(blocks=["timetable", "goals", "stats", "log", "grades"])    # saved before Focus and Grades existed
    assert b.chosen_keys() == ["timetable", "goals", "stats", "log", "grades", "focus"]


def test_core_blocks_bring_home_widgets(store):
    b = _blocks()
    offered = {w.key: w.size for w in b.widgets()}
    assert {"timetable_today": "l", "todos": "s", "deadlines": "s", "goals": "m", "habits": "m", "journal": "s",
            "focus": "s", "modules": "m"}.items() <= offered.items()
    b.save(["goals"])
    assert [w.key for w in b.widgets()] == ["todos", "deadlines", "goals"]      # only the switched-on blocks'


def test_block_with_old_home_is_one_widget(store, monkeypatch):
    """A block from another copy that still sets `home` (no widgets): one widget keyed by the block, medium."""
    drawn = []
    blocks, fake = _install(monkeypatch, home=lambda: drawn.append(1))
    blocks.save(["fake"])
    (w,) = blocks.widgets()
    assert (w.key, w.name, w.size) == ("fake", "Fake", "m")
    store.save_settings(home=[{"w": "fake", "size": "full"}])
    at = AppTest.from_file(APP, default_timeout=60).run()
    assert not at.exception and drawn


def test_block_needs_are_gathered(store, monkeypatch):
    def broken():
        raise RuntimeError("no")
    blocks, _ = _install(monkeypatch, needs=lambda: ["Feed the cat", {"text": "Vet", "page": "Settings"}, ""])
    blocks.save(["fake"])
    assert [(n["text"], n["page"], n["block"]) for n in blocks.needs()] == [("Feed the cat", None, "fake"),
                                                                          ("Vet", "Settings", "fake")]
    monkeypatch.setattr(blocks.get("fake"), "needs", broken)
    assert blocks.needs() == []                                            # a broken block is skipped
