"""Goals meet the timetable (pace.py): capacity, budget, pace, debt, follow-through, competition,
negotiation and suggestions. The clock is pinned to Wednesday 11 Nov 2026, 10:00 (London)."""

import importlib
from datetime import date, datetime, timedelta

import pytest

NOW = datetime(2026, 11, 11, 10, 0)          # a Wednesday; November 2026 starts on a Sunday


@pytest.fixture
def pace(store, monkeypatch):
    monkeypatch.setattr(store, "local_now", lambda: NOW)
    monkeypatch.setattr(store, "local_today", lambda: NOW.date())
    from venato import pace as module
    return importlib.reload(module)


def block(store, day, start, end, label, cat, track="plan"):
    store.paint(str(day), track, store.slot_of(start), store.slot_of(end), {"label": label, "category_id": cat})
    if track == "actual":
        store.mark_confirmed(str(day))     # Actual counts on confirmed days only


def event(uid, day, start=None, end=None, title="Lecture"):
    return {"uid": uid, "date": str(day), "start": start, "end": end, "title": title, "location": None,
            "all_day": 0 if start else 1, "exact": f"{start}–{end}" if start else None}


# --- Phase 1: capacity and budget ---

def test_capacity_is_timetable_hours_minus_fixed_time(store, pace):
    store.add_goal("Study", "monthly", "2026-11-01", 20, "h", category_id="study")
    store.replace_outlook([event("thu", "2026-11-12", "09:00", "11:00", "Team meeting"),
                           event("sun", "2026-11-15", title="Trip")])
    block(store, "2026-11-13", "18:00", "20:00", "Gym", "exercise")           # fixed: serves no goal
    block(store, "2026-11-14", "09:00", "12:00", "Revision", "study")         # serves the goal: still free for goals
    cap = pace.week_capacity(NOW.date(), pace.Ctx(NOW))
    by_day = {d["date"]: d["hours"] for d in cap["days"]}
    assert by_day["2026-11-09"] == by_day["2026-11-10"] == 0                   # already over
    assert by_day["2026-11-11"] == 15                                          # 10:00 -> 01:00
    assert by_day["2026-11-12"] == 16 and by_day["2026-11-13"] == 16
    assert by_day["2026-11-14"] == 18
    assert by_day["2026-11-15"] == 18                                          # all-day events don't block...
    store.set_away("sun", True)                                                # ...unless you're away
    store.replace_outlook([event("thu", "2026-11-12", "09:00", "11:00", "Team meeting"),
                           event("sun", "2026-11-15", title="Trip")])           # and that survives a re-sync
    cap = pace.week_capacity(NOW.date(), pace.Ctx(NOW))
    assert {d["date"]: d["hours"] for d in cap["days"]}["2026-11-15"] == 0
    assert cap["hours"] == 15 + 16 + 16 + 18 and not cap["estimate"]


def test_calendar_events_in_a_goals_category_count_for_the_goal_not_against_capacity(store, pace):
    store.replace_outlook([event("lec", "2026-11-12", "09:00", "11:00", "Lecture")])   # Outlook category: Classes
    ctx = pace.Ctx(NOW)
    assert pace.week_capacity(NOW.date(), ctx)["days"][3]["hours"] == 16
    store.add_goal("Classes", "monthly", "2026-11-01", 30, "h", category_id="classes")
    ctx = pace.Ctx(NOW)
    assert pace.week_capacity(NOW.date(), ctx)["days"][3]["hours"] == 18
    w = pace.week_goals(NOW.date(), ctx)[0]
    assert w["planned"] == w["planned_future"] == 2


def test_detached_calendar_events_stay_fixed(store, pace):
    store.add_goal("Classes", "monthly", "2026-11-01", 30, "h", category_id="classes")
    store.replace_outlook([event("lec", "2026-11-12", "09:00", "11:00", "Lecture")])
    store.detach_outlook("lec")
    assert pace.week_capacity(NOW.date(), pace.Ctx(NOW))["days"][3]["hours"] == 16


