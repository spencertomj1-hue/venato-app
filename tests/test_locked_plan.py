"""Plan locked at the start of the day, the Actual adjusted, then confirmed (store, tools, grid ops, Home)."""

import importlib
import sqlite3
from datetime import date, datetime
from pathlib import Path

import pytest
from streamlit.testing.v1 import AppTest
from nav_helpers import goto, page_names

APP = str(Path(__file__).resolve().parents[1] / "app.py")
NOW = datetime(2026, 11, 11, 10, 0)          # Wednesday 11 Nov, 10:00
DAY = "2026-11-10"                            # yesterday: over


def put(store, day, start, end, label, cat, track="plan"):
    store.paint(day, track, store.slot_of(start), store.slot_of(end), {"label": label, "category_id": cat})


def actual(store, day=DAY):
    return [(b["start"], b["end"], b["label"]) for b in store.blocks_between(day, day, "actual")]


def ev(uid, day, start, end, title="Lecture"):
    return {"uid": uid, "date": day, "start": start, "end": end, "title": title, "location": None,
            "all_day": 0, "exact": f"{start}–{end}"}


# ---# --- Locking ---

def test_lock_copies_the_whole_plan_and_events_keeps_actual_and_is_idempotent(store):
    put(store, DAY, "09:00", "11:00", "Revision", "study")
    put(store, DAY, "18:00", "19:00", "Gym", "exercise")
    store.replace_outlook([ev("a", DAY, "13:00", "14:00")])
    put(store, DAY, "09:30", "10:00", "Focus", "study", track="actual")       # a Focus session: it wins
    added = store.lock_day(DAY, now=NOW)
    assert actual(store) == [("09:00", "09:30", "Revision"), ("09:30", "10:00", "Focus"),
                             ("10:00", "11:00", "Revision"), ("13:00", "14:00", "Lecture"), ("18:00", "19:00", "Gym")]
    assert {b["id"] for b in added} >= {f"m:{DAY}:09:00", f"m:{DAY}:13:00"}     # ids the grid's JS agrees on
    assert store.get_outlook("a")                                               # the calendar event stays put
    assert store.confirmed_days(DAY, DAY) == []                                 # only the user confirms
    assert store.lock_day(DAY, now=NOW) == [] and len(actual(store)) == 5       # twice: nothing more


def test_today_locks_whole_day_at_its_start(store):
    today = "2026-11-11"
    put(store, today, "08:00", "12:00", "Work", "work")
    put(store, today, "20:00", "21:00", "Gym", "exercise")
    assert store.lock_day(today, now=datetime(2026, 11, 11, 6, 59)) == []     # before 07:00: still the Plan
    assert not store.day_started(today, datetime(2026, 11, 11, 6, 59))
    store.lock_day(today, now=datetime(2026, 11, 11, 7, 0))                     # the day starts: all of it, evening too
    assert actual(store, today) == [("08:00", "12:00", "Work"), ("20:00", "21:00", "Gym")]
    put(store, today, "15:00", "16:00", "Late plan", "work")                     # (a Plan change after the lock)
    store.lock_day(today, now=datetime(2026, 11, 11, 16, 0))
    assert ("15:00", "16:00", "Late plan") not in actual(store, today)          # isn't copied: the Plan was locked
    store.confirm_day(today, now=NOW.replace(hour=22))
    assert store.confirmed_days(today, today) == [today]


def test_a_part_locked_day_from_an_older_version_gets_the_rest(store):
    put(store, DAY, "08:00", "12:00", "Work", "work")
    with store.db() as conn:
        conn.execute("INSERT INTO tt_day_status VALUES (?, NULL, '10:00')", (DAY,))
        conn.execute("INSERT INTO tt_entries (id, date, track, start, \"end\", label, category_id) "
                     "VALUES ('x', ?, 'actual', '08:00', '10:00', 'Work', 'work')", (DAY,))
    store.lock_day(DAY, now=NOW)
    assert actual(store) == [("08:00", "10:00", "Work"), ("10:00", "12:00", "Work")]


def test_unconfirm_keeps_the_actual(store):
    put(store, DAY, "09:00", "11:00", "Revision", "study")
    store.confirm_day(DAY, now=NOW)
    assert store.confirmed_days(DAY, DAY) == [DAY] and actual(store) == [("09:00", "11:00", "Revision")]
    store.unconfirm_day(DAY)
    assert store.confirmed_days(DAY, DAY) == [] and actual(store) == [("09:00", "11:00", "Revision")]
    store.confirm_day(DAY, now=NOW)
    assert store.confirmed_days(DAY, DAY) == [DAY]


