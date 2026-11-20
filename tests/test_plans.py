"""Deadline plans: an hours goal in the deadline's module, with pace, carry-over, done / delete / re-date, and
the Modules page (list, one module's page, Plan, a module without a category)."""

import importlib
from datetime import date, datetime, timedelta
from pathlib import Path

import pytest
from streamlit.testing.v1 import AppTest

APP = str(Path(__file__).resolve().parents[1] / "app.py")
MON = date(2026, 11, 16)                      # a Monday
NOW = datetime(2026, 11, 16, 9, 0)


@pytest.fixture
def gr(store, monkeypatch):
    from venato import blocks
    importlib.reload(blocks)
    from venato.blocks import grades as module
    module = importlib.reload(module)
    blocks.save(blocks.chosen_keys() + ["grades"])
    monkeypatch.setattr(store, "local_now", lambda: NOW)
    monkeypatch.setattr(store, "local_today", lambda: MON)
    return module


@pytest.fixture
def pace(store, gr):
    from venato import pace as module
    return importlib.reload(module)


def _plan(store, gr, due="2026-11-30", **kw):
    mid = gr.add_module("Organic Chemistry", code="CHEM50001")
    did = store.add_deadline("Lab report", due, module_id=mid)
    return mid, did, store.plan_deadline(did, gr.get_module(mid)["category_id"], today=MON, **kw)


def test_total_hours_makes_an_hours_goal_in_the_modules_category(store, gr):
    mid, did, g = _plan(store, gr, total=15)
    assert (g["target"], g["due"], g["category_id"], g["label"], g["title"], g["kind"], g["deadline_id"]) == \
        (15, "2026-11-29", gr.get_module(mid)["category_id"], "Lab report", "Lab report", "hours", did)
    assert g["period_start"] == "2026-11-16"            # finish-by defaults to the day before it's due


def test_hours_a_week_become_a_total_over_the_weeks_to_finish_by(store, gr):
    _, _, g = _plan(store, gr, per_week=3)               # 16 Nov .. 29 Nov = 14 days = 2 weeks
    assert g["target"] == 6
    mid = gr.add_module("Spectroscopy")
    cat = gr.get_module(mid)["category_id"]
    did = store.add_deadline("Poster", "2026-12-10", module_id=mid)
    g = store.plan_deadline(did, cat, per_week=4, finish_by="2026-11-22", today=MON)
    assert (g["target"], g["due"]) == (4, "2026-11-22")  # one week
    g = store.plan_deadline(did, cat, per_week=3, finish_by="2026-11-25", today=MON)
    assert g["target"] == 4.5                            # 10 days at 3 h a week is 4.3 h, in halves


def test_plan_checks_its_input(store, gr):
    mid = gr.add_module("Organic Chemistry")
    cat = gr.get_module(mid)["category_id"]
    did = store.add_deadline("Lab report", "2026-11-30")
    with pytest.raises(ValueError):
        store.plan_deadline(did, cat, today=MON)                                  # neither
    with pytest.raises(ValueError):
        store.plan_deadline(did, cat, total=5, per_week=2, today=MON)             # both
    with pytest.raises(ValueError):
        store.plan_deadline(did, cat, total=5, finish_by="2026-12-02", today=MON)  # after it's due
    with pytest.raises(ValueError):
        store.plan_deadline(did, cat, total=5, finish_by="2026-11-10", today=MON)  # in the past
    store.set_deadline_done(did, True)
    with pytest.raises(ValueError):
        store.plan_deadline(did, cat, total=5, today=MON)                          # already done


def test_planning_again_changes_the_same_goal(store, gr):
    mid, did, g = _plan(store, gr, total=10)
    again = store.plan_deadline(did, g["category_id"], total=12, finish_by="2026-11-27", today=MON)
    assert again["id"] == g["id"] and (again["target"], again["due"]) == (12, "2026-11-27")
    assert len(store.goals_open(MON)) == 1


def test_a_missed_sitting_is_carried_over(store, gr, pace):
    _, did, g = _plan(store, gr, total=14)               # 14 h over 14 days: 7 h a week
    cat = g["category_id"]
    week2 = MON + timedelta(days=7)
    ctx = pace.Ctx(NOW + timedelta(days=7))              # Monday of the second week, nothing done
    w = pace.week_goals(week2, ctx)[0]
    assert (w["need"], w["baseline"], w["carried"]) == (14, 7, 7)       # the whole first week carried over
    assert pace.goal_pace(store.deadline_goal(did), ctx)["state"] == "behind"
    store.paint("2026-11-16", "actual", store.slot_of("10:00"), store.slot_of("14:00"),
                {"label": "Lab report", "category_id": cat})             # 4 of the 7 h were done
    store.mark_confirmed("2026-11-16")
    w = pace.week_goals(week2, pace.Ctx(NOW + timedelta(days=7)))[0]
    assert (w["done"], w["need"], w["carried"]) == (0, 10, 3)            # the missed 3 h are carried over
    assert store.deadline_goal(did)["value"] == 4


