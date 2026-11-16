"""Goals meet the timetable, on screen (AppTest): the Timetable's goal chips and buttons, the Goals page's
pace lines, budget, offers and suggestions, Home's marker, the weekly review and the nudge.
The real clock is used here (pace.py's own tests pin it), so the data is built around today."""

from datetime import datetime, timedelta
from pathlib import Path

from streamlit.testing.v1 import AppTest

APP = str(Path(__file__).resolve().parents[1] / "app.py")


def app():
    return AppTest.from_file(APP, default_timeout=60).run()


def open_page(at, name):
    at.sidebar.radio[0].set_value(name).run()
    assert not at.exception, at.exception


def test_timetable_shows_a_chip_per_hours_goal(store):
    g = store.add_goal("Revision", "monthly", store.local_today(), 200, "h", category_id="study")
    at = app()
    open_page(at, "Timetable")
    chip = at.button(key=f"tt_goal_{g['id']}")
    assert chip.label.startswith(":orange[Revision 0/")          # short: amber, with a warning icon
    assert any("Goals need" in m.value for m in at.markdown)
    assert at.button(key="tt_plan_goals")


def test_goals_page_pace_budget_and_ranking(store):
    today = store.local_today()
    a = store.add_goal("Revision", "monthly", today, 20, "h", category_id="study")
    b = store.add_goal("Gym", "monthly", today, 12, "sessions")
    at = app()
    open_page(at, "Goals")
    text = " ".join(m.value for m in at.markdown)
    assert "This week" in " ".join(s.value for s in at.subheader) or "this week" in text
    assert "Goals need" in text
    at.button(key=f"edit_{b['id']}_up").click().run()            # Gym first now
    assert [g["title"] for g in store.goals_in("monthly", today)] == ["Gym", "Revision"]
    assert a["id"]


def test_suggestion_card_makes_a_goal(store):
    monday = store.week_start_of(store.local_today())
    for i in range(1, 4):
        day = (monday - timedelta(weeks=i)).isoformat()
        store.paint(day, "actual", store.slot_of("18:00"), store.slot_of("21:00"), {"label": "Guitar", "category_id": "rest"})
    at = app()
    open_page(at, "Goals")
    yes = [x for x in at.button if x.key and x.key.startswith("suggest_yes_")]
    assert yes
    yes[0].click().run()
    goals = store.goals_in("monthly", store.local_today())
    assert [(g["title"], g["category_id"], g["label"]) for g in goals] == [("Guitar", "rest", "Guitar")]


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