def test_changes_go_to_the_actual_and_the_plan_stays(store):
    put(store, DAY, "09:00", "11:00", "Revision", "study")
    put(store, DAY, "14:00", "16:00", "Project", "work")
    put(store, DAY, "18:00", "19:00", "Gym", "exercise")
    s = store.slot_of
    store.correct(DAY, s("18:00"), s("19:00"), None, now=NOW)                   # Didn't happen
    assert actual(store) == [("09:00", "11:00", "Revision"), ("14:00", "16:00", "Project")]
    store.correct(DAY, s("14:00"), s("16:00"), {"label": "Coffee", "category_id": "rest"}, now=NOW)   # something else
    store.retime(DAY, s("09:00"), s("11:00"), s("09:30"), s("12:00"), {"label": "Revision", "category_id": "study"}, now=NOW)
    assert actual(store) == [("09:30", "12:00", "Revision"), ("14:00", "16:00", "Coffee")]
    assert [b["label"] for b in store.blocks_between(DAY, DAY, "plan")] == ["Revision", "Project", "Gym"]   # Plan untouched


def test_other_day_hours(store):
    store.save_settings(day_start=6, day_end=22)
    assert store.SLOTS == 32
    other = "2026-11-09"
    put(store, other, "06:00", "07:00", "Run", "exercise")
    store.lock_day(other, now=NOW)
    assert actual(store, other) == [("06:00", "07:00", "Run")] and store.slots_gone(other, NOW) == 32


@pytest.mark.parametrize("start, first", [("Monday", "2026-11-09"), ("Sunday", "2026-11-08")])
def test_confirm_week_follows_the_week_start(store, start, first):
    from venato import tools
    tools = importlib.reload(tools)
    tools._now = lambda: NOW
    store.set_week_start(start)
    week = store.week_start_of(date(2026, 11, 11))
    assert week.isoformat() == first
    r = tools.confirm_day(week.isoformat(), "2026-11-15", preview=True)
    assert r.pending and r.pending.summary.count(",") == (1 if start == "Monday" else 2)   # Mon-Tue / Sun-Tue
    r.pending.run()
    assert store.unconfirmed_days(week, "2026-11-15", now=NOW) == []
    assert "2026-11-11" not in store.confirmed_days(week, "2026-11-15")                    # today: not over yet


def test_migration_confirms_only_days_with_actual_blocks(store, tmp_path, monkeypatch):
    put(store, "2026-10-01", "09:00", "10:00", "Gym", "exercise", track="actual")
    put(store, "2026-10-02", "09:00", "10:00", "Gym", "exercise")                   # Plan only
    with sqlite3.connect(store.DB_PATH) as conn:
        conn.execute("DROP TABLE tt_day_status")                                   # as before this version
    store.settings_path().write_text('{"wizard_done": true, "timezone": "Europe/London"}')
    store.init_db()
    assert store.confirmed_days("2026-09-01", "2026-10-31") == ["2026-10-01"]
    assert len(store.blocks_between("2026-10-01", "2026-10-02")) == 2              # nothing changed


# --- What counts ---

def test_stats_review_and_goals_count_confirmed_days_only(store, monkeypatch):
    monkeypatch.setattr(store, "local_now", lambda: NOW)
    g = store.add_goal("Study", "monthly", "2026-11-01", 20, "h", category_id="study")
    put(store, "2026-11-09", "09:00", "11:00", "Revision", "study")
    put(store, DAY, "09:00", "11:00", "Revision", "study")
    assert store.get_goal(g["id"])["value"] == 0                  # planned, nothing confirmed: not done
    store.confirm_day("2026-11-09", now=NOW)
    assert store.get_goal(g["id"])["value"] == 2
    from venato import pace, review
    importlib.reload(review)
    s = review.summary(date(2026, 11, 9))
    assert (s["days_confirmed"], s["days_so_far"], s["planned_hours"], s["followed_pct"]) == (1, 3, 2.0, 100)
    assert "from 1 of 3 days confirmed" in review.as_text(s)
    w = pace.week_goals(NOW.date(), pace.Ctx(NOW))[0]
    assert (w["done"], w["assumed"], w["confirmed_days"], w["days_so_far"]) == (2, 2, 1, 3)
    assert store.get_stats(7, today=NOW.date())["days_confirmed"] == 1


# --- Tools (Claude) ---

@pytest.fixture
def tools(store):
    from venato import tools as module
    module = importlib.reload(module)
    module._now = lambda: NOW
    return module


