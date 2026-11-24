"""Goals meet the timetable, on screen (AppTest): the Timetable's goal chips and buttons, the Goals page's
pace lines, budget, offers and suggestions, Home's marker, the weekly review and the nudge.
The real clock is used here (pace.py's own tests pin it), so the data is built around today."""

from datetime import datetime, timedelta
from pathlib import Path

from streamlit.testing.v1 import AppTest
from nav_helpers import goto, page_names

APP = str(Path(__file__).resolve().parents[1] / "app.py")


def app():
    return AppTest.from_file(APP, default_timeout=60).run()


def has_key(at, key):
    return any(b.key == key for b in at.button)


def open_page(at, name):
    goto(at, name)
    assert not at.exception, at.exception


def test_timetable_planner_panel_and_suggestions(store):
    g = store.add_goal("Revision", "monthly", store.local_today(), 200, "h", category_id="study")
    at = app()
    open_page(at, "Timetable")
    assert at.button(key=f"tt_pick_goal_{g['id']}").label.startswith("Revision")   # the side panel lists it
    assert not has_key(at, "tt_plan_goals")                                       # "Plan this week" is gone
    assert not any(b.key and b.key.startswith("tt_goal_") for b in at.button)      # the old chip strip is gone
    from venato.ui import goal_time
    sugg = goal_time.suggestions_for(store.week_start_of(store.local_today()))
    if sugg:                                     # (none late on the week's last day: nothing left to suggest in)
        assert any("suggested sitting" in m.value for m in at.markdown)
        at.button(key="tt_sugg_dismiss").click().run()
        assert goal_time.suggestions_for(store.week_start_of(store.local_today())) == []
    at.toggle(key="tt_show_sugg").set_value(False).run()
    assert not goal_time.show_suggestions()


def test_goals_page_pace_budget_and_ranking(store):
    today = store.local_today()
    a = store.add_goal("Revision", "monthly", today, 20, "h", category_id="study")
    b = store.add_goal("Gym", "monthly", today, 12, "sessions")
    at = app()
    open_page(at, "Goals")
    heads = " ".join(s.value for s in at.subheader)
    assert "Where this week's" not in heads and "This week's time" not in heads  # no side panel
    html = " ".join(h.proto.body for h in at.get("html"))
    assert html.count('class="gc-legend"') == 1                                   # one legend for every chart
    assert 'alt="Revision: 0 h of 20 h by' in html                                 # each chart says its numbers
    assert "Unclaimed" not in html
    assert any("This week" in c.value for c in at.caption)                        # the goal's own week numbers
    at.button(key=f"edit_{b['id']}_up").click().run()            # Gym first now
    assert [g["title"] for g in store.goals_in("monthly", today)] == ["Gym", "Revision"]
    assert a["id"]


def test_home_bar_has_a_should_be_here_marker(store):
    today = store.local_today()
    store.add_goal("Read", "yearly", today, 12, "books")
    at = app()
    html = " ".join(h.proto.body for h in at.get("html"))
    if today.timetuple().tm_yday > 1:
        assert "hg-mark" in html and "by today" in html


def test_review_has_goal_pace(store):
    from venato import review
    today = store.local_today()
    store.add_goal("Revision", "monthly", today, 20, "h", category_id="study")
    s = review.summary(store.week_start_of(today))
    assert s["goals"] and s["goals"][0]["text"].startswith("Revision: 0 h of ")
    assert "Goal pace: Revision" in review.as_text(s)


def test_notification_nudges_once(store, monkeypatch):
    from venato import notify, system
    sent_out = []
    monkeypatch.setattr(system, "notify", lambda title, body: sent_out.append(title))
    today = store.local_today()
    store.add_goal("Revision", "monthly", today, 300, "h", category_id="study")
    first = store.week_start_of(today)
    now = datetime.combine(first + timedelta(days=3), datetime.min.time()).replace(hour=13)
    if store.end_of_period("monthly", store.start_of_period("monthly", today)) < now.date():
        return                                                   # (late in the month: the period would be over)
    monkeypatch.setattr(store, "local_now", lambda: now)
    monkeypatch.setattr(store, "local_today", lambda: now.date())
    sent = set()
    notify.check(sent, now)
    notify.check(set(), now)                                     # a restart: still once a week
    nudges = [t for t in sent_out if "short this week" in t]
    assert len(nudges) == 1 and nudges[0].startswith("Revision: ")


def test_suggested_sittings_are_free_time_from_now_on(store, monkeypatch):
    from venato import pace, tools
    from venato.ui import goal_time, timetable
    now = datetime(2026, 11, 11, 10, 0)                         # Wednesday
    monkeypatch.setattr(store, "local_now", lambda: now)
    monkeypatch.setattr(tools, "_now", lambda: now)
    store.add_goal("Revision", "monthly", "2026-11-01", 60, "h", category_id="study")
    store.paint("2026-11-12", "plan", store.slot_of("09:00"), store.slot_of("17:00"), {"label": "Work", "category_id": "work"})
    sugg = goal_time.suggestions_for(store.week_start_of(now.date()), pace.Ctx(now))
    assert sugg and all(x["date"] >= "2026-11-11" for x in sugg)
    assert not [x for x in sugg if x["date"] == "2026-11-11" and x["start"] < "10:00"]           # never in the past
    assert not [x for x in sugg if x["date"] == "2026-11-12" and "09:00" <= x["start"] < "17:00"]  # never over fixed time
    # Clicking one adds just that sitting; the same op twice (a resend) adds nothing more.
    x = sugg[0]
    op = {"kind": "add_suggestion", "date": x["date"], "start": x["start"], "end": x["end"],
          "block": {"label": x["label"], "categoryId": x["categoryId"]}, "newId": "s1"}
    timetable.apply_grid_op(op)
    timetable.apply_grid_op({**op, "newId": "s2", "block": {"label": "Other", "categoryId": "work"}})
    got = [b for b in store.blocks_between(x["date"], x["date"], store.live_track(x["date"])) if b["start"] == x["start"]]
    assert [(b["id"], b["label"]) for b in got] == [("s1", "Revision")]
    # "Add all to Plan" (plan_goals) adds the same sittings that are left.
    left = goal_time.suggestions_for(store.week_start_of(now.date()), pace.Ctx(now))
    assert x["id"] not in {y["id"] for y in left}


