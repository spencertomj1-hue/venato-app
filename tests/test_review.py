"""Weekly review: when it's due, what it adds up, the pop-up, and the history on Stats."""

import importlib
from datetime import date, datetime, timedelta
from pathlib import Path

import pytest
from streamlit.testing.v1 import AppTest

import fragment_run
from nav_helpers import goto, page_names

APP = str(Path(__file__).resolve().parents[1] / "app.py")


@pytest.fixture
def review(store):
    from venato import review as module
    return importlib.reload(module)


def test_when_its_due(review, store):
    sun = datetime(2026, 11, 1, 18, 59)                       # Sunday 1 Nov, just before 7pm
    assert review.due_week(sun) == date(2026, 10, 19)         # still last week's
    assert review.due_week(sun.replace(hour=19)) == date(2026, 10, 26)
    assert review.due_week(datetime(2026, 11, 3, 9)) == date(2026, 10, 26)   # Tuesday: still that one
    store.set_week_start("Sunday")
    assert review.due_week(datetime(2026, 11, 1, 20)) == date(2026, 10, 25)  # Sun 25 - Sat 31 Oct


def test_summary_numbers(review, store, monkeypatch):
    from venato import tools
    tools = importlib.reload(tools)
    monkeypatch.setattr(store, "local_now", lambda: datetime(2026, 10, 26, 12, 0))         # Monday: planning Tuesday
    tools.add_block("2026-10-27", "plan", "09:00", "11:00", "Revision", category="Study")
    monkeypatch.setattr(store, "local_now", lambda: datetime(2026, 10, 27, 20, 0))         # Tuesday: Plan locked
    # The Plan was copied into the Actual when the day started, so this overwrites "Revision": confirm it.
    tools.add_block("2026-10-27", "actual", "10:00", "11:00", "Scrolling", category="Distracted").pending.run()
    store.confirm_day("2026-10-27")
    with store.db() as conn:
        store.save_entry(conn, "2026-10-27", "Good day", 7.0, 2.0)
        store.save_entry(conn, "2026-10-20", None, 5.0)    # the week before
    store.set_tracking(sleep=True, water=False)
    store.add_habit("Gym", per_week=2)
    gym = store.find_habit("Gym")[0]
    with store.db() as conn:
        for d in ("2026-10-26", "2026-10-29"):
            store.set_habit_done(conn, gym, d, True)
    store.add_deadline("Essay", "2026-10-30")
    s = review.summary(date(2026, 10, 26))
    assert (s["planned_hours"], s["actual_hours"], s["followed_pct"]) == (2.0, 2.0, 50)
    assert {t["category"]: (t["plan"], t["actual"]) for t in s["time"]} == {"Study": (2.0, 1.0), "Distracted": (0.0, 1.0)}
    assert s["log"] == {"sleep": {"now": 7.0, "before": 5.0}} and s["days_logged"] == 1
    assert s["habits"] == [{"name": "Gym", "ticks": 2, "target": 2, "hit": True}]
    assert [d["title"] for d in s["deadlines"]["missed"]] == ["Essay"] and s["has_data"]
    text = review.as_text(s)
    assert "50% of the Plan followed" in text and "Average sleep: 7.0 (week before 5.0)" in text and "mood" not in text


def test_popup_until_done_and_history(store, monkeypatch):
    from venato import review, tools
    importlib.reload(tools)
    week = store.week_start_of(store.local_today())
    tools.add_block(week.isoformat(), "actual", "09:00", "10:00", "Gym", category="Exercise")
    monkeypatch.setattr(review, "due_week", lambda now=None: week)
    def shown(at):
        return any(b.key == "review_popup_plan" for b in at.button)
    at = AppTest.from_file(APP, default_timeout=60).run()
    assert not at.exception and shown(at)
    assert not store.get_review(week).get("seen_at")                           # closed by accident: not done with
    with fragment_run.recording():                                             # the dialog is a fragment
        at = AppTest.from_file(APP, default_timeout=60).run()                  # so it comes back next time
        assert shown(at)
        fragment_run.click(at, at.button(key="review_popup_done").click())
    assert not at.exception and store.get_review(week).get("seen_at") and review.should_show() is None
    at = AppTest.from_file(APP, default_timeout=60).run()                      # opened again: not shown again
    assert not shown(at)
    goto(at, "Review")
    assert not at.exception and any(b.key == f"review_{week.isoformat()}_plan" for b in at.button)


