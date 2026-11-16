"""
Start Working (the user's own areas, bars, levels, weekly bars and pot), its plan (delegation
triage), goal categories, and Km run against the training plan. Nothing in Start Working is
preset: each test sets up its own (made-up) bars.
"""

from datetime import date, timedelta
from pathlib import Path

import pytest
from streamlit.testing.v1 import AppTest

APP = str(Path(__file__).resolve().parents[1] / "app.py")


def _setup(store):
    """A made-up setup: two areas, three level bars and one weekly bar, two pots."""
    store.save_work_setup(areas=[{"name": "Studio", "colour": "#3B82F6"}, {"name": "Life"}])
    studio, life = (a["id"] for a in store.work_areas())
    store.save_work_setup(
        bars=[{"name": "Emails sent", "area": studio, "verb": "Sent one", "base": 3, "step": 5, "words": "email"},
              {"name": "Calls", "area": studio, "base": 2, "step": 0, "words": "call, ring"},
              {"name": "Posts", "area": life, "base": 1, "step": 1, "words": ["post", "publish"]},
              {"name": "Newsletter", "area": life, "weekly": True, "base": 2, "words": "newsletter"}],
        pots=["Equipment", "Treats"], reward=5, questions=["Who else could do this?"])


def test_nothing_is_preset(store):
    assert (store.work_bars(), store.work_areas(), store.work_pots(), store.work_questions()) == ([], [], [], [])
    assert store.work_targets(1) == {} and store.match_track("Send 5 emails") == (None, 1)
    with pytest.raises(ValueError):
        store.work_tap("emails")                                           # no such bar


def test_filling_every_bar_completes_the_level_and_pays(store):
    _setup(store)
    keys = {b["name"]: b["key"] for b in store.work_bars()}
    em, ca, po, nl = keys["Emails sent"], keys["Calls"], keys["Posts"], keys["Newsletter"]
    assert store.work_targets(1) == {em: 3, ca: 2, po: 1} and store.work_targets(3) == {em: 13, ca: 2, po: 3}
    for _ in range(4):
        store.work_tap(nl)                                                 # weekly: never completes a level
    for _ in range(3):
        assert store.work_tap("emails sent") is None                       # by name works too
    store.work_tap(em, -1)                                                 # one fewer
    store.work_tap(em)
    for _ in range(2):
        store.work_tap(ca)
    assert store.work_state()["counts"] == {em: 3, ca: 2, po: 0}
    assert store.work_tap(po) == 1                                         # the last one finishes level 1
    state = store.work_state()
    assert (state["level"], state["balance"], state["counts"][em]) == (2, 5.0, 0)
    assert state["targets"] == {em: 8, ca: 2, po: 2}
    assert state["weekly"] == {nl: 4}                                      # the weekly bar isn't reset by levels


def test_weekly_bar_starts_again_every_monday(store):
    _setup(store)
    nl = store.work_bar("newsletter")["key"]
    assert store.weekly_targets() == {nl: 2}
    store.work_tap(nl)
    store.work_tap(nl)
    last_week = (date.fromisoformat(store.work_week_start()) - timedelta(days=1)).isoformat() + "T12:00:00+00:00"
    with store.db() as conn:
        conn.execute("INSERT INTO work_log VALUES ('old', ?, 1, ?)", (nl, last_week))
    state = store.work_state()
    assert state["weekly"] == {nl: 2} and state["totals"][nl] == 3
    store.work_tap(nl, -1)                                                 # one fewer takes this week's, not last week's
    assert store.work_state()["weekly"] == {nl: 1} and store.work_state()["totals"][nl] == 2
    assert date.fromisoformat(store.work_week_start(date(2026, 11, 12))).weekday() == 0


def test_setup_keeps_keys_so_counts_stay(store):
    _setup(store)
    em = store.work_bar("Emails sent")
    store.work_tap(em["key"])
    bars = store.work_bars()
    bars[0]["name"] = "Emails out"                                         # renamed: same key, same count
    store.save_work_setup(bars=bars + [{"name": ""}])                      # a blank row is dropped
    assert store.work_bar("emails out")["key"] == em["key"] and len(store.work_bars()) == 4
    assert store.work_state()["counts"][em["key"]] == 1


