"""Deadlines: store, Claude's tools, reminders and the Goals / Home pages (AppTest)."""

import importlib
from datetime import date, datetime, timedelta
from pathlib import Path

import pytest
from streamlit.testing.v1 import AppTest
from nav_helpers import goto, page_names

APP = str(Path(__file__).resolve().parents[1] / "app.py")


def test_store_and_countdown(store):
    a = store.add_deadline("Essay", "2026-11-06", "2,000 words")
    store.add_deadline("Lab report", "2026-11-02")
    assert [d["title"] for d in store.deadlines()] == ["Lab report", "Essay"]
    store.set_deadline_done(a, True)
    assert [d["title"] for d in store.deadlines()] == ["Lab report"]
    assert len(store.deadlines(include_done=True)) == 2
    store.update_deadline(a, due="2026-11-09", notes="")
    assert store.get_deadline(a)["due"] == "2026-11-09" and store.get_deadline(a)["notes"] is None
    t = date(2026, 11, 2)
    assert [store.countdown(d, t) for d in ("2026-11-02", "2026-11-03", "2026-11-07", "2026-11-01", "2026-10-30")] == \
        ["Today", "Tomorrow", "in 5 days", "1 day overdue", "3 days overdue"]
    with pytest.raises(ValueError):
        store.add_deadline(" ", "2026-11-02")


def test_tools(store, monkeypatch):
    from venato import tools
    tools = importlib.reload(tools)
    monkeypatch.setattr(store, "local_today", lambda: date(2026, 10, 30))
    assert tools.add_deadline("Essay on Kant", "2026-11-06").text == \
        "Added deadline 'Essay on Kant' due Fri 6 Nov (in 7 days)."
    tools.add_deadline("Internship application", "2026-11-15")
    assert tools.complete_deadline("essay").text.startswith("Ticked off 'Essay on Kant'")
    assert "[done]" in tools.list_deadlines(include_done=True).text
    tools.edit_deadline("internship", due="2026-11-14")
    assert store.deadlines()[0]["due"] == "2026-11-14"
    r = tools.delete_deadline("internship")
    assert r.pending and len(store.deadlines()) == 1
    r.pending.run()
    assert store.deadlines() == []


def test_deadline_reminders(store):
    from venato import notify
    notify = importlib.reload(notify)
    store.add_deadline("Essay", "2026-11-03")
    store.add_deadline("Later", "2026-11-10")
    assert notify.due_deadlines(datetime(2026, 11, 2, 8, 0), set()) == []          # before 9 am
    out = notify.due_deadlines(datetime(2026, 11, 2, 9, 5), set())
    assert [(t, b) for _, t, b in out] == [("Due tomorrow: Essay", "")]
    assert notify.due_deadlines(datetime(2026, 11, 2, 9, 5), {out[0][0]}) == []     # once a day


def test_pages(store):
    today = store.local_today()
    store.add_deadline("Essay", today + timedelta(days=3))
    store.save_settings(home=[{"w": "deadlines", "size": "s"}])                         # Home's Deadlines widget
    at = AppTest.from_file(APP, default_timeout=60).run()
    assert not at.exception
    assert any("Essay" in m.value and "in 3 days" in m.value for m in at.markdown)       # Home
    goto(at, "Goals")
    assert not at.exception and any("Deadlines" in s.value for s in at.subheader)
    box = next(t for t in at.text_input if t.label == "New deadline")
    box.set_value("Lab report")
    next(b for b in at.button if b.label == "Add" and "dl_new" in str(b.form_id)).click().run()
    assert [d["title"] for d in store.deadlines()] == ["Essay", "Lab report"]
    at.checkbox(key=f"dl_done_{store.deadlines()[0]['id']}").check().run()
    assert [d["title"] for d in store.deadlines()] == ["Lab report"]


# --- Canvas assignments (Phase 2) ---

CANVAS = (Path(__file__).parent / "fixtures" / "canvas_sample.ics").read_bytes()


def _canvas(store, raw=CANVAS):
    from venato import feeds
    return feeds.canvas_events(raw, store.tz())


def _by_uid(store):
    return {d["uid"]: d for d in store.deadlines(include_done=True) if d["uid"]}


def test_import_canvas_adds_deadlines_with_their_due_time(store):
    got = store.import_canvas(_canvas(store))
    assert got["added"] == 7
    d = _by_uid(store)["event-assignment-500210"]
    assert (d["title"], d["due"], d["due_time"], d["source"], d["module_id"], d["done"]) == \
        ("Lab Report 2 (Kinetics) Data Entry: Due Wed 25th Nov at 5pm", "2026-11-25", "17:00", "canvas", None, False)
    plain = store.get_deadline(store.add_deadline("Essay", "2026-11-06"))
    assert (plain["due_time"], plain["source"], plain["uid"], plain["module_id"]) == (None, None, None, None)


def test_resyncing_canvas_is_idempotent(store):
    store.import_canvas(_canvas(store))
    before = store.deadlines(include_done=True)
    got = store.import_canvas(_canvas(store))
    assert (got["added"], got["updated"]) == (0, 0)
    assert store.deadlines(include_done=True) == before