def test_home_needs_you_lists_only_goals_that_need_something(store):
    today = store.local_today()
    behind = store.add_goal("Revision", "monthly", today, 200, "h", category_id="study")
    store.add_goal("Books", "yearly", today, 1, "books")
    store.set_goal_progress(store.goals_in("yearly", today)[0]["id"], 1)          # done: on track
    at = app()
    assert not at.exception
    text = " ".join(m.value for m in at.markdown)
    assert "**Needs you**" in text and "Revision" in text
    assert "Books" not in text                                                     # on track: only on the Goals page
    assert not has_key(at, "home_plan_goals")                                     # the tile: one line a goal
    at.button(key="open_tile_needs_you").click().run()                             # tap it: everything, in a dialog
    assert not at.exception
    html = " ".join(h.proto.body for h in at.get("html"))
    assert 'class="hg-bar"' in html and "/ 200 h by " in html                      # its bar and "0 / 200 h by …"
    assert "Agenda" not in html                                                    # no Agenda
    assert at.button(key="home_plan_goals")
    assert behind["id"]


def test_past_week_scorecard(store, monkeypatch):
    from venato import pace
    from venato.ui import goal_time
    now = datetime(2026, 11, 18, 10, 0)                              # Wednesday; last week is over
    g = store.add_goal("Study", "monthly", "2026-11-01", 30, "h", category_id="study")
    store.paint("2026-11-10", "actual", store.slot_of("09:00"), store.slot_of("11:00"), {"label": "Study", "category_id": "study"})
    store.mark_confirmed("2026-11-10")
    w = [x for x in pace.week_goals("2026-11-09", pace.Ctx(now)) if x["goal"]["id"] == g["id"]][0]
    assert w["over"] and w["done"] == 2
    short = goal_time._score(w, all_confirmed=False)
    assert "done 2 of" in short and "short so far" in short and "missed" not in short    # unconfirmed days: not "missed"
    assert "✕ missed by" in goal_time._score(w, all_confirmed=True)
    assert "✓ hit" in goal_time._score({**w, "need": 2}, all_confirmed=True)


def test_linked_habit_updates_goal(store):
    """Ticking a habit on Home that a goal counts: the goal's bar moves in the same run (the habit
    fragment reruns the whole app), as it does on the browser."""
    import fragment_run
    today = store.local_today()
    store.add_habit("Gym")
    hid = store.find_habit("gym")[0]
    store.add_goal("Gym", "monthly", today, 12, "sessions", habit_id=hid)
    store.save_settings(home=[{"w": "goals", "size": "wide"}, {"w": "habits", "size": "m"}])
    html = lambda at: " ".join(h.proto.body for h in at.get("html"))
    with fragment_run.recording():
        at = app()
        assert "0 / 12 sessions" in html(at)
        draws = at.session_state["home_draws"]
        fragment_run.click(at, at.checkbox(key=f"home_habit_{hid}_{today}").check())
    assert not at.exception
    assert at.session_state["home_draws"] == draws + 1
    assert "1 / 12 sessions" in html(at)


def test_a_new_hours_goal_needs_a_plan_it_is_not_behind(store):
    from datetime import timedelta
    today = store.local_today()
    store.add_goal("Revision", None, today, 40, "h", category_id="study", due=today + timedelta(days=40))
    store.add_goal("Old plan", None, today - timedelta(days=10), 40, "h", category_id="work",
                   due=today + timedelta(days=30))
    at = app()
    assert not at.exception
    text = " ".join(m.value for m in at.markdown)
    rev = next(m.value for m in at.markdown if "Revision" in m.value and "badge" in m.value)
    old = next(m.value for m in at.markdown if "Old plan" in m.value and "badge" in m.value)
    assert "Needs a plan" in rev and "Behind" not in rev
    assert "Behind" in old                                                         # a week in: honestly behind
    assert "float:right" not in text                                               # "N h to plan" sits beside, not over, the bar
    assert any("h to plan" in m.value for m in at.markdown)


def test_a_plan_goal_shows_once_in_needs_you(store):
    from datetime import timedelta
    today = store.local_today()
    did = store.add_deadline("Lab report", today + timedelta(days=3))
    store.plan_deadline(did, "study", total=8, today=today)
    at = app()
    assert not at.exception
    rows = [m.value for m in at.markdown if "Lab report" in m.value]
    assert len(rows) == 1 and "event" in rows[0]                  # the deadline row, not also a goal row
