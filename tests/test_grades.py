"""Grades block: averages, secured marks, what's needed, year weighting, UK / US, tools, quick."""

import importlib
from datetime import date
from pathlib import Path

import pytest
from nav_helpers import goto, page_names


@pytest.fixture
def gr(store):
    from venato import blocks, tools, quick
    importlib.reload(tools)
    importlib.reload(blocks)
    importlib.reload(quick)
    from venato.blocks import grades as module
    module = importlib.reload(module)
    blocks.save(blocks.chosen_keys() + ["grades"])
    return module


def test_module_maths(gr, store):
    mid = gr.add_module("Quantum Mechanics", 20, "Year 2", target=70, code="QM")
    gr.add_assessment(mid, "Coursework", 30, 80)
    gr.add_assessment(mid, "Midterm", 20, 60)
    gr.add_assessment(mid, "Exam", 50)
    n = gr.module_numbers(gr.get_module(mid))
    assert n["average"] == pytest.approx(72) and n["secured"] == pytest.approx(36)
    assert n["needed"] == pytest.approx(68) and n["status"] == "possible"     # (70 - 36) / 50%
    with pytest.raises(gr.GradeError):
        gr.add_assessment(mid, "Extra", 10)                                    # over 100% of the module
    with pytest.raises(gr.GradeError):
        gr.add_assessment(mid, "Bad", 5, 120)


def test_overall_years_and_systems(gr, store):
    a = gr.add_module("A", 20, "Year 2")
    gr.add_assessment(a, "Exam", 100, 60)
    b = gr.add_module("B", 20, "Year 3")
    gr.add_assessment(b, "Exam", 100, 75)
    gr.save_settings("UK", {"Year 2": 1, "Year 3": 2})
    o = gr.overall()
    assert o["degree"] == pytest.approx((60 + 2 * 75) / 3) and gr.classification(o["degree"]) == "First"
    assert gr.classification(59.9) == "2:2" and gr.letter(88) == ("B+", 3.3)
    gr.save_settings("US")
    assert "GPA" in gr.describe(o["degree"], o["gpa"])
    gr.update_module(a, final=65)
    assert gr.module_numbers(gr.get_module(a))["projected"] == 65


def test_tools_quick_and_page(gr, store):
    from venato import quick
    gr.tool_add_module("ACP", 15, "Year 2", 70)
    gr.tool_add_grade("acp", "Coursework", weight=40)
    assert "Saved" in quick.handle("got 68 in acp coursework").reply
    assert gr.assessments(gr.find_module("ACP")["id"])[0]["mark"] == 68
    assert "needs" in gr.tool_needed("ACP").text and "Overall" in gr.tool_summary().text
    from streamlit.testing.v1 import AppTest
    at = AppTest.from_file(str(Path(__file__).resolve().parents[1] / "app.py"), default_timeout=60).run()
    goto(at, "Modules")
    assert not at.exception


# --- Modules, categories, deadlines and events (Phase 2) ---

FIXTURES = Path(__file__).parent / "fixtures"
CANVAS = (FIXTURES / "canvas_sample.ics").read_bytes()
UNI = (FIXTURES / "uni_timetable_sample.ics").read_bytes()
CANVAS_URL = "https://canvas.example.ac.uk/feeds/calendars/user_abc123.ics"
OUTLOOK_URL = "https://outlook.office365.com/owa/calendar/abc/def/calendar.ics"


@pytest.fixture
def ol(store, tmp_path, monkeypatch):
    from venato import outlook
    outlook = importlib.reload(outlook)                 # picks up the reloaded store
    from conftest import MemoryKeyring
    monkeypatch.setattr(outlook, "keyring", MemoryKeyring())   # reload brought back the real Keychain
    monkeypatch.setattr(outlook, "CACHE", tmp_path / "cache.ics")
    monkeypatch.setattr(outlook, "_extra_cache", lambda cid: tmp_path / f"cal-{cid}.ics")
    return outlook