def test_beyond_the_calendars_reach_capacity_is_an_estimate(store, pace):
    # a 2-hour lecture every Thursday for the 8 weeks the calendar reaches
    rows = [event(f"l{i}", date(2026, 11, 12) + timedelta(weeks=i), "09:00", "11:00") for i in range(8)]
    store.replace_outlook(rows)
    ctx = pace.Ctx(NOW)
    near = pace.week_capacity("2026-11-23", ctx)
    far = pace.week_capacity("2027-01-18", ctx)
    assert not near["estimate"] and far["estimate"]
    assert near["hours"] == 7 * 18 - 2
    assert {d["date"]: d["hours"] for d in far["days"]}["2027-01-21"] == 16  # Thursdays keep their average load
    assert "estimate" in pace.week_budget("2027-01-18", ctx)["text"]


def test_capacity_with_sunday_weeks_and_other_day_hours(store, pace):
    store.set_week_start("Sunday")
    store.save_settings(day_start=8, day_end=22)                              # 14-hour days
    cap = pace.week_capacity(NOW.date(), pace.Ctx(NOW))
    assert cap["week_start"] == date(2026, 11, 8)
    assert [d["hours"] for d in cap["days"]] == [0, 0, 0, 12, 14, 14, 14]    # Sun-Tue over; Wed from 10:00


def test_budget_text(store, pace):
    store.add_goal("Study", "monthly", "2026-11-01", 300, "h", category_id="study")
    b = pace.week_budget(NOW.date(), pace.Ctx(NOW))
    assert b["over"] and b["text"].startswith("Goals need ") and "you have 87 h free" in b["text"]


# --- Phase 2 / 3: pace and debt ---

def test_week_need_spreads_the_remainder_and_carries_debt(store, pace):
    g = store.add_goal("Study", "monthly", "2026-11-01", 30, "h", category_id="study")
    block(store, "2026-11-03", "09:00", "11:00", "Revision", "study", track="actual")      # 2 h last week
    ctx = pace.Ctx(NOW)
    need, baseline = pace.week_need(g, NOW.date(), ctx)
    assert baseline == pytest.approx(7)                                        # 30 h over 30 days
    assert need == pytest.approx(28 * 7 / 22)                                  # 28 h left over 22 days
    assert pace.debt_text(g, need, baseline) == "8.9 h this week (7 h + 1.9 h carried)"
    # a period that only covers part of a week (1 Nov is that week's Sunday)
    need, baseline = pace.week_need(g, "2026-10-28", ctx)
    assert baseline == pytest.approx(1) and need == pytest.approx(1)


def test_pace_states(store, pace):
    g = store.add_goal("Study", "monthly", "2026-11-01", 30, "h", category_id="study")
    ctx = pace.Ctx(NOW)
    assert pace.goal_pace(g, ctx)["state"] == "behind"                         # nothing planned
    for day in ("2026-11-12", "2026-11-13", "2026-11-14", "2026-11-15"):
        block(store, day, "09:00", "12:00", "Revision", "study")
    p = pace.goal_pace(store.get_goal(g["id"]), pace.Ctx(NOW))
    assert p["state"] == "on_track" and p["week"]["covered"] == 12
    # planned earlier this week: assumed done until the day is confirmed...
    block(store, "2026-11-10", "09:00", "11:00", "Revision", "study")
    p = pace.goal_pace(store.get_goal(g["id"]), pace.Ctx(NOW))
    assert p["state"] == "on_track" and p["week"]["assumed"] == 2 and p["week"]["done"] == 0
    # ...confirmed with the Actual missing: slipping
    store.mark_confirmed("2026-11-10")
    p = pace.goal_pace(store.get_goal(g["id"]), pace.Ctx(NOW))
    assert p["state"] == "slipping" and p["week"]["confirmed_days"] == 1
    # far more than the time left
    big = store.add_goal("Big", "monthly", "2026-11-01", 900, "h", category_id="work")
    assert pace.goal_pace(big, pace.Ctx(NOW))["state"] == "unreachable"


def test_projection_from_the_last_four_weeks(store, pace):
    g = store.add_goal("Study", "monthly", "2026-11-01", 30, "h", category_id="study")
    for i in range(4):          # 1 h a week of Actual
        block(store, date(2026, 10, 14) + timedelta(weeks=i), "09:00", "10:00", "Revision", "study", "actual")
    p = pace.goal_pace(store.get_goal(g["id"]), pace.Ctx(NOW))
    assert p["rate"] == pytest.approx(7)      # only those 4 days are confirmed: 1 h a confirmed day
    for i in range(1, 29):                    # every day of the last 4 weeks confirmed
        store.mark_confirmed(NOW.date() - timedelta(days=i))
    p = pace.goal_pace(store.get_goal(g["id"]), pace.Ctx(NOW))
    assert p["rate"] == pytest.approx(1)
    assert p["late"] > 0 and "days late at this rate" in p["line"]