def test_last_week_promise_deltas_and_gaps(review, store, monkeypatch):
    from venato import tools
    tools = importlib.reload(tools)
    monkeypatch.setattr(store, "local_now", lambda: datetime(2026, 10, 19, 8, 0))
    for day in ("2026-10-20", "2026-10-27"):                                  # Tuesdays, a week apart
        tools.add_block(day, "plan", "09:00", "13:00", "Revision", category="Study")
    monkeypatch.setattr(store, "local_now", lambda: datetime(2026, 11, 2, 20, 0))
    store.confirm_day("2026-10-20")                                           # the week before: all 4 h done
    tools.add_block("2026-10-27", "actual", "10:00", "13:00", "Scrolling", category="Distracted").pending.run()
    store.confirm_day("2026-10-27")                                           # this week: 1 h of 4
    store.save_review(date(2026, 10, 19), to_change="Phone in the other room")
    s = review.summary(date(2026, 10, 26))
    assert (s["followed_pct"], s["before"]["followed_pct"], s["before"]["actual_hours"]) == (25, 100, 4.0)
    assert [g["category"] for g in review.gaps(s["time"])] == ["Study"]
    assert s["headline"].startswith("Rough week: 25% of the plan followed, down from 100%")
    assert "Study fell short (1 of 4 h)" in s["headline"]
    assert s["promise"] == "Phone in the other room"
    store.save_review(date(2026, 10, 26), kept="partly")
    text = review.as_text(review.summary(date(2026, 10, 26)))
    assert "they'd do differently: Phone in the other room (did they? partly)" in text
    trend = review.trend(date(2026, 10, 26), weeks=2)
    assert [(t["followed_pct"], t["actual_hours"]) for t in trend] == [(100, 4.0), (25, 4.0)]


def test_unconfirmed_days(review, store, monkeypatch):
    from venato import tools
    tools = importlib.reload(tools)
    monkeypatch.setattr(store, "local_now", lambda: datetime(2026, 10, 26, 8, 0))
    tools.add_block("2026-10-27", "plan", "09:00", "10:00", "Revision", category="Study")
    tools.add_block("2026-10-28", "plan", "09:00", "10:00", "Revision", category="Study")
    monkeypatch.setattr(store, "local_now", lambda: datetime(2026, 10, 28, 9, 30))   # Wednesday's isn't over
    s = review.summary(date(2026, 10, 26))
    assert s["unconfirmed"] == ["2026-10-27"] and s["followed_pct"] is None
    assert "No days confirmed" in s["headline"]


def test_review_page_draws_everything(store, monkeypatch):
    from venato import review, tools
    importlib.reload(tools)
    today = store.local_today()
    week = store.week_start_of(today)
    for w in (week - timedelta(days=14), week - timedelta(days=7)):
        day = (w + timedelta(days=1)).isoformat()
        tools.add_block(day, "actual", "09:00", "10:00", "Gym", category="Exercise")
        store.confirm_day(day)
    store.save_review(week - timedelta(days=7), to_change="Sleep earlier")
    monkeypatch.setattr(review, "should_show", lambda now=None: None)
    at = AppTest.from_file(APP, default_timeout=60).run()
    goto(at, "Review")
    assert not at.exception
    assert any("Sleep earlier" in m.value for m in at.markdown)
    assert at.button(key="rv_next").disabled                                   # can't go past this week
    at.button(key="rv_prev").click().run()                                     # the week before
    assert not at.exception and at.session_state["rv_week"] == week - timedelta(days=7)
    assert any(b.key == f"review_{(week - timedelta(days=7)).isoformat()}_plan" for b in at.button)
    at.button(key=f"review_{(week - timedelta(days=7)).isoformat()}_plan").click().run()   # Plan next week
    assert not at.exception and at.session_state["page"] == "Timetable" and at.session_state["tt_day"] == week
    goto(at, "Review")
    assert at.session_state["rv_week"] == week - timedelta(days=7)            # still that week
    at.segmented_control(key="rv_view_w").set_value("Trends").run()
    assert not at.exception and any(s.value.startswith("Last 8 weeks") for s in at.subheader)
    goto(at, "Home")
    goto(at, "Review")
    assert at.session_state["rv_view"] == "Trends"                            # the choice is remembered


def test_future_plans_dont_count(review, store, monkeypatch):
    from datetime import datetime
    from venato import tools
    tools = importlib.reload(tools)
    monkeypatch.setattr(store, "local_now", lambda: datetime(2026, 10, 26, 12, 0))
    tools.add_block("2026-10-27", "plan", "09:00", "10:00", "Revision", category="Study")
    tools.add_block("2026-10-30", "plan", "09:00", "11:00", "Revision", category="Study")    # Friday: later on
    monkeypatch.setattr(store, "local_now", lambda: datetime(2026, 10, 28, 12, 0))         # it's Wednesday
    store.confirm_day("2026-10-27")                                                          # it went as planned
    s = review.summary(date(2026, 10, 26))
    assert (s["planned_hours"], s["followed_pct"]) == (1.0, 100)


def test_next_week_numbers(review):
    goals = [{"title": "Study", "state": "behind", "need": 12.0, "booked": 8.0},
             {"title": "Gym", "state": "on_track", "need": 3.0, "booked": 3.0},          # booked: not listed
             {"title": "Essay", "state": "on_track", "need": 2.0, "booked": 1.9},        # within tolerance
             {"title": "Spanish", "state": "unreachable", "need": 41.0, "booked": 2.0},
             {"title": "Old", "state": "done", "need": 5.0, "booked": 0.0}]
    n = review.next_week_numbers(48.0, 32.0, goals)
    assert (n["planned"], n["this_planned"], round(n["frac"], 3)) == (32.0, 48.0, 0.667)
    assert [g["title"] for g in n["short"]] == ["Spanish", "Study"]
    assert n["short"][0]["text"] == "can't be reached · move the date?"
    assert n["short"][1]["text"] == "needs 12 h · 8 h booked"
    assert review.next_week_numbers(0, 5.0, [])["frac"] is None
    assert review.next_week_numbers(2.0, 5.0, [])["frac"] == 1.0