def test_an_assignment_redated_in_canvas_moves(store):
    store.import_canvas(_canvas(store))
    moved = CANVAS.replace(b"DTSTART:20261125T170000Z", b"DTSTART:20261127T100000Z")
    got = store.import_canvas(_canvas(store, moved))
    assert got["updated"] == 1
    d = _by_uid(store)["event-assignment-500210"]
    assert (d["due"], d["due_time"]) == ("2026-11-27", "10:00")


def test_ticked_deleted_redated_or_renamed_stay_as_the_student_left_them(store):
    store.import_canvas(_canvas(store))
    d = _by_uid(store)
    store.set_deadline_done(d["event-assignment-500210"]["id"], True)
    store.update_deadline(d["event-assignment-500210"]["id"], notes="handed in early")
    store.delete_deadline(d["event-assignment-900501"]["id"])
    store.update_deadline(d["event-assignment-500233"]["id"], due="2026-12-05", due_time="09:00")
    store.update_deadline(d["event-assignment-900502"]["id"], title="Integrity module")
    store.import_canvas(_canvas(store))
    after = _by_uid(store)
    done = after["event-assignment-500210"]
    assert done["done"] and done["done_at"] and done["notes"] == "handed in early"
    assert "event-assignment-900501" not in after                              # deleted: not brought back
    assert (after["event-assignment-500233"]["due"], after["event-assignment-500233"]["due_time"]) == \
        ("2026-12-05", "09:00")                                                 # the student's date
    assert after["event-assignment-900502"]["title"] == "Integrity module"      # the student's title
    # Canvas changes them later: a new date or title in Canvas wins, done and notes never change
    changed = (CANVAS.replace(b"DTSTART:20261125T170000Z", b"DTSTART:20261130T170000Z")
               .replace(b"SUMMARY:CORE - Academic Integrity", b"SUMMARY:CORE - Academic Integrity v2"))
    store.import_canvas(_canvas(store, changed))
    after = _by_uid(store)
    assert after["event-assignment-500210"]["due"] == "2026-11-30" and after["event-assignment-500210"]["done"]
    assert after["event-assignment-500210"]["notes"] == "handed in early"
    assert after["event-assignment-900502"]["title"] == "CORE - Academic Integrity v2"
    assert "event-assignment-900501" not in after


def test_due_time_is_checked(store):
    did = store.add_deadline("Essay", "2026-11-06", due_time="23:59")
    assert store.get_deadline(did)["due_time"] == "23:59"
    with pytest.raises(ValueError):
        store.update_deadline(did, due_time="25:00")
    store.update_deadline(did, due_time=None)
    assert store.get_deadline(did)["due_time"] is None


def test_an_older_database_only_gains_columns(tmp_path, monkeypatch):
    """Deadlines, timetable events and modules from before Phase 2 stay exactly as they were."""
    import sqlite3
    data = tmp_path / "old"
    data.mkdir()
    db = data / "life.db"
    with sqlite3.connect(db) as conn:
        conn.executescript("""
            CREATE TABLE deadlines (id TEXT PRIMARY KEY, title TEXT NOT NULL, due TEXT NOT NULL, notes TEXT,
                done INTEGER NOT NULL DEFAULT 0, done_at TEXT, created_at TEXT NOT NULL);
            INSERT INTO deadlines VALUES ('d1', 'Essay', '2026-11-06', 'long', 1, '2026-11-05T10:00', 'x');
            CREATE TABLE tt_outlook (uid TEXT PRIMARY KEY, date TEXT NOT NULL, start TEXT, "end" TEXT,
                title TEXT NOT NULL, location TEXT, all_day INTEGER NOT NULL DEFAULT 0, exact TEXT);
            INSERT INTO tt_outlook VALUES ('e1', '2026-11-02', '09:00', '10:00', 'Lecture', 'LT1', 0, '09:00–10:00');
            CREATE TABLE gr_modules (id TEXT PRIMARY KEY, name TEXT NOT NULL UNIQUE COLLATE NOCASE, code TEXT,
                credits REAL NOT NULL DEFAULT 10, year TEXT, target REAL, final REAL, created_at TEXT NOT NULL);
            INSERT INTO gr_modules VALUES ('m1', 'Organic', 'CHEM1', 20, 'Year 2', 70, NULL, 'x');
        """)
    monkeypatch.setenv("VENATO_DATA_DIR", str(data))
    monkeypatch.setenv("VENATO_DB", str(db))
    from venato import store
    store = importlib.reload(store)
    store.init_db()
    store.init_db()                                           # running again changes nothing
    d = store.get_deadline("d1")
    assert (d["title"], d["due"], d["notes"], d["done"], d["due_time"], d["module_id"], d["uid"]) == \
        ("Essay", "2026-11-06", "long", True, None, None, None)
    ev = store.outlook_between("2026-11-02", "2026-11-02")[0]
    assert (ev["title"], ev["location"], ev["module_id"], ev["module_category"]) == ("Lecture", "LT1", None, None)
    with sqlite3.connect(db) as conn:
        assert conn.execute("SELECT name, code, credits, category_id FROM gr_modules").fetchall() == \
            [("Organic", "CHEM1", 20.0, None)]
        assert conn.execute("SELECT COUNT(*) FROM deadlines_hidden").fetchone()[0] == 0


