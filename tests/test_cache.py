"""kit.cached: reads are remembered until the data (or settings.json) changes."""

import threading
from datetime import timedelta


def _kit():
    import importlib
    from venato import cache
    from venato.ui import kit
    importlib.reload(cache)             # (the `store` fixture reloads store, so these must see the new one)
    return importlib.reload(kit)


def test_cached_stats_see_new_log(store):
    cached_stats = _kit().cached(store.get_stats)
    today = store.local_today()
    assert cached_stats(7)["days_logged"] == 0
    with store.db() as conn:
        store.save_entry(conn, today.isoformat(), 7, 8, 6, "ok")
    assert cached_stats(7)["days_logged"] == 1      # not the remembered answer


def test_cached_sees_background_thread_write(store):
    cached_habits = _kit().cached(store.get_habits)
    assert cached_habits() == []
    t = threading.Thread(target=store.add_habit, args=("Gym",))
    t.start()
    t.join()
    assert [name for _, name in cached_habits()] == ["Gym"]


def test_cached_remembers_until_something_changes(store):
    calls = []

    def probe(x):
        calls.append(x)
        return {"x": x}

    cached_probe = _kit().cached(probe)
    first = cached_probe(1)
    first["x"] = 99                                 # callers may change what they get back
    assert cached_probe(1) == {"x": 1} and calls == [1]
    store.add_habit("Gym")
    cached_probe(1)
    assert calls == [1, 1]


def test_cached_sees_settings_change(store):
    cached_settings = _kit().cached(lambda: dict(store.load_settings()))
    assert "week_start" not in cached_settings()
    store.save_settings(week_start="sunday")
    assert cached_settings()["week_start"] == "sunday"


def test_cached_is_per_database(store, tmp_path, monkeypatch):
    kit = _kit()
    cached_habits = kit.cached(store.get_habits)
    store.add_habit("Gym")
    assert len(cached_habits()) == 1
    version = store.data_version()
    other = tmp_path / "other.db"
    monkeypatch.setattr(store, "DB_PATH", other)
    store.init_db()
    monkeypatch.setattr(store, "data_version", lambda: version)      # same version, same arguments...
    assert cached_habits() == []                                     # ...but another database