def test_taps_are_idempotent_per_op(store):
    _setup(store)
    em = store.work_bar("Emails sent")["key"]
    store.work_tap(em, op_id="x")
    store.work_tap(em, op_id="x")
    assert store.work_state()["counts"][em] == 1


def test_spending_the_pot(store):
    _setup(store)
    pots = {p["name"]: p["key"] for p in store.work_pots()}
    with pytest.raises(ValueError):
        store.work_spend(5, pots["Equipment"])                             # nothing in it yet
    for track, n in store.work_targets(1).items():
        for _ in range(n):
            store.work_tap(track)
    store.work_spend(3, pots["Equipment"], "A new lamp")
    store.work_spend(2, pots["Treats"])
    state = store.work_state()
    assert state["balance"] == 0 and state["spent"] == {pots["Equipment"]: 3.0, pots["Treats"]: 2.0}
    with pytest.raises(ValueError):
        store.work_spend(1, pots["Treats"])
    with pytest.raises(ValueError):
        store.work_spend(1, "not a pot")


def test_delegation_questions_are_the_users(store):
    from venato.ui import work
    assert work.delegate_question() is None                                # none: no nudge
    _setup(store)
    assert work.delegate_question() == "Who else could do this?"


def test_every_task_must_be_decided(store):
    store.add_plan_task("Book the venue")
    store.add_plan_task("Design the poster")
    store.add_plan_task("Reply to old thread")
    tasks = {t["title"]: t for t in store.plan_tasks()}
    assert all(t["decision"] is None for t in tasks.values())
    store.decide_plan_task(tasks["Design the poster"]["id"], "delegate", "Sam")
    store.decide_plan_task(tasks["Book the venue"]["id"], "me")
    store.decide_plan_task(tasks["Reply to old thread"]["id"], "drop")
    left = {t["title"]: t for t in store.plan_tasks()}
    assert set(left) == {"Book the venue", "Design the poster"}             # dropped ones go
    assert left["Design the poster"]["who"] == "Sam"
    assert store.delegation_stats() == {"me": 1, "delegate": 1, "drop": 1}
    store.finish_plan_task(left["Book the venue"]["id"])
    assert [t["title"] for t in store.plan_tasks()] == ["Design the poster"]


def test_goal_categories(store):
    today = store.local_today()
    a = store.add_goal("Client calls", "monthly", today, 20)
    e = store.add_goal("Studio calls", "monthly", today, 20)
    store.set_goal_category(a["id"], "Work")
    store.set_goal_category(e["id"], "Studio")
    store.set_goal_category(store.add_goal("Sign ups", "monthly", today, 25)["id"], "work")   # same category
    cats = store.goal_categories()
    assert list(cats) == ["Work", "Studio"] and cats["Work"] != cats["Studio"]
    assert [g["category"] for g in store.goals_in("monthly", today)] == ["Work", "Studio", "Work"]
    store.set_goal_category(a["id"], None)
    assert store.get_goal(a["id"])["category"] is None


def test_km_goals_follow_the_training_plan(store):
    from venato import tools
    from venato.ui import training_ui
    today = store.local_today()
    assert [r[0] for r in training_ui.km_goals(today)] == ["This week", "This month"]   # no plan: no targets
    assert all(r[3] is None for r in training_ui.km_goals(today))
    tools.create_training_plan(today.isoformat(), confirmed=True, on_timetable=False)
    rows = training_ui.km_goals(today)
    assert len(rows) == 3 and rows[2][3] > rows[1][3] > 0                  # the plan's km grow week by week
    session = next(s for s in store.plan_sessions(store.active_plan()["id"]) if s["kind"] != "strength")
    store.update_session(session["id"], done=True, actual_km=7.5)
    assert training_ui.km_goals(date.fromisoformat(session["date"]))[2][2] == 7.5


def test_start_working_page_with_nothing_set_up(store):
    at = AppTest.from_file(APP, default_timeout=60).run()
    at.button(key="start_working").click().run()
    at.button(key="ws_skip_btn").click().run()                             # straight to the bars: none yet
    assert not at.exception
    assert any("No bars yet" in i.value for i in at.info) and at.button(key="ws_setup_save")