def test_skip_and_confirm_tools(tools, store):
    put(store, DAY, "09:00", "10:00", "Gym", "exercise")
    put(store, DAY, "12:00", "13:00", "Lunch", "rest")
    gym = store.blocks_between(DAY, DAY, "plan")[0]
    r = tools.skip_block(gym["id"])
    assert r.pending and "not having happened" in r.pending.summary
    r.pending.run()
    assert actual(store) == [("12:00", "13:00", "Lunch")] and store.confirmed_days(DAY, DAY) == []   # you confirm
    put(store, "2026-11-12", "09:00", "10:00", "Gym", "exercise")
    with pytest.raises(tools.ToolError, match="hasn't happened"):
        tools.skip_block(store.blocks_between("2026-11-12", "2026-11-12", "plan")[0]["id"])
    assert tools.confirm_day(DAY).changed and store.confirmed_days(DAY, DAY) == [DAY]
    assert "Nothing to confirm" in tools.confirm_day(DAY).text
    assert tools.confirm_day("2026-11-09").changed                           # one day: no preview needed


def test_add_block_on_actual_locks_the_day_first(tools, store):
    put(store, DAY, "09:00", "10:00", "Gym", "exercise")
    tools.add_block(DAY, "actual", "20:00", "21:00", "Cinema", category="rest")
    assert actual(store) == [("09:00", "10:00", "Gym"), ("20:00", "21:00", "Cinema")]


# --- The grid ---

def test_grid_ops(store):
    from venato.ui import timetable
    put(store, DAY, "09:00", "11:00", "Revision", "study")
    blk = {"label": "Revision", "categoryId": "study"}
    timetable.apply_grid_op({"kind": "retime", "date": DAY, "fromStart": "09:00", "fromEnd": "11:00",
                             "start": "10:00", "end": "11:30", "block": blk, "newId": "r1"})
    assert [(b["id"], b["start"], b["end"]) for b in store.blocks_between(DAY, DAY, "actual")] == [("r1", "10:00", "11:30")]
    timetable.apply_grid_op({"kind": "skip", "date": DAY, "start": "10:00", "end": "11:30"})
    assert actual(store) == []
    timetable.apply_grid_op({"kind": "confirm_day", "date": "2026-11-09"})
    assert "2026-11-09" in store.confirmed_days("2026-11-09", "2026-11-09")


def test_tools_never_change_a_locked_plan(tools, store):
    put(store, DAY, "09:00", "10:00", "Gym", "exercise")
    gym = store.blocks_between(DAY, DAY, "plan")[0]
    with pytest.raises(tools.ToolError, match="locked"):
        tools.delete_block(gym["id"])
    with pytest.raises(tools.ToolError, match="locked"):
        tools.update_block(gym["id"], start="11:00", end="12:00")
    assert "actual" in tools.add_block(DAY, "plan", "15:00", "16:00", "Walk", category="Exercise").text   # goes to the Actual
    assert [b["label"] for b in store.blocks_between(DAY, DAY, "plan")] == ["Gym"]
    put(store, "2026-11-13", "09:00", "10:00", "Gym", "exercise")                 # a day ahead: the Plan, as ever
    ahead = store.blocks_between("2026-11-13", "2026-11-13", "plan")[0]
    tools.update_block(ahead["id"], start="11:00", end="12:00").pending.run()
    assert [b["start"] for b in store.blocks_between("2026-11-13", "2026-11-13", "plan")] == ["11:00"]


def test_grid_ops_on_a_locked_plan_are_dropped_and_actual_ones_apply(store, monkeypatch):
    from venato.ui import timetable
    monkeypatch.setattr(store, "local_now", lambda: NOW)
    put(store, DAY, "09:00", "11:00", "Revision", "study")
    timetable.apply_grid_op({"kind": "paint", "date": DAY, "track": "plan", "start": "12:00", "end": "13:00",
                             "block": {"label": "Lunch", "categoryId": "rest"}, "newId": "p"})
    assert [b["label"] for b in store.blocks_between(DAY, DAY, "plan")] == ["Revision"]     # locked: dropped
    assert actual(store) == [("09:00", "11:00", "Revision")]                                 # (locked by the op)
    copy = store.blocks_between(DAY, DAY, "actual")[0]["id"]
    timetable.apply_grid_op({"kind": "move", "id": copy, "date": DAY, "track": "actual", "start": "10:00", "end": "13:00"})
    assert actual(store) == [("10:00", "13:00", "Revision")]                                 # stretched in the Actual
    assert store.confirmed_days(DAY, DAY) == []                                              # still yours to confirm


# --- Home's end-of-day prompt ---