def test_habit_and_hand_kept_goals_get_pace_in_their_unit(store, pace):
    store.add_habit("Gym")
    hid = store.find_habit("Gym")[0]
    g = store.add_goal("Gym", "monthly", "2026-11-01", 12, "sessions", habit_id=hid)
    with store.db() as conn:
        for d in ("2026-11-02", "2026-11-04"):
            store.set_habit_done(conn, hid, d, True)
    p = pace.goal_pace(store.get_goal(g["id"]), pace.Ctx(NOW))
    assert p["state"] == "behind" and p["expected"] == pytest.approx(12 * 10 / 30)
    assert "sessions this week" in p["line"]
    hard = store.add_goal("Run", "monthly", "2026-11-01", 25, "runs", habit_id=hid)
    assert pace.goal_pace(hard, pace.Ctx(NOW))["state"] == "unreachable"   # 23 to go, 20 days left
    books = store.add_goal("Books", "yearly", "2026-01-01", 10, "books")
    store.set_goal_progress(books["id"], 9)
    assert pace.goal_pace(store.get_goal(books["id"]), pace.Ctx(NOW))["state"] == "on_track"


# --- Phase 4: honest forecast ---

def test_follow_through_inflates_the_plan(store, pace):
    g = store.add_goal("Study", "monthly", "2026-11-01", 30, "h", category_id="study")
    ctx = pace.Ctx(NOW)
    assert pace.follow_through(g, ctx) is None                                 # no history
    for i in range(1, 4):       # 3 past weeks: planned 4 h, did 2 h
        monday = date(2026, 11, 9) - timedelta(weeks=i)
        block(store, monday, "09:00", "13:00", "Revision", "study")
        block(store, monday, "09:00", "11:00", "Revision", "study", "actual")
    ctx = pace.Ctx(NOW)
    assert pace.follow_through(g, ctx) == pytest.approx(0.5)
    w = pace.week_goals(NOW.date(), ctx)[0]
    assert w["factor"] == pytest.approx(2) and w["want"] == pytest.approx(2 * w["need"])
    assert "plan" in pace.goal_pace(store.get_goal(g["id"]), ctx)["line"]
    store.save_settings(goal_inflate=False)
    w = pace.week_goals(NOW.date(), pace.Ctx(NOW))[0]
    assert w["factor"] == 1 and w["want"] == pytest.approx(w["need"])


def test_follow_through_is_clamped(store, pace):
    g = store.add_goal("Study", "monthly", "2026-11-01", 30, "h", category_id="study")
    for i in range(1, 4):       # planned 4 h, did nothing
        block(store, date(2026, 11, 9) - timedelta(weeks=i), "09:00", "13:00", "Revision", "study")
    assert pace.follow_through(g, pace.Ctx(NOW)) is None             # unconfirmed days: nothing to go on
    for i in range(1, 4):
        store.mark_confirmed(date(2026, 11, 9) - timedelta(weeks=i))
    assert pace.follow_through(g, pace.Ctx(NOW)) == 0.3


# --- Phase 5: competition ---

def test_over_budget_goals_are_served_top_down(store, pace):
    store.replace_outlook([event(f"x{i}", date(2026, 11, 11) + timedelta(days=i), "07:00", "01:00", "Busy")
                           for i in range(1, 5)])                              # Thu-Sun fully booked
    a = store.add_goal("A", "monthly", "2026-11-01", 60, "h", category_id="study")
    b = store.add_goal("B", "monthly", "2026-11-01", 60, "h", category_id="work")
    rows = pace.week_goals(NOW.date(), pace.Ctx(NOW))
    assert [w["goal"]["title"] for w in rows] == ["A", "B"]
    assert rows[0]["alloc"] == pytest.approx(min(15, rows[0]["want"]))
    assert rows[1]["budget_short"] > 0
    store.reorder_goals([b["id"], a["id"]])                                   # B first now
    assert [w["goal"]["title"] for w in pace.week_goals(NOW.date(), pace.Ctx(NOW))] == ["B", "A"]
    store.set_goal_week_hours(NOW.date(), {a["id"]: 10, b["id"]: 5})          # the user's own split
    rows = {w["goal"]["title"]: w for w in pace.week_goals(NOW.date(), pace.Ctx(NOW))}
    assert (rows["A"]["want"], rows["B"]["want"]) == (10, 5)
    store.delete_goal(a["id"])                                                # cascades
    assert store.goal_week_hours(NOW.date()) == {b["id"]: 5}


