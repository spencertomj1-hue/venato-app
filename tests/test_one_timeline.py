"""One timeline: plan once, Actual as a correction of the Plan, day confirmation (store, tools, grid ops, Home)."""

import importlib
import sqlite3
from datetime import date, datetime
from pathlib import Path

import pytest
from streamlit.testing.v1 import AppTest

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


# --- Materialising ---

def test_materialise_copies_plan_and_events_keeps_actual_and_is_idempotent(store):
    put(store, DAY, "09:00", "11:00", "Revision", "study")
    put(store, DAY, "18:00", "19:00", "Gym", "exercise")
    store.replace_outlook([ev("a", DAY, "13:00", "14:00")])
    put(store, DAY, "09:30", "10:00", "Focus", "study", track="actual")       # a Focus session: it wins
    added = store.materialise(DAY, now=NOW)
    assert actual(store) == [("09:00", "09:30", "Revision"), ("09:30", "10:00", "Focus"),
                             ("10:00", "11:00", "Revision"), ("13:00", "14:00", "Lecture"), ("18:00", "19:00", "Gym")]
    assert {b["id"] for b in added} >= {f"m:{DAY}:09:00", f"m:{DAY}:13:00"}     # ids the grid's JS agrees on
    assert store.get_outlook("a")                                               # the calendar event stays put
    assert store.confirmed_days(DAY, DAY) == [DAY]                              # a past day: confirmed
    assert store.materialise(DAY, now=NOW) == [] and len(actual(store)) == 5    # twice: nothing more


def test_today_materialises_only_what_has_passed(store):
    today = "2026-11-11"
    put(store, today, "08:00", "12:00", "Work", "work")
    store.materialise(today, now=NOW)                             # 10:00
    assert actual(store, today) == [("08:00", "10:00", "Work")]
    assert store.day_status(today, today)[today] == {"confirmed": False, "upto": store.slot_of("10:00")}
    store.materialise(today, now=NOW.replace(hour=11))            # later: carries on from 10:00
    assert actual(store, today) == [("08:00", "10:00", "Work"), ("10:00", "11:00", "Work")]
    store.confirm_day(today, now=NOW.replace(hour=13))
    assert store.confirmed_days(today, today) == [today]


def test_corrections_leave_the_rest_of_the_day_as_planned(store):
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


def test_blocks_after_midnight_and_other_day_hours(store):
    put(store, DAY, "23:00", "01:00", "Out", "rest")
    store.materialise(DAY, now=datetime(2026, 11, 11, 0, 30))     # 00:30: the day isn't over yet
    assert actual(store) == [("23:00", "00:30", "Out")] and not store.confirmed_days(DAY, DAY)
    store.materialise(DAY, now=datetime(2026, 11, 11, 1, 0))
    assert actual(store) == [("23:00", "00:30", "Out"), ("00:30", "01:00", "Out")] and store.confirmed_days(DAY, DAY)
    store.save_settings(day_start=6, day_end=22)
    assert store.SLOTS == 32
    other = "2026-11-09"
    put(store, other, "06:00", "07:00", "Run", "exercise")
    store.materialise(other, now=NOW)
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
    assert store.timetable_view() == "split"                                       # an existing install keeps its view
    assert len(store.blocks_between("2026-10-01", "2026-10-02")) == 2              # nothing changed


def test_new_installs_default_to_one_timeline(store):
    assert store.timetable_view() == "one"


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
    assert actual(store) == [("12:00", "13:00", "Lunch")] and store.confirmed_days(DAY, DAY) == [DAY]
    put(store, "2026-11-12", "09:00", "10:00", "Gym", "exercise")
    with pytest.raises(tools.ToolError, match="hasn't happened"):
        tools.skip_block(store.blocks_between("2026-11-12", "2026-11-12", "plan")[0]["id"])
    assert "Nothing to confirm" in tools.confirm_day(DAY).text
    assert tools.confirm_day("2026-11-09").changed                           # one day: no preview needed


def test_add_block_on_actual_materialises_the_day(tools, store):
    put(store, DAY, "09:00", "10:00", "Gym", "exercise")
    tools.add_block(DAY, "actual", "20:00", "21:00", "Cinema", category="rest")
    assert actual(store) == [("09:00", "10:00", "Gym"), ("20:00", "21:00", "Cinema")]


# --- The grid ---

def test_grid_ops(store):
    from venato.ui import timetable
    put(store, DAY, "09:00", "11:00", "Revision", "study")
    store.save_settings(timetable_view="one")
    blk = {"label": "Revision", "categoryId": "study"}
    timetable.apply_grid_op({"kind": "retime", "date": DAY, "fromStart": "09:00", "fromEnd": "11:00",
                             "start": "10:00", "end": "11:30", "block": blk, "newId": "r1"})
    assert [(b["id"], b["start"], b["end"]) for b in store.blocks_between(DAY, DAY, "actual")] == [("r1", "10:00", "11:30")]
    timetable.apply_grid_op({"kind": "skip", "date": DAY, "start": "10:00", "end": "11:30"})
    assert actual(store) == []
    timetable.apply_grid_op({"kind": "confirm_day", "date": "2026-11-09"})
    assert "2026-11-09" in store.confirmed_days("2026-11-09", "2026-11-09")


def test_side_by_side_view_behaves_as_before(store):
    from venato.ui import timetable
    store.save_settings(timetable_view="split")
    put(store, DAY, "09:00", "11:00", "Revision", "study")
    timetable.apply_grid_op({"kind": "paint", "date": DAY, "track": "actual", "start": "09:00", "end": "10:00",
                             "block": {"label": "Revision", "categoryId": "study"}, "newId": "x"})
    assert actual(store) == [("09:00", "10:00", "Revision")]                # no Plan copied in
    assert store.confirmed_days(DAY, DAY) == [DAY]                            # filled in by hand: the truth


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


def test_home_all_as_planned_and_timetable_views(store):
    yesterday = date.fromordinal(store.local_today().toordinal() - 1).isoformat()
    put(store, yesterday, "09:00", "10:00", "Gym", "exercise")
    at = AppTest.from_file(APP, default_timeout=60).run()
    assert not at.exception
    ok = [b for b in at.button if b.key == f"eod_ok_{yesterday}"]
    assert ok and any("Anything not go to plan yesterday?" in m.value for m in at.markdown)
    ok[0].click().run()
    assert yesterday in store.confirmed_days(yesterday, yesterday)
    assert actual(store, yesterday) == [("09:00", "10:00", "Gym")]
    for view in ("one", "split"):
        store.save_settings(timetable_view=view)
        at.sidebar.radio[0].set_value("Timetable").run()
        assert not at.exception