def test_end_of_day_prompt_days(store, monkeypatch):
    from venato.ui import timetable
    monkeypatch.setattr(store, "local_today", lambda: date(2026, 11, 11))
    today = "2026-11-11"
    put(store, today, "09:00", "17:00", "Work", "work")
    assert timetable.prompt_days(datetime(2026, 11, 11, 16, 0)) == [date(2026, 11, 10)]     # yesterday only
    assert timetable.prompt_days(datetime(2026, 11, 11, 18, 0)) == [date(2026, 11, 11), date(2026, 11, 10)]
    store.confirm_day(DAY, now=NOW)
    timetable._dismiss(date(2026, 11, 11))
    assert timetable.prompt_days(datetime(2026, 11, 11, 18, 0)) == []


def test_home_confirm_and_timetable(store, monkeypatch):
    monkeypatch.setattr(store, "local_today", lambda: date(2026, 11, 11))      # mid-afternoon: yesterday is over
    monkeypatch.setattr(store, "local_now", lambda: datetime(2026, 11, 11, 14, 0))
    yesterday = "2026-11-10"
    put(store, yesterday, "09:00", "10:00", "Gym", "exercise")
    at = AppTest.from_file(APP, default_timeout=60).run()
    assert not at.exception
    ok = [b for b in at.button if b.key == f"eod_ok_{yesterday}"]
    assert ok and any("Is the timetable right for yesterday?" in m.value for m in at.markdown)
    ok[0].click().run()
    assert yesterday in store.confirmed_days(yesterday, yesterday)
    assert actual(store, yesterday) == [("09:00", "10:00", "Gym")]
    goto(at, "Timetable")
    assert not at.exception


# --- Future days are never confirmed ---

def test_migration_and_repair_leave_future_days_unconfirmed(store, monkeypatch):
    monkeypatch.setattr(store, "local_today", lambda: date(2026, 11, 11))
    put(store, "2026-11-10", "07:00", "08:00", "Sleep", "sleep", track="actual")
    put(store, "2026-11-12", "07:00", "08:00", "Sleep", "sleep", track="actual")    # a day ahead
    with sqlite3.connect(store.DB_PATH) as conn:
        conn.execute("DROP TABLE tt_day_status")
    store.init_db()
    assert store.confirmed_days("2026-11-01", "2026-11-30") == ["2026-11-10"]
    with sqlite3.connect(store.DB_PATH) as conn:                                   # as the first version left it
        conn.execute("INSERT INTO tt_day_status VALUES ('2026-11-13', 'x', '23:30')")
    store.init_db()
    assert store.day_status("2026-11-12", "2026-11-30") == {}


def test_a_future_day_cant_be_confirmed(store):
    from venato.ui import timetable
    ahead = "2026-11-13"
    put(store, ahead, "09:00", "10:00", "Gym", "exercise")
    store.confirm_day(ahead, now=NOW)
    assert store.confirmed_days(ahead, ahead) == [] and actual(store, ahead) == []
    timetable.apply_grid_op({"kind": "paint", "date": "2099-01-01", "track": "actual", "start": "09:00",
                             "end": "10:00", "block": {"label": "Gym", "categoryId": "exercise"}, "newId": "f"})
    assert store.day_status("2099-01-01", "2099-01-01") == {}                     # filling in the future: not a record


def test_confirm_all_covers_every_week_with_blocks_only(store):
    from venato import tools
    tools = importlib.reload(tools)
    tools._now = lambda: NOW
    put(store, "2026-10-20", "09:00", "10:00", "Gym", "exercise")                 # weeks back
    put(store, DAY, "09:00", "10:00", "Gym", "exercise")
    put(store, "2026-11-11", "09:00", "10:00", "Gym", "exercise")                 # today: not over
    put(store, "2026-11-13", "09:00", "10:00", "Gym", "exercise")                 # ahead
    assert store.unconfirmed_days_with_blocks(now=NOW) == ["2026-10-20", DAY]     # empty days aren't listed
    r = tools.confirm_all()
    assert r.pending and "2 days" in r.pending.summary
    r.pending.run()
    assert store.confirmed_days("2026-10-01", "2026-11-30") == ["2026-10-20", DAY]
    assert tools.confirm_all().text.startswith("Nothing to confirm")


def test_timetable_confirm_all_button(store):
    old = date.fromordinal(store.local_today().toordinal() - 20).isoformat()
    put(store, old, "09:00", "10:00", "Gym", "exercise")
    at = AppTest.from_file(APP, default_timeout=60).run()
    goto(at, "Timetable")
    btn = [b for b in at.button if b.key == "tt_btn_confirm_all"]
    assert btn and btn[0].label == "Confirm all (1 day)"
    btn[0].click().run()                            # the dialog's preview (clicking inside it: checked in a browser)
    assert not at.exception and any("Confirm 1 day as what you did" in w.value for w in at.warning)