# --- Phase 6: negotiation ---

def test_negotiation_offers(store, pace):
    store.replace_outlook([event(f"x{i}", date(2026, 11, 11) + timedelta(days=i), "07:00", "01:00", "Busy")
                           for i in range(1, 21)])                             # booked to the end of the month
    g = store.add_goal("Study", "monthly", "2026-11-01", 40, "h", category_id="study")
    low = store.add_goal("Guitar", "monthly", "2026-11-01", 10, "h", category_id="rest")
    n = pace.negotiation(g, pace.Ctx(NOW))
    kinds = [o["kind"] for o in n["offers"]]
    assert kinds == ["lower", "extend", "take"]
    assert n["offers"][0]["target"] == 15                                      # today's 15 h is all there is
    assert n["offers"][1]["due"] > "2026-11-30" and "move the deadline to" in n["offers"][1]["text"]
    assert n["offers"][2]["other"] == low["id"]
    assert pace.negotiation(low, pace.Ctx(NOW)) is not None                   # it can't get any time either


# --- Phase 7: suggestions ---

def test_suggested_goals(store, pace):
    store.save_category("music", "Music", "#123456", "Life")
    for i in range(1, 4):
        monday = date(2026, 11, 9) - timedelta(weeks=i)
        block(store, monday, "18:00", "20:30", "Guitar", "music", "actual")
    found = pace.suggestions(pace.Ctx(NOW))
    assert [s["text"] for s in found] == ["1.9 h/week of Guitar. Make it a goal?"]
    assert pace.suggested_target(found[0]["per_week"], NOW.date()) == 8
    pace.dismiss_suggestion(found[0])
    assert pace.suggestions(pace.Ctx(NOW)) == []


def test_no_suggestion_when_a_goal_counts_it(store, pace):
    for i in range(1, 4):
        block(store, date(2026, 11, 9) - timedelta(weeks=i), "09:00", "12:00", "Revision", "study", "actual")
    assert pace.suggestions(pace.Ctx(NOW))
    store.add_goal("Study", "monthly", "2026-11-01", 20, "h", category_id="study")
    assert pace.suggestions(pace.Ctx(NOW)) == []


# --- The mid-week nudge ---

def test_nudge_once_a_week_per_goal_from_midweek(store, pace):
    g = store.add_goal("Study", "monthly", "2026-11-01", 30, "h", category_id="study")
    assert pace.nudges(datetime(2026, 11, 10, 18, 0)) == []                    # Tuesday: too early
    assert pace.nudges(datetime(2026, 11, 11, 9, 0)) == []                     # Wednesday morning: too early
    out = pace.nudges(NOW.replace(hour=13))
    assert [o[0] for o in out] == [g["id"]] and "short this week" in out[0][2]
    pace.mark_nudged(g["id"], out[0][1])
    assert pace.nudges(NOW.replace(hour=15)) == []


# --- Claude's tools (and the buttons that call the same functions) ---

@pytest.fixture
def tools(store, pace):
    from venato import tools as module
    module = importlib.reload(module)
    module._now = lambda: NOW
    return module


def test_plan_goals_fills_only_free_gaps_in_priority_order(store, pace, tools):
    store.replace_outlook([event("thu", "2026-11-12", "09:00", "11:00", "Team meeting")])
    block(store, "2026-11-13", "09:00", "21:00", "Work", "work")             # Friday's daytime is fixed
    a = store.add_goal("Study", "monthly", "2026-11-01", 30, "h", category_id="study", label="Revision")
    b = store.add_goal("Run", "monthly", "2026-11-01", 8, "h", category_id="exercise")
    r = tools.plan_goals()
    assert r.pending and "Revision for Study" in r.pending.summary and "Run for Run" in r.pending.summary
    assert store.blocks_between("2026-11-11", "2026-11-15", "plan")[0]["label"] == "Work"   # nothing yet
    r.pending.run()
    rows = {w["goal"]["id"]: w for w in pace.week_goals(NOW.date(), pace.Ctx(NOW))}
    assert rows[a["id"]]["short"] < 0.5 and rows[b["id"]]["short"] < 0.5
    plan = store.blocks_between("2026-11-11", "2026-11-15", "plan")
    assert [p for p in plan if p["label"] == "Work"][0]["start"] == "09:00"            # untouched
    assert not any(p["date"] == "2026-11-12" and "09:00" <= p["start"] < "11:00" for p in plan)
    assert store.outlook_between("2026-11-12", "2026-11-12")                           # the event is still there
    assert not any(p["date"] < "2026-11-11" or (p["date"] == "2026-11-11" and p["start"] < "10:00") for p in plan)
    assert tools.plan_goals().text.startswith("Nothing to plan")