def _category(store, cid):
    cats = store.load_categories()
    row = cats[cats["id"] == cid]
    return None if row.empty else row.iloc[0].to_dict()


def test_a_module_gets_its_own_category(gr, blank_store):
    store = blank_store
    a = gr.add_module("Organic Chemistry", code="CHEM50001")
    b = gr.add_module("Spectroscopy")
    ca, cb = gr.get_module(a)["category_id"], gr.get_module(b)["category_id"]
    assert ca and cb and ca != cb
    cat = _category(store, ca)
    assert (cat["name"], cat["grp"]) == ("Organic Chemistry", "Modules")
    assert cat["colour"] != _category(store, cb)["colour"]                     # the next free colour
    gr.update_module(a, name="Organic Chem II")
    assert _category(store, ca)["name"] == "Organic Chem II"                   # renamed together
    gr.update_module(a, credits=20)
    assert _category(store, ca)["name"] == "Organic Chem II"


def test_deleting_a_module_only_clears_its_links(gr, store, ol):
    mid = gr.add_module("Organic Chemistry", code="CHEM50001")
    cid = gr.get_module(mid)["category_id"]
    ol.save_url(OUTLOOK_URL)
    ol.sync(date(2026, 11, 20), fetcher=lambda url: UNI)
    tagged = [e for e in store.outlook_between("2026-11-01", "2026-12-31") if e["module_id"] == mid]
    assert tagged
    did = store.add_deadline("Problem sheet", "2026-11-30", module_id=mid)
    store.import_canvas([{"uid": "event-assignment-1", "title": "Quiz", "label": "CHEM50001.2026",
                          "course_id": "77", "due": "2026-12-01", "due_time": "17:00"}])
    assert gr.canvas_courses()[0]["module_id"] == mid                          # label carries the code: linked
    gr.delete_module(mid)
    assert _category(store, cid)["name"] == "Organic Chemistry"                # the category stays
    assert store.get_deadline(did)["module_id"] is None                        # the deadline stays, unlinked
    assert {d["title"] for d in store.deadlines()} == {"Problem sheet", "Quiz"}
    events = store.outlook_between("2026-11-01", "2026-12-31")
    assert len([e for e in events if e["title"] == "Organic Chemistry"]) == len(tagged)   # events stay
    assert not any(e["module_id"] for e in events)
    assert gr.canvas_courses()[0]["module_id"] is None


def test_linking_a_canvas_course_moves_its_deadlines(gr, store):
    from venato import feeds
    store.import_canvas(feeds.canvas_events(CANVAS, store.tz()))
    courses = gr.canvas_courses()
    assert [(c["course_id"], c["label"], c["module_id"]) for c in courses] == [
        ("1101", "20501.202610", None), ("1102", "20502.202610", None), ("2201", "TRNG-260812134148.202610", None)]
    mid = gr.add_module("Organic Chemistry", code="CHEM50001")
    gr.link_canvas_course("1101", mid)
    titles = {d["title"] for d in store.deadlines(include_done=True) if d["module_id"] == mid}
    assert titles == {"Term 1 - Assignment 1 (OC Grp4)", "Term 1 - Assignment 2 (OC Grp4)"}
    # new assignments in that course pick up the link
    extra = CANVAS.replace(b"UID:event-assignment-override-4117", b"UID:event-assignment-override-4999")
    store.import_canvas(feeds.canvas_events(extra, store.tz()))
    assert len([d for d in store.deadlines(include_done=True) if d["module_id"] == mid]) == 3
    gr.link_canvas_course("1101", None)
    assert not any(d["module_id"] for d in store.deadlines(include_done=True))


