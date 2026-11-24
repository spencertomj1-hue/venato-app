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


def test_modules_tile_shows_study_hours_not_marks(gr, store, monkeypatch):
    """Home's Modules tile (was Grades): this week's hours per module against its target, up to 3, then
    "and N more"; the header sums them. No marks."""
    from streamlit.testing.v1 import AppTest
    from venato import blocks, tile_status
    assert tile_status.modules() == "No modules yet"
    assert next(w for w in blocks.widgets() if w.key == "modules").name == "Modules"
    ids = [gr.add_module(n) for n in ("Algebra", "Biology", "Chemistry", "Drama")]
    gr.add_assessment(ids[0], "Exam", 100, 72)                                 # a mark: never shown
    done = dict(zip(ids, (1, 2, 0.5, 0.5)))
    monkeypatch.setattr(gr, "module_hours", lambda m, ctx: {"done": done[m["id"]], "planned": 3, "goal": 3, "term": 0})
    assert tile_status.modules() == "4 of 12 h this week"
    store.save_settings(home=[{"w": "modules", "size": "s"}])
    at = AppTest.from_file(str(Path(__file__).resolve().parents[1] / "app.py"), default_timeout=60).run()
    assert not at.exception
    page = " ".join(h.proto.body for h in at.get("html"))
    assert page.count('class="vn-mh-row"') == 3 and "and 1 more" in page
    assert "Algebra: 1 of 3 hours this week" in page and 'style="width:33%"' in page
    tile = page.split('class="vn-mh"')[1].split("and 1 more")[0]
    assert "72" not in tile and "%<" not in tile
    assert any(c.value == "4 of 12 h this week" for c in at.caption)


# --- Modules as the glue: detection after setup, title rules, overrides, unfiled, links ---

DAY = date(2026, 11, 20)


@pytest.fixture
def today(store, monkeypatch):
    """Pin the user's day to the fixtures' week (Needs you and the UI read it without a `day`)."""
    monkeypatch.setattr(store, "local_today", lambda: DAY)
    return DAY


def sync_uni(ol, canvas=False):
    ol.save_url(OUTLOOK_URL)
    if canvas:
        ol._save_extra([{"id": "c1", "name": "Canvas", "url": CANVAS_URL}])
    ol.sync(DAY, fetcher={OUTLOOK_URL: UNI, CANVAS_URL: CANVAS}.__getitem__)


def events_titled(store, title):
    rows = [e for e in store.outlook_between("2026-11-01", "2026-12-31") if e["title"] == title]
    assert rows, f"no {title!r} events in the fixture"
    return rows


def test_new_found_offers_only_unknown_and_undismissed(gr, store, ol):
    sync_uni(ol, canvas=True)
    gr.add_module("Organic Chemistry", code="CHEM50001")
    gr.add_module("spectroscopy and structure")                  # no code: matched by name, any case
    found = gr.new_found(DAY)
    codes = {m["code"] for m in found["modules"]}
    assert "CHEM50001" not in codes and "CHEM50002" not in codes and "CHEM60004" in codes
    gr.dismiss("module", "CHEM60004")
    assert "CHEM60004" not in {m["code"] for m in gr.new_found(DAY)["modules"]}
    assert {c["course_id"] for c in found["courses"]} == {"1101", "1102", "2201"}
    course = found["courses"][0]["course_id"]
    gr.dismiss("course", course)
    assert course not in {c["course_id"] for c in gr.new_found(DAY)["courses"]}
    mid = gr.add_module("Lasers", code="CHEM60004")
    gr.link_canvas_course("1102", mid)                          # a linked course isn't offered
    assert {c["course_id"] for c in gr.new_found(DAY)["courses"]} == {"2201"}


def test_new_found_ignores_an_old_term_still_in_venato(gr, store, ol):
    """A new term's feed: modules from last term stay in Venato and are never offered again."""
    sync_uni(ol)
    for m in gr.detected(DAY):
        gr.add_module(m["name"], code=m["code"])
    gr.add_module("Last Term Module", code="CHEM40001")
    assert gr.new_found(DAY) == {"modules": [], "courses": []}


def test_needs_you_mentions_new_modules(gr, store, ol, today):
    from venato import blocks
    assert not [i for i in blocks.needs() if i["block"] == "grades"]          # nothing connected
    sync_uni(ol, canvas=True)
    items = [i for i in blocks.needs() if i["block"] == "grades"]
    assert len(items) == 1
    assert items[0]["text"] == "5 new modules in your timetable · 3 Canvas courses to link"
    assert items[0]["page"] == "grades"
    for m in gr.detected():
        gr.dismiss("module", m["code"])
    assert [i["text"] for i in blocks.needs() if i["block"] == "grades"] == ["3 Canvas courses to link"]