def test_next_week_from_the_timetable(review, store, monkeypatch):
    from venato import tools
    tools = importlib.reload(tools)
    monkeypatch.setattr(store, "local_now", lambda: datetime(2026, 10, 26, 8, 0))          # planned on Monday
    tools.add_block("2026-10-27", "plan", "09:00", "13:00", "Revision", category="Study")   # this week: 4 h
    tools.add_block("2026-11-03", "plan", "09:00", "10:00", "Revision", category="Study")   # next week: 1 h
    monkeypatch.setattr(store, "local_now", lambda: datetime(2026, 11, 1, 20, 0))          # Sunday evening
    store.add_goal("Study", "monthly", "2026-11-01", 20, "h", category_id="study")
    n = review.next_week(date(2026, 10, 26))
    assert (n["planned"], n["this_planned"]) == (1.0, 4.0)
    [g] = n["short"]
    assert g["title"] == "Study" and g["booked"] == 1.0 and g["need"] > 1.0


def test_verdict_words(review):
    assert review.verdict(None) == "No verdict yet"
    assert review.verdict(85) == "Strong week" and review.verdict(60, complete=False) == "Solid week so far"
    assert review.verdict(45) == "Patchy week" and review.verdict(10) == "Rough week"


def _week_with_a_gap(store, monkeypatch):
    """Last week: Tuesday's 4 h of Study all done. This week: Tuesday's 4 h of Study, 1 h done (25%),
    Wednesday planned but not confirmed. It's Thursday morning."""
    from venato import tools
    tools = importlib.reload(tools)
    monkeypatch.setattr(store, "local_now", lambda: datetime(2026, 10, 19, 8, 0))
    for day in ("2026-10-20", "2026-10-27", "2026-10-28"):
        tools.add_block(day, "plan", "09:00", "13:00", "Revision", category="Study")
    monkeypatch.setattr(store, "local_now", lambda: datetime(2026, 10, 29, 9, 0))
    monkeypatch.setattr(store, "local_today", lambda: date(2026, 10, 29))
    store.confirm_day("2026-10-20")
    tools.add_block("2026-10-27", "actual", "10:00", "13:00", "Scrolling", category="Distracted").pending.run()
    store.confirm_day("2026-10-27")


def test_home_tile_numbers(review, store, monkeypatch):
    _week_with_a_gap(store, monkeypatch)
    t = review.tile(trend_weeks=2)
    assert t["first"] == date(2026, 10, 26) and not t["complete"]
    assert (t["pct"], t["before"], t["verdict"]) == (25, 100, "Rough week so far")
    assert t["sentence"].startswith("25% of the plan followed, down from 100%")       # the headline after the verdict
    assert t["short"]["category"] == "Study" and t["to_confirm"] == ["2026-10-28"]
    assert t["days"][:3] == [None, 25, None] and (t["planned"], t["done"]) == (4.0, 4.0)
    assert t["trend"] == [100, 25]
    from venato import tile_status
    assert tile_status.review() == "Rough week so far"                                 # Small: the verdict
    assert tile_status.review(size="wide") == "4 of 4 h"                               # bigger: the hours


def test_home_tile_shows_last_week_until_reviewed(review, store, monkeypatch):
    _week_with_a_gap(store, monkeypatch)
    monkeypatch.setattr(store, "local_now", lambda: datetime(2026, 11, 2, 9, 0))      # Monday: nothing confirmed yet
    monkeypatch.setattr(store, "local_today", lambda: date(2026, 11, 2))
    t = review.tile()
    assert t["first"] == date(2026, 10, 26) and t["complete"] and t["verdict"] == "Rough week"
    store.save_review(date(2026, 10, 26), seen=True)
    t = review.tile()
    assert t["first"] == date(2026, 11, 2) and t["pct"] is None and t["verdict"] == "No verdict yet"


@pytest.mark.parametrize("size", ["small", "wide", "large"])
def test_home_tile_draws_each_size(store, monkeypatch, size):
    _week_with_a_gap(store, monkeypatch)
    store.save_settings(home=[{"w": "review", "size": size}])
    at = AppTest.from_file(APP, default_timeout=60).run()
    assert not at.exception
    page = " ".join(h.proto.body for h in at.get("html"))
    assert 'class="vn-rv-tile"' in page and "25<small>%</small>" in page and "1 day to confirm" in page
    assert ("dashed line is 100%" in page) == (size != "small")                       # a bar a day from Wide up
    assert ("Plan vs done" in page) == (size == "large")
    assert ("Rough week so far.</b>" in page) == (size != "small")                     # the verdict in words
    head = [c.value for c in at.caption]
    assert ("Rough week so far" in head) == (size == "small")