def test_sync_sends_canvas_to_deadlines_and_tags_timetable_events(gr, store, ol):
    mid = gr.add_module("Organic Chemistry", code="CHEM50001")
    lasers = gr.add_module("Lasers", code="CHEM60004")
    ol.save_url(OUTLOOK_URL)
    ol._save_extra([{"id": "c1", "name": "Canvas", "url": CANVAS_URL}])
    feeds = {OUTLOOK_URL: UNI, CANVAS_URL: CANVAS}
    status = ol.sync(date(2026, 11, 20), fetcher=feeds.__getitem__)
    assert status["ok"]
    events = store.outlook_between("2026-11-01", "2026-12-31")
    assert not any("Assignment" in e["title"] or "Wellbeing" in e["title"] for e in events)   # Canvas: not events
    assert len(store.deadlines(include_done=True)) == 7
    org = [e for e in events if e["title"] == "Organic Chemistry"]
    assert org and all(e["module_id"] == mid for e in org)
    assert all(e["module_id"] == lasers for e in events if e["title"] == "Lasers")    # first code of two
    assert not any(e["module_id"] for e in events if e["title"] in ("Spectroscopy", "Summer project chat"))
    assert store.outlook_category("Organic Chemistry", org[0]["module_id"]) == gr.get_module(mid)["category_id"]
    assert store.outlook_category("Spectroscopy") == "classes"
    block = store.get_block(store.detach_outlook(org[-1]["uid"]))          # changed by the student: keeps the colour
    assert block["category_id"] == gr.get_module(mid)["category_id"]
    ol.sync(date(2026, 11, 20), fetcher=feeds.__getitem__)                     # idempotent
    assert len(store.deadlines(include_done=True)) == 7
    # a module added later tags the events already there
    spec = gr.add_module("Spectroscopy", code="CHEM50002")
    assert all(e["module_id"] == spec for e in store.outlook_between("2026-11-01", "2026-12-31")
               if e["title"] == "Spectroscopy")


def test_module_hours_count_once(gr, store, ol):
    mid = gr.add_module("Organic Chemistry", code="CHEM50001")
    cat = gr.get_module(mid)["category_id"]
    ol.save_url(OUTLOOK_URL)
    ol.sync(date(2026, 11, 20), fetcher=lambda url: UNI)
    module_goal = {"category_id": cat, "label": None}
    classes_goal = {"category_id": "classes", "label": None}
    week = ("2026-11-23", "2026-11-29")
    # Organic Chemistry: two 1-hour lectures that week, under the module's category only
    assert store.goal_hours(module_goal, *week, "plan") == 2
    everything = store.outlook_between(*week)
    timed = sum((store.slot_of(e["end"]) - store.slot_of(e["start"])) / 2 for e in everything if not e["all_day"])
    assert store.goal_hours(classes_goal, *week, "plan") + 2 == timed           # the rest, under Classes
    from venato import review
    plan, _ = importlib.reload(review)._slot_maps("2026-11-23")
    assert plan[store.slot_of("10:00")] == cat


def test_linking_a_course_keeps_deadlines_the_student_moved(gr, store):
    from venato import feeds
    store.import_canvas(feeds.canvas_events(CANVAS, store.tz()))
    a = gr.add_module("A", code="AAA1001")
    b = gr.add_module("B", code="BBB1001")
    c = gr.add_module("C", code="CCC1001")
    gr.link_canvas_course("1101", a)
    ds = sorted((d for d in store.deadlines(include_done=True) if d["module_id"] == a), key=lambda d: d["due"])
    store.update_deadline(ds[0]["id"], module_id=c)                          # moved by hand
    gr.link_canvas_course("1101", b)
    assert store.get_deadline(ds[0]["id"])["module_id"] == c                 # left alone
    assert store.get_deadline(ds[1]["id"])["module_id"] == b


def test_no_orphan_category_when_the_module_insert_fails(gr, store, monkeypatch):
    import sqlite3
    first = gr.add_module("A")
    before = sorted(store.load_categories()["name"])
    monkeypatch.setattr(gr, "_id", lambda: first)                            # the same id: the insert fails
    with pytest.raises(sqlite3.IntegrityError):
        gr.add_module("B")
    assert sorted(store.load_categories()["name"]) == before                 # nothing made or renamed