def test_modules_page_offers_new_modules(gr, store, ol, today):
    from streamlit.testing.v1 import AppTest
    sync_uni(ol, canvas=True)
    at = AppTest.from_file(str(Path(__file__).resolve().parents[1] / "app.py"), default_timeout=60).run()
    goto(at, "Modules")
    assert not at.exception
    assert any("New in your calendars" in m.value for m in at.markdown)
    add = next(b for b in at.button if b.key == "gr_new_add_CHEM60004")
    add.click().run()
    assert not at.exception
    assert gr.find_module("Lasers")["code"] == "CHEM60004"
    next(b for b in at.button if b.key == "gr_new_ign_CHEM50001").click().run()
    assert "CHEM50001" not in {m["code"] for m in gr.new_found()["modules"]}


def test_module_without_code_gets_its_lectures_by_name(gr, store, ol):
    """No module has Spectroscopy's code (CHEM50002): a module with no code gets the series whose titles
    contain its name, the make-up lecture too."""
    sync_uni(ol)
    spec = gr.add_module("Spectroscopy")
    assert all(e["module_id"] == spec for e in events_titled(store, "Spectroscopy"))
    assert all(e["module_id"] == spec for e in events_titled(store, "Spectroscopy Make-Up Lecture"))
    assert not any(e["module_id"] for e in events_titled(store, "Organic Chemistry"))
    sync_uni(ol)                                                 # and again after a re-sync
    assert all(e["module_id"] == spec for e in events_titled(store, "Spectroscopy"))


def test_match_rule_and_override_priority(gr, store, ol):
    sync_uni(ol)
    org = gr.add_module("Organic Chemistry", code="CHEM50001")
    other = gr.add_module("Other", match="organic")              # broad rule loses to the code
    assert gr.get_module(other)["match"] == "organic"
    assert all(e["module_id"] == org for e in events_titled(store, "Organic Chemistry"))
    gr.file_series("Summer project chat", other)                 # a one-off with no code or rule
    sync_uni(ol)                                                 # survives a re-sync
    assert all(e["module_id"] == other for e in events_titled(store, "Summer project chat"))
    gr.file_series("Organic Chemistry", None, code="CHEM50001")  # "not a module" beats the code
    assert not any(e["module_id"] for e in events_titled(store, "Organic Chemistry"))
    gr.file_series("organic  chemistry lecture", org, code="chem 50001")   # keyed by normalised title and code
    assert all(e["module_id"] == org for e in events_titled(store, "Organic Chemistry"))


def test_first_module_wins_between_title_rules(gr, store, ol):
    sync_uni(ol)
    first = gr.add_module("Lab skills", match="laboratory")
    gr.add_module("Lab reports", match="LABORATORY")
    assert all(e["module_id"] == first for e in events_titled(store, "Year 2 Laboratory (L1L2)"))


def test_changing_a_rule_retags(gr, store, ol):
    sync_uni(ol)
    mid = gr.add_module("Talks")
    assert not any(e["module_id"] for e in events_titled(store, "Years 2 & 3 Town Hall"))
    gr.update_module(mid, match="town hall")
    assert all(e["module_id"] == mid for e in events_titled(store, "Years 2 & 3 Town Hall"))
    gr.update_module(mid, match="")                              # cleared: back to the name (no match)
    assert gr.get_module(mid)["match"] is None
    assert not any(e["module_id"] for e in events_titled(store, "Years 2 & 3 Town Hall"))
    gr.update_module(mid, code="CHEM50005")                      # a code: the name rule stops
    assert all(e["module_id"] == mid for e in events_titled(store, "Year 2 Laboratory (L1L2)"))


def test_title_key(store):
    assert store.title_key("  Organic  Chemistry Lecture ") == "organic chemistry"
    assert store.title_key("Maths Methods Classwork") == "maths methods classwork"