def test_goal_pace_and_week_budget_tools(store, tools):
    store.add_goal("Study", "monthly", "2026-11-01", 30, "h", category_id="study")
    store.add_goal("Books", "yearly", "2026-01-01", 12, "books")
    text = tools.goal_pace().text
    assert "Study (0/30 h): Behind" in text and "Books" in text
    assert "Study" in tools.goal_pace("study").text and "Books" not in tools.goal_pace("study").text
    text = tools.week_budget().text
    assert "Goals need" in text and "- Study: 0/" in text


def test_resolve_goal_moves_the_deadline(store, pace, tools):
    store.replace_outlook([event(f"x{i}", date(2026, 11, 11) + timedelta(days=i), "07:00", "01:00", "Busy")
                           for i in range(1, 21)])
    g = store.add_goal("Study", "monthly", "2026-11-01", 40, "h", category_id="study", label="Revision")
    due = pace.negotiation(g, pace.Ctx(NOW))["offers"][1]["due"]
    r = tools.resolve_goal(g["id"], "extend")
    assert r.pending
    r.pending.run()
    after = store.get_goal(g["id"])
    assert (after["target"], after["due"]) == (40, due)


def test_assistant_has_the_goal_tools_and_a_snapshot_line(store, pace):
    from venato import assistant
    assistant = importlib.reload(assistant)
    names = [spec[0] for spec in assistant.TOOL_SPECS]
    assert {"goal_pace", "week_budget", "plan_goals"} <= set(names)
    store.add_goal("Study", "monthly", "2026-11-01", 30, "h", category_id="study")
    assert "Goals this week:\nGoals need" in assistant.context(NOW)


def test_a_day_can_be_marked_away_without_a_calendar_event(store, pace):
    store.set_away_day("2026-11-14", True)
    days = {d["date"]: d for d in pace.week_capacity(NOW.date(), pace.Ctx(NOW))["days"]}
    assert days["2026-11-14"]["hours"] == 0 and days["2026-11-14"]["away"]
    store.set_away_day("2026-11-14", False)
    assert pace.week_capacity(NOW.date(), pace.Ctx(NOW))["days"][5]["hours"] == 18


def test_sleep_is_never_suggested(store, pace):
    for i in range(1, 4):
        block(store, date(2026, 11, 9) - timedelta(weeks=i), "23:00", "01:00", "Sleep", "sleep", "actual")
        block(store, date(2026, 11, 10) - timedelta(weeks=i), "23:00", "01:00", "Sleep", "sleep", "actual")
    assert pace.suggestions(pace.Ctx(NOW)) == []


def test_history_and_chart_count_confirmed_days(store, pace):
    from venato.ui import goal_chart
    g = store.add_goal("Study", "monthly", "2026-11-01", 30, "h", category_id="study")
    block(store, "2026-11-02", "09:00", "11:00", "Revision", "study", "actual")      # confirmed (the helper)
    store.paint("2026-11-03", "actual", store.slot_of("09:00"), store.slot_of("12:00"),
                {"label": "Revision", "category_id": "study"})                         # not confirmed: not counted
    ctx = pace.Ctx(NOW)
    hist = pace.history(store.get_goal(g["id"]), ctx)
    assert hist[0] == (date(2026, 10, 31), 0) and hist[-1] == (NOW.date(), 2)
    assert dict(hist)[date(2026, 11, 3)] == 2
    p = pace.goal_pace(store.get_goal(g["id"]), ctx)
    from urllib.parse import unquote
    svg = unquote(goal_chart.chart(p, ctx))
    assert svg.count("<polyline") == 1 and 'stroke-dasharray="5 4"' in svg and 'role="img"' in svg
    assert "2 h of 30 h by" in goal_chart.describe(p, ctx) and "confirmed days this week" in goal_chart.describe(p, ctx)
    assert pace.history(store.add_goal("Books", "yearly", "2026-01-01", 10, "books"), ctx) is None
