"""Blocks: finding them, switching them on and off, their order, and what they bring."""

import importlib
from pathlib import Path

from streamlit.testing.v1 import AppTest

APP = str(Path(__file__).resolve().parents[1] / "app.py")


def _blocks():
    from venato import blocks
    return importlib.reload(blocks)


def test_registry_and_defaults(store):
    b = _blocks()
    keys = [x.key for x in b.all_blocks()]
    assert {"timetable", "goals", "log", "applications", "network", "stats"} <= set(keys)
    assert len(keys) == len(set(keys))
    assert b.chosen_keys()[:2] == ["timetable", "goals"]          # never chose: the original pages, on
    assert all(b.get(k).default for k in b.chosen_keys())


def test_switch_order_and_pages(store):
    b = _blocks()
    b.save(["stats", "timetable", "nonsense", "stats"])            # unknown keys and repeats are dropped
    assert b.chosen_keys() == ["stats", "timetable"]
    assert list(b.pages()) == ["Timetable", "Stats"]                # the sidebar keeps its own order
    assert b.is_on("stats") and not b.is_on("network")


def test_app_follows_the_choice(store):
    b = _blocks()
    b.save(["timetable", "stats"])
    at = AppTest.from_file(APP, default_timeout=60).run()
    assert not at.exception
    assert list(at.sidebar.radio[0].options) == ["Home", "Timetable", "Stats", "Settings"]


def test_settings_tab_switches_blocks(store):
    b = _blocks()
    at = AppTest.from_file(APP, default_timeout=60).run()
    at.sidebar.radio[0].set_value("Settings").run()
    at.toggle(key="set_block_network").set_value(False).run()
    assert not at.exception and not b.is_on("network")
    assert "Network" not in at.sidebar.radio[0].options
    at.button(key="set_down_timetable").click().run()                # priority order
    assert b.chosen_keys()[:2] == ["goals", "timetable"]