def test_unfiled_lists_series_until_filed(gr, store, ol):
    sync_uni(ol)
    series = {s["title"]: s for s in gr.unfiled_series(DAY)}
    assert {"Spectroscopy", "Research Frontiers Social", "Years 2 & 3 Town Hall"} <= set(series)
    assert "Summer project chat" not in series                   # a one-off isn't a series
    assert "Alex Doe, Personal Tutorial, 18/11/2026 13:20 GMT - New" not in series
    social = series["Research Frontiers Social"]
    assert social["count"] >= 2 and social["next"] >= DAY.isoformat()
    nexts = [s["next"] for s in gr.unfiled_series(DAY)]
    assert nexts == sorted(nexts)
    gr.add_module("Spectroscopy")                                # filed by its name
    assert "Spectroscopy" not in {s["title"] for s in gr.unfiled_series(DAY)}
    gr.file_series("Research Frontiers Social", None)            # "not a module" counts as filed
    assert "Research Frontiers Social" not in {s["title"] for s in gr.unfiled_series(DAY)}
    assert gr.unfiled_series(date(2027, 3, 1)) == []             # nothing in that window


def test_deleting_a_module_unfiles_its_overrides(gr, store, ol):
    sync_uni(ol)
    mid = gr.add_module("Projects")
    keep = gr.add_module("Talks")
    gr.file_series("Research Frontiers Social", mid)
    gr.file_series("Years 2 & 3 Town Hall", keep)
    assert all(e["module_id"] == mid for e in events_titled(store, "Research Frontiers Social"))
    gr.delete_module(mid)
    assert not any(e["module_id"] for e in events_titled(store, "Research Frontiers Social"))
    titles = {s["title"] for s in gr.unfiled_series(DAY)}
    assert "Research Frontiers Social" in titles and "Years 2 & 3 Town Hall" not in titles
    assert all(e["module_id"] == keep for e in events_titled(store, "Years 2 & 3 Town Hall"))


def test_deleting_a_module_lets_another_rule_take_its_series(gr, store, ol):
    sync_uni(ol)
    first = gr.add_module("Lab one", match="laboratory")
    second = gr.add_module("Lab two", match="laboratory")
    gr.delete_module(first)
    assert all(e["module_id"] == second for e in events_titled(store, "Year 2 Laboratory (L1L2)"))


def test_unfiled_deadlines(gr, store):
    """Imported (Canvas) deadlines on no module, minus ignored courses. Ones typed in by hand may well be on no
    module (a passport renewal), so they're never nagged about."""
    mid = gr.add_module("Organic Chemistry")
    store.add_deadline("Renew passport", "2026-12-01")
    store.add_deadline("Problem sheet", "2026-12-02", module_id=mid)
    store.import_canvas([
        {"uid": "event-assignment-1", "title": "Quiz", "label": "X", "course_id": "77", "due": "2026-12-01",
         "due_time": "17:00"},
        {"uid": "event-assignment-2", "title": "Training", "label": "TRNG", "course_id": "88", "due": "2026-12-01",
         "due_time": "17:00"},
        {"uid": "event-assignment-3", "title": "Old quiz", "label": "X", "course_id": "77", "due": "2026-11-01",
         "due_time": "17:00"}])
    old = next(d for d in store.deadlines() if d["title"] == "Old quiz")
    store.set_deadline_done(old["id"], True)
    assert [d["title"] for d in gr.unfiled_deadlines()] == ["Quiz", "Training"]
    gr.dismiss("course", "88")
    assert [d["title"] for d in gr.unfiled_deadlines()] == ["Quiz"]


def test_unfiled_card_and_links_panel(gr, store, ol, today):
    from streamlit.testing.v1 import AppTest
    sync_uni(ol, canvas=True)
    org = gr.add_module("Organic Chemistry", code="CHEM50001")
    gr.add_module("Projects")
    store.import_canvas([{"uid": "event-assignment-1", "title": "Essay", "label": "X", "course_id": "77",
                          "due": "2026-12-01", "due_time": "17:00"}])
    at = AppTest.from_file(str(Path(__file__).resolve().parents[1] / "app.py"), default_timeout=60).run()
    goto(at, "Modules")
    assert not at.exception
    assert any("Unfiled" in m.value for m in at.markdown)
    pick = next(s for s in at.selectbox if s.label == "Research Frontiers Social")
    projects = gr.find_module("Projects")["id"]
    pick.set_value(projects).run()
    assert not at.exception
    assert all(e["module_id"] == projects for e in events_titled(store, "Research Frontiers Social"))
    essay = next(s for s in at.selectbox if s.label == "Essay")
    essay.set_value(org).run()
    assert [d["module_id"] for d in store.deadlines() if d["title"] == "Essay"] == [org]
    # the module's own page: Links
    at.session_state["gr_module"] = org
    at.run()
    assert not at.exception
    at.text_input(key=f"gr_match_{org}").set_value("organic").run()
    assert gr.get_module(org)["match"] == "organic"
    at.selectbox(key=f"gr_canvas_{org}").set_value("1101").run()
    assert {c["course_id"]: c["module_id"] for c in gr.canvas_courses()}["1101"] == org
    btn = next(b for b in at.button if b.key and b.key.startswith(f"gr_notthis_{org}_"))
    btn.click().run()
    assert not at.exception
    assert not any(e["module_id"] for e in events_titled(store, "Organic Chemistry"))
    at.session_state["gr_module"] = None                         # back to Modules: Restore it
    at.run()
    restore = next(b for b in at.button if b.key and b.key.startswith("gr_restore_"))
    restore.click().run()
    assert not at.exception
    assert all(e["module_id"] == org for e in events_titled(store, "Organic Chemistry"))