def test_done_closes_the_goal_and_its_suggested_sittings_go(store, gr, pace):
    _, did, g = _plan(store, gr, total=14)
    from venato import tools
    tools = importlib.reload(tools)
    monkey = pace.Ctx(NOW)
    assert tools.goal_spots(MON.isoformat(), ctx=monkey)               # sittings are suggested for the plan
    store.set_deadline_done(did, True)
    assert store.deadline_goal(did) is None and store.goals_open(MON) == []
    assert store.get_goal(g["id"])["id"] == g["id"]                      # closed, not deleted
    assert tools.goal_spots(MON.isoformat(), ctx=pace.Ctx(NOW)) == []
    store.set_deadline_done(did, False)                                  # un-ticking opens it again
    assert store.deadline_goal(did)["id"] == g["id"]


def test_deleting_the_deadline_deletes_its_goal(store, gr):
    _, did, g = _plan(store, gr, total=14)
    store.set_goal_week_hours(MON, {g["id"]: 3})
    store.delete_deadline(did)
    assert store.get_goal(g["id"]) is None and store.goals_open(MON) == []
    assert store.goal_week_hours(MON) == {}


def test_a_deadline_moved_by_hand_moves_the_goal(store, gr):
    _, did, g = _plan(store, gr, total=10)
    store.update_deadline(did, due="2026-12-04")                          # 4 days later
    assert store.get_goal(g["id"])["due"] == "2026-12-03"
    store.update_deadline(did, title="Lab report v2")                     # no date change: nothing moves
    assert store.get_goal(g["id"])["due"] == "2026-12-03"


def test_a_canvas_redate_moves_the_plan_goal_keeping_its_offset(store, gr):
    store.import_canvas([{"uid": "a1", "title": "Quiz", "label": "X", "course_id": "7",
                          "due": "2026-11-30", "due_time": "23:59"}])
    d = next(x for x in store.deadlines() if x["uid"] == "a1")
    cat = gr.get_module(gr.add_module("Quiz module"))["category_id"]
    default = store.plan_deadline(d["id"], cat, total=6, today=MON)
    assert default["due"] == "2026-11-29"                                 # the day before
    custom = store.plan_deadline(store.add_deadline("Other", "2026-12-05"), cat, total=6,
                                 finish_by="2026-12-01", today=MON)       # 4 days before
    store.import_canvas([{"uid": "a1", "title": "Quiz", "label": "X", "course_id": "7",
                          "due": "2026-12-03", "due_time": "23:59"}])     # Canvas moves it 3 days on
    assert store.get_deadline(d["id"])["due"] == "2026-12-03"
    assert store.get_goal(default["id"])["due"] == "2026-12-02"           # still the day before
    assert store.get_goal(custom["id"])["due"] == "2026-12-01"            # a hand-made one isn't Canvas's
    # a deadline the student re-dated, or ticked, is not reset by the next sync; a ticked one keeps its closed goal
    store.set_deadline_done(d["id"], True)
    store.import_canvas([{"uid": "a1", "title": "Quiz", "label": "X", "course_id": "7",
                          "due": "2026-12-03", "due_time": "23:59"}])
    assert store.deadline_goal(d["id"]) is None


def test_needs_you_says_no_plan_then_behind_then_nothing(store, gr, pace):
    from venato.ui import goal_time
    mid = gr.add_module("Organic Chemistry")
    cat = gr.get_module(mid)["category_id"]
    did = store.add_deadline("Lab report", "2026-11-20", module_id=mid)
    d = store.get_deadline(did)
    ctx = pace.Ctx(NOW)
    assert goal_time.deadline_needs_plan(d, ctx) == "no plan yet"
    store.plan_deadline(did, cat, total=20, finish_by="2026-11-19", today=MON)     # 20 h in 4 days
    assert goal_time.deadline_needs_plan(d, pace.Ctx(NOW)) == "behind on its plan"
    store.update_goal(store.deadline_goal(did)["id"], target=2)                    # 2 h, and it's planned
    store.paint("2026-11-17", "plan", store.slot_of("10:00"), store.slot_of("12:00"),
                {"label": "Lab report", "category_id": cat})
    assert goal_time.deadline_needs_plan(d, pace.Ctx(NOW)) == ""


# --- The Modules page ---