def test_start_working_page_and_home_render(store):
    _setup(store)
    at = AppTest.from_file(APP, default_timeout=60).run()
    assert not at.exception
    assert at.button(key="start_working").label == "Start Working"
    at.button(key="start_working").click().run()
    assert not at.exception
    assert at.sidebar.radio[0].value is None                              # nothing selected: Start Working
    # First: what needs doing this session. The bars wait until the list is done.
    assert "ws_setup_save" not in [b.key for b in at.button]
    at.text_area(key="ws_text").set_value("Firstly email Sam. Secondly, fix the bike").run()
    at.button(key="ws_make").click().run()
    assert not at.exception
    items = store.session_items()
    assert [i["title"] for i in items] == ["Email Sam", "Fix the bike"]
    for i in items:
        at.checkbox(key=f"ws_{i['id']}").check().run()
    assert not at.exception
    assert store.work_state()["counts"][store.work_bar("Emails sent")["key"]] == 1   # "email Sam" filled that bar
    assert at.button(key="ws_setup_save")                                  # list done: the bars and Set up
    at.text_input(key="plan_new").set_value("Book the venue").run()
    assert not at.exception
    assert [t["title"] for t in store.plan_tasks()] == ["Book the venue"]
    at.sidebar.radio[0].set_value("Home").run()                            # back out to any page
    assert not at.exception and at.sidebar.radio[0].value == "Home"
    assert "Start Working" not in at.sidebar.radio[0].options and "To-dos" in at.sidebar.radio[0].options


def test_session_list_is_split_and_linked(store):
    _setup(store)
    keys = {b["name"]: b["key"] for b in store.work_bars()}
    said = ("Okay so firstly I need to send 5 emails to the clients. Secondly, write the newsletter. "
            "Then call Sam at 5, and finally fix the bike")
    assert store.split_session_text(said) == ["Send 5 emails to the clients", "Write the newsletter",
                                              "Call Sam at 5", "Fix the bike"]
    assert store.split_session_text("1. email Sam\n2) book venue") == ["Email Sam", "Book venue"]
    assert store.match_track("Send 5 emails to the clients") == (keys["Emails sent"], 5)
    assert store.match_track("Call Sam at 5") == (keys["Calls"], 1)       # a time isn't a count
    assert store.match_track("Publish two posts") == (keys["Posts"], 2)
    assert store.match_track("Fix the bike") == (None, 1)
    assert store.match_track("Recall the order") == (None, 1)             # "call" only as a word

    today = store.local_today()
    bike = store.add_detailed_todo("Fix bike brakes", due=today)
    letter = store.add_detailed_todo("Newsletter", due=today)
    items = {i["title"]: i for i in store.add_session_items(store.split_session_text(said))}
    assert items["Fix the bike"]["todo_id"] == bike["id"] and items["Fix the bike"]["track"] is None
    assert (items["Write the newsletter"]["todo_id"], items["Write the newsletter"]["track"]) == (letter["id"], keys["Newsletter"])

    store.tick_session_item(items["Write the newsletter"]["id"])          # ticks the to-do and the weekly bar
    store.tick_session_item(items["Send 5 emails to the clients"]["id"])
    assert store.get_todo(letter["id"])["done"] and store.work_state()["weekly"][keys["Newsletter"]] == 1
    assert store.work_state()["counts"][keys["Emails sent"]] == 5
    store.tick_session_item(items["Write the newsletter"]["id"], False)   # unticking undoes both
    assert not store.get_todo(letter["id"])["done"] and store.work_state()["weekly"][keys["Newsletter"]] == 0
    store.tick_session_item(items["Send 5 emails to the clients"]["id"])  # ticking twice counts once
    assert store.work_state()["counts"][keys["Emails sent"]] == 5

    store.update_session_item(items["Call Sam at 5"]["id"], todo_id=bike["id"], track=None)
    assert {i["title"]: i for i in store.session_items()}["Call Sam at 5"]["todo_id"] == bike["id"]
    store.clear_session()
    assert store.session_items() == [] and store.work_state()["counts"][keys["Emails sent"]] == 5   # ticks stay