def test_module_code_resolves_to_its_category(gr, store):
    mid = gr.add_module("Organic Chemistry", code="CHEM50001")
    cat = gr.get_module(mid)["category_id"]
    assert store.resolve_category(category="chem 50001") == cat
    assert store.resolve_category(category="CHEM50001") == cat
    assert store.resolve_category(label="CHEM50001 problem sheet") == cat
    assert store.resolve_category(label="chem 50001 revision") == cat
    assert store.resolve_category(label="chem50001") == cat
    assert store.resolve_category(label="Lunch") != cat
    assert store.resolve_category(category="CHEM99999") is None
    assert store.resolve_category(category="Exercise") == "exercise"          # names still work
    assert store.resolve_category(label="Gym") == "exercise"


def test_exact_category_name_beats_a_module_code(gr, store):
    store.save_category("qm", "QM", "#123456", "Life")
    gr.add_module("Quantum Mechanics", code="QM")
    assert store.resolve_category(category="QM") == "qm"
    assert store.resolve_category(label="qm") == "qm"


def test_a_code_beats_a_word_match(gr, store):
    """'CHEM50001 revision': the code says which module, though "Revision" alone means Study."""
    mid = gr.add_module("Organic Chemistry", code="CHEM50001")
    assert store.resolve_category(label="Revision") == "study"
    assert store.resolve_category(label="CHEM50001 revision") == gr.get_module(mid)["category_id"]


def test_no_modules_table_means_no_codes(blank_store):
    """The store never needs the Modules block: without its tables a code is just text."""
    assert blank_store.resolve_category(category="CHEM50001") is None
    assert blank_store.resolve_category(label="CHEM50001 sheet") is None


def test_focus_on_a_module_code_counts_for_the_module(gr, store):
    from venato.blocks import focus
    focus = importlib.reload(focus)
    mid = gr.add_module("Organic Chemistry", code="CHEM50001")
    focus.tool_log("chem 50001 problem sheet", 30)
    focus.tool_log("Lunch", 30, category="chem50001")
    today = store.local_today()
    cats = [s["category_id"] for s in focus.sessions(today, today)]
    assert cats == [gr.get_module(mid)["category_id"]] * 2


def test_link_summary(gr, store, ol):
    sync_uni(ol)
    mid = gr.add_module("Organic Chemistry", code="CHEM50001")
    s = gr.link_summary(gr.get_module(mid), DAY)
    upcoming = [e for e in events_titled(store, "Organic Chemistry") if e["date"] >= DAY.isoformat()]
    assert s == {"lectures": len(upcoming), "deadlines": 0, "canvas": None} and s["lectures"] > 0
    store.add_deadline("Problem sheet", "2026-11-30", module_id=mid)
    store.import_canvas([{"uid": "event-assignment-1", "title": "Quiz", "label": "20501.202610", "course_id": "77",
                          "due": "2026-12-01", "due_time": "17:00"}])
    gr.link_canvas_course("77", mid)
    s = gr.link_summary(gr.get_module(mid), DAY)
    assert (s["deadlines"], s["canvas"]) == (2, "20501.202610")
    empty = gr.add_module("Nothing On")
    assert gr.link_summary(gr.get_module(empty), DAY) == {"lectures": 0, "deadlines": 0, "canvas": None}


def test_cards_show_links_and_flag_missing_lectures(gr, store, ol, today):
    from streamlit.testing.v1 import AppTest
    sync_uni(ol)
    gr.add_module("Organic Chemistry", code="CHEM50001")
    gr.add_module("Nothing On")
    at = AppTest.from_file(str(Path(__file__).resolve().parents[1] / "app.py"), default_timeout=60).run()
    goto(at, "Modules")
    assert not at.exception
    captions = [c.value for c in at.caption]
    assert any(c.startswith(":material/link:") and "lectures" in c and "0 deadlines" in c for c in captions)
    assert any("No lectures found" in c for c in captions)
    assert not [t for t in at.toggle if t.label == "Assessments and settings"]       # it's on the module's page