# --- Fix round 1 ---

def test_countdown_uses_the_due_time(store):
    from datetime import datetime as dt
    assert store.countdown("2026-11-20", due_time="17:00", now=dt(2026, 11, 20, 16, 0)) == "Today, 17:00"
    assert store.countdown("2026-11-20", due_time="17:00", now=dt(2026, 11, 20, 17, 1)) == "Overdue since 17:00"
    assert store.countdown("2026-11-20", now=dt(2026, 11, 20, 23, 0)) == "Today"           # no time: all day
    assert store.countdown("2026-11-21", due_time="09:00", now=dt(2026, 11, 20, 23, 0)) == "Tomorrow, 09:00"
    assert not store.deadline_overdue({"due": "2026-11-20", "due_time": "17:00"}, dt(2026, 11, 20, 16, 0))
    assert store.deadline_overdue({"due": "2026-11-20", "due_time": "17:00"}, dt(2026, 11, 20, 17, 1))
    assert not store.deadline_overdue({"due": "2026-11-20", "due_time": None}, dt(2026, 11, 20, 23, 59))
    assert store.deadline_overdue({"due": "2026-11-19", "due_time": None}, dt(2026, 11, 20, 0, 1))


def test_reminders_use_the_due_time(store):
    from venato import notify
    notify = importlib.reload(notify)
    store.add_deadline("Lab report", "2026-11-20", due_time="17:00")
    out = notify.due_deadlines(datetime(2026, 11, 20, 16, 0), set())
    assert [t for _, t, _ in out] == ["Due today at 17:00: Lab report"]
    assert notify.due_deadlines(datetime(2026, 11, 20, 17, 1), set()) == []              # overdue: no "due today"
    early = store.add_deadline("Quiz", "2026-11-21", due_time="08:00")
    morning = notify.due_deadlines(datetime(2026, 11, 21, 6, 30), set())                   # before 9 am, 1.5 h to go
    assert [t for _, t, _ in morning] == ["Due today at 08:00: Quiz"]
    assert early


def test_tools_show_the_due_time(store, monkeypatch):
    from venato import tools
    tools = importlib.reload(tools)
    monkeypatch.setattr(store, "local_now", lambda: datetime(2026, 11, 20, 16, 0))
    monkeypatch.setattr(store, "local_today", lambda: date(2026, 11, 20))
    store.add_deadline("Lab report", "2026-11-20", due_time="17:00")
    assert "(Today, 17:00)" in tools.list_deadlines().text


def test_a_canvas_time_change_keeps_a_date_the_student_moved(store):
    store.import_canvas(_canvas(store))
    did = _by_uid(store)["event-assignment-500210"]["id"]
    store.update_deadline(did, due="2026-11-28")
    store.import_canvas(_canvas(store, CANVAS.replace(b"DTSTART:20261125T170000Z", b"DTSTART:20261125T120000Z")))
    d = store.get_deadline(did)
    assert (d["due"], d["due_time"]) == ("2026-11-28", "12:00")          # the time from Canvas, their date


def test_auto_link_needs_the_exact_code(store):
    from venato.blocks import grades
    short = grades.add_module("Short", code="CHEM1")
    full = grades.add_module("Full", code="CHEM10001")
    store.import_canvas([{"uid": "event-assignment-1", "title": "Quiz", "label": "CHEM10001.2026",
                          "course_id": "7", "due": "2026-12-01", "due_time": None}])
    assert grades.canvas_courses()[0]["module_id"] == full
    assert short


def test_assistant_tools_set_and_clear_the_due_time(store):
    from venato import tools
    from venato.tools import ToolError
    tools.add_deadline("Lab report", "2026-11-20", due_time="9:05")
    d = store.deadlines()[0]
    assert d["due_time"] == "09:05"
    tools.edit_deadline("lab", due_time="17:00")
    assert store.deadlines()[0]["due_time"] == "17:00"
    tools.edit_deadline("lab", title="Lab write-up")                    # left alone when not given
    assert store.deadlines()[0]["due_time"] == "17:00"
    tools.edit_deadline("lab", due_time="")                             # "" clears it
    assert store.deadlines()[0]["due_time"] is None
    for bad in ("25:00", "5pm"):
        with pytest.raises(ToolError):
            tools.edit_deadline("lab", due_time=bad)
        with pytest.raises(ToolError):
            tools.add_deadline("Other", "2026-11-21", due_time=bad)


def test_assistant_schema_offers_due_time():
    from venato import assistant
    props = {t[0]: t[2] for t in assistant.TOOL_SPECS if t[0] in ("add_deadline", "edit_deadline")}
    assert all("due_time" in str(schema) for schema in props.values())
