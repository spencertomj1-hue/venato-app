"""
Nothing is preset: a new install (without "presets") starts with no timetable categories,
activity defaults, network groups or starter lists; everything is the user's own.
"""

import importlib


def test_a_new_install_starts_empty(tmp_path, monkeypatch):
    data = tmp_path / "fresh"
    monkeypatch.setenv("VENATO_DATA_DIR", str(data))
    monkeypatch.setenv("VENATO_DB", str(data / "life.db"))
    monkeypatch.delenv("VENATO_PRESETS", raising=False)
    from venato import store
    store = importlib.reload(store)
    store.init_db()
    assert not store.use_presets()
    assert store.load_categories().empty and store.load_label_map().empty
    with store.db() as conn:
        assert conn.execute("SELECT COUNT(*) FROM net_groups").fetchone()[0] == 0
    from venato.blocks import cutdown, money, workouts
    assert cutdown.trackers() == [] and money.categories() == [] and workouts.exercises() == []
    assert store.day_trackers() == [] and store.work_bars() == [] and store.goal_categories() == {}

    # A category is made where it's needed: here, from the timetable's new-event form.
    from venato.ui import timetable
    timetable._apply({"kind": "paint", "date": "2026-11-16", "track": "plan", "start": "09:00", "end": "10:00",
                      "block": {"label": "Pottery", "categoryId": "", "newCategory": "Hobbies"}})
    cats = store.load_categories()
    assert list(cats["name"]) == ["Hobbies"]
    block = store.blocks_between("2026-11-16", "2026-11-16", "plan")[0]
    assert (block["label"], block["category_id"]) == ("Pottery", cats["id"][0])
    timetable._apply({"kind": "paint", "date": "2026-11-16", "track": "plan", "start": "11:00", "end": "12:00",
                      "block": {"label": "Kiln", "categoryId": "", "newCategory": "hobbies"}})
    assert list(store.load_categories()["name"]) == ["Hobbies"]                # the same one, not a second


def test_presets_can_be_switched_on(store):
    assert store.use_presets()                                                  # the tests' own setting
    assert "Study" in list(store.load_categories()["name"])