# --- Review fixes ---

def _rows(store, rows):
    store.replace_outlook([{"uid": f"u{i}", "date": d, "start": "10:00", "end": "11:00", "title": t, "location": None,
                            "all_day": 0, "exact": None, "module_code": c} for i, (d, t, c) in enumerate(rows)])


def test_a_series_choice_is_per_module_code(gr, store):
    """Two modules each have "Problems Class" (and bare "Lecture"s): a choice for one leaves the other alone,
    and can be undone."""
    a = gr.add_module("Alpha", code="ALP101")
    b = gr.add_module("Beta", code="BET202")
    rows = [(f"2026-11-{d}", t, c) for d in (23, 24, 25) for t in ("Problems Class", "Lecture")
            for c in ("ALP101", "BET202")]
    _rows(store, rows)
    gr.file_series("Problems Class", None, code="ALP101")
    gr.file_series("Lecture", None, code="ALP101")
    ev = store.outlook_between("2026-11-01", "2026-11-30")
    assert all(e["module_id"] == b for e in ev if e["uid"] in {f"u{i}" for i, r in enumerate(rows) if r[2] == "BET202"})
    assert not any(e["module_id"] for e in ev if e["uid"] in {f"u{i}" for i, r in enumerate(rows) if r[2] == "ALP101"})
    assert {(s["title"], s["code"]) for s in gr.not_a_module_series()} == {("Problems Class", "ALP101"), ("Lecture", "ALP101")}
    gr.unfile_series("Problems Class", "ALP101")                 # Restore
    assert all(e["module_id"] == a for e in store.outlook_between("2026-11-01", "2026-11-30")
               if e["title"] == "Problems Class" and e["uid"] in {f"u{i}" for i, r in enumerate(rows) if r[2] == "ALP101"})


def test_not_this_module_on_the_links_panel_only_unlinks_that_module(gr, store):
    a = gr.add_module("Alpha", code="ALP101")
    b = gr.add_module("Beta", code="BET202")
    _rows(store, [(f"2026-11-{d}", "Problems Class", c) for d in (23, 24) for c in ("ALP101", "BET202")])
    series = gr.series_of(a, date(2026, 11, 20))
    assert [(s["title"], s["code"], s["count"]) for s in series] == [("Problems Class", "ALP101", 2)]
    gr.file_series(series[0]["title"], None, code=series[0]["code"])
    assert gr.series_of(a, date(2026, 11, 20)) == []
    assert gr.series_of(b, date(2026, 11, 20))[0]["count"] == 2
    assert [s["code"] for s in gr.unfiled_series(date(2026, 11, 20))] == []     # marked, so not unfiled


def test_unfiled_series_keep_codes_apart(gr, store):
    _rows(store, [(f"2026-11-{d}", "Tutorial", c) for d in (23, 24) for c in ("ALP101", "BET202")])
    assert sorted(s["code"] for s in gr.unfiled_series(date(2026, 11, 20))) == ["ALP101", "BET202"]
    gr.file_series("Tutorial", None, code="ALP101")
    assert [s["code"] for s in gr.unfiled_series(date(2026, 11, 20))] == ["BET202"]


def test_same_name_other_code_is_a_new_module(gr, store, ol):
    sync_uni(ol)
    gr.add_module("Lasers", code="CHEM60099")                    # last year's Lasers, another code
    assert "CHEM60004" in {m["code"] for m in gr.new_found(DAY)["modules"]}
    gr.add_module("Organic Chemistry")                           # no code: the name is enough
    assert "CHEM50001" not in {m["code"] for m in gr.new_found(DAY)["modules"]}


def test_a_module_whose_lectures_are_filed_isnt_offered(gr, store, ol):
    sync_uni(ol)
    mine = gr.add_module("Practicals", match="laboratory")       # took the CHEM50005 lab's lectures
    assert all(e["module_id"] == mine for e in events_titled(store, "Year 2 Laboratory (L1L2)"))
    assert "CHEM50005" not in {m["code"] for m in gr.new_found(DAY)["modules"]}
    assert "CHEM50003" in {m["code"] for m in gr.new_found(DAY)["modules"]}
