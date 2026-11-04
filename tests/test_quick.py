"""Quick commands: everyday logging done straight away, without Claude."""

import importlib

import pytest


@pytest.fixture
def quick(store):
    from venato import tools, quick
    importlib.reload(tools)
    return importlib.reload(quick)


def test_water(quick, store):
    today = store.local_today().isoformat()
    r = quick.handle("drank 500ml")
    assert r.reply.startswith(quick.MARK) and r.changed and store.get_entry(today)["water"] == 0.5
    quick.handle("had another 2 glasses of water")
    assert store.get_entry(today)["water"] == 1.0
    quick.handle("Drank 1.5L in total today.")
    assert store.get_entry(today)["water"] == 1.5
    quick.handle("16 oz water")
    assert store.get_entry(today)["water"] == pytest.approx(1.5 + 16 * 0.0295735, abs=1e-3)
    for text in ("had a coffee", "had 3", "drank a lot", "drank 500ml and went to the gym"):
        assert quick.handle(text) is None, text


def test_scores(quick, store):
    today = store.local_today().isoformat()
    quick.handle("mood 4")
    quick.handle("energy was 3/5")
    quick.handle("slept 7.5h last night")
    e = store.get_entry(today)
    assert (e["mood"], e["energy"], e["sleep"]) == (4, 3, 7.5)
    r = quick.handle("mood 2")                        # overwriting asks first, like Claude's tool
    assert r.pending and store.get_entry(today)["mood"] == 4
    assert quick.handle("mood 9") is None             # out of range: Claude explains
    assert quick.handle("my mood is great") is None


def test_habits_and_todos(quick, store):
    from venato import tools
    tools.add_habit("Gym")
    tools.add_todo("Finish essay", "daily")
    today = store.local_today()
    hid = store.find_habit("Gym")[0]
    assert quick.handle("tick gym").changed and today.isoformat() in store.get_habit_dates(hid)
    quick.handle("did gym yesterday")
    from datetime import timedelta
    assert (today - timedelta(days=1)).isoformat() in store.get_habit_dates(hid)
    assert quick.handle("done finish essay").changed
    assert quick.handle("tick something else entirely") is None
    assert quick.handle("tick gym and add a lecture") is None
    store.save_settings(quick_commands=False)
    assert quick.handle("drank 500ml") is None        # switched off in Settings


def test_a_broken_block_handler_never_breaks_quick(store, monkeypatch):
    import importlib
    from venato import quick
    quick = importlib.reload(quick)
    def boom(text, day):
        raise RuntimeError("bug")
    monkeypatch.setattr(quick, "EXTRA", [boom])
    assert quick.handle("something odd") is None