def test_module_without_a_category_offers_to_create_one(store, gr):
    with store.db() as conn:                                              # a module from before categories
        conn.execute("INSERT INTO gr_modules (id, name, credits, created_at) VALUES ('old', 'Old module', 10, 'x')")
    assert gr.get_module("old")["category_id"] is None and gr.category_colour(gr.get_module("old")) is None
    at = AppTest.from_file(APP, default_timeout=60).run()
    at.sidebar.radio[0].set_value("Modules").run()
    assert not at.exception
    next(b for b in at.button if b.key == "gr_cat_old").click().run()
    cid = gr.get_module("old")["category_id"]
    assert cid and store.load_categories().set_index("id").loc[cid, "name"] == "Old module"
    assert gr.create_category("old") == cid                               # asking again changes nothing


def test_modules_page_lists_each_module_and_opens_one(store, gr):
    at = AppTest.from_file(APP, default_timeout=60).run()
    at.sidebar.radio[0].set_value("Modules").run()
    assert not at.exception and any("No modules yet" in c.value for c in at.caption)      # empty state
    mid = gr.add_module("Organic Chemistry", code="CHEM50001", target=70)
    store.add_deadline("Lab report", "2026-11-30", module_id=mid)
    at = AppTest.from_file(APP, default_timeout=60).run()
    at.sidebar.radio[0].set_value("Modules").run()
    assert any("Next: Lab report" in c.value for c in at.caption)
    assert any("This week: 0 done / 0 planned / 6 h goal" in c.value for c in at.caption)  # the 6 h default
    next(b for b in at.button if b.key == f"gr_open_btn_{mid}").click().run()
    assert not at.exception and any("Organic Chemistry" in h.value for h in at.get("html"))
    assert any("No lectures this week" in c.value for c in at.caption)
    assert any("Lab report" in m.value for m in at.markdown)
    next(b for b in at.button if b.key == "gr_back").click().run()
    assert any(t.value == "Modules" for t in at.title)


def test_a_deadline_row_opens_its_module_and_plan_shows_progress(store, gr, pace):
    mid, did, g = _plan(store, gr, total=15)
    at = AppTest.from_file(APP, default_timeout=60).run()
    at.sidebar.radio[0].set_value("Goals").run()
    assert not at.exception
    mod = next(b for b in at.button if b.key == f"dl_mod_{did}")
    assert "Organic Chemistry" in mod.label and "0 / 15 h" in mod.label
    mod.click().run()
    assert at.session_state["page"] == "Modules" and at.session_state["gr_module"] == mid
    assert not at.exception


def test_a_module_weekly_goal_can_be_overridden(store, gr):
    mid = gr.add_module("Organic Chemistry")
    m = gr.get_module(mid)
    assert gr.week_hours_goal(m) == 6
    gr.set_week_hours_goal(mid, 9)
    assert gr.week_hours_goal(m) == 9
    gr.set_week_hours_goal(mid, None)
    assert gr.week_hours_goal(m) == 6


def test_module_hours_count_lectures_once(store, gr, pace):
    mid = gr.add_module("Organic Chemistry", code="CHEM50001")
    m = gr.get_module(mid)
    store.replace_outlook([{"uid": "l1", "date": "2026-11-17", "start": "10:00", "end": "12:00", "title": "Lecture",
                            "location": None, "all_day": 0, "exact": "10:00"}])
    store.tag_outlook_modules()
    with store.db() as conn:
        conn.execute("UPDATE tt_outlook SET module_id = ? WHERE uid = 'l1'", (mid,))
    h = gr.module_hours(m, pace.Ctx(NOW))
    assert (h["planned"], h["done"], h["goal"]) == (2, 0, 6)
    assert [e["uid"] for e in gr.week_events(mid, MON, MON + timedelta(days=6))] == ["l1"]


def test_plan_dialog_is_pre_filled(store, gr):
    mid = gr.add_module("Organic Chemistry")
    did = store.add_deadline("Lab report", store.local_today() + timedelta(days=15), module_id=mid)
    at = AppTest.from_file(APP, default_timeout=60).run()
    at.sidebar.radio[0].set_value("Goals").run()
    next(b for b in at.button if b.key == f"dl_plan_{did}").click().run()
    assert not at.exception
    assert next(s for s in at.selectbox if s.key == f"plan_mod_{did}").value == mid        # pre-filled
    assert next(d for d in at.date_input if d.key == f"plan_by_{did}").value == store.local_today() + timedelta(days=14)
    assert next(n for n in at.number_input if n.key == f"plan_hours_{did}_In total").value == 6   # 6 h to start


def test_plan_dialog_without_a_module_says_what_to_do(store, gr):
    did = store.add_deadline("Essay", store.local_today() + timedelta(days=5))
    at = AppTest.from_file(APP, default_timeout=60).run()
    at.sidebar.radio[0].set_value("Goals").run()
    next(b for b in at.button if b.key == f"dl_plan_{did}").click().run()
    assert not at.exception and any("Add a module" in i.value for i in at.info)
