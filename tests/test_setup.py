"""Setup wizard and Settings: link checks, connecting, Keychain, Claude status, backups, the wizard flow."""

import importlib
import json
import os
import subprocess
from pathlib import Path

import pytest
from streamlit.testing.v1 import AppTest

from conftest import MemoryKeyring
from nav_helpers import goto, page_names

APP = str(Path(__file__).resolve().parents[1] / "app.py")
FIXTURE = (Path(__file__).parent / "fixtures" / "sample.ics").read_bytes()
GOOD = "https://outlook.office365.com/published/0000fake/1111fake/calendar.ics"


@pytest.fixture
def outlook(store, tmp_path, monkeypatch):
    from venato import outlook as module
    module = importlib.reload(module)
    monkeypatch.setattr(module, "CACHE", tmp_path / "cache.ics")
    monkeypatch.setattr(module, "keyring", MemoryKeyring())
    return module


# --- link checks ---

def test_good_link(outlook):
    assert outlook.check_link(f"  {GOOD}  ") == (GOOD, None)


def test_html_link_is_swapped(outlook):
    url, note = outlook.check_link(GOOD.replace(".ics", ".html"))
    assert url == GOOD and "switched it to the ICS link" in note


@pytest.mark.parametrize("bad, why", [
    ("", "Paste"),
    ("http://outlook.office365.com/published/x/calendar.ics", "https"),
    ("https://evil.example.com/calendar.ics", "isn't an Outlook calendar link"),
    ("https://outlook.office365.com.evil.com/calendar.ics", "isn't an Outlook calendar link"),
    ("https://outlook.office365.com/published/x/calendar", "end in .ics"),
])
def test_bad_links(outlook, bad, why):
    with pytest.raises(outlook.LinkError, match=why):
        outlook.check_link(bad)


@pytest.mark.parametrize("kind, status, says", [
    ("offline", None, "internet"),
    ("http", 403, "ask your IT team"),
    ("http", 404, "couldn't find that calendar"),
    ("notcal", None, "ICS link"),
])
def test_friendly_errors(outlook, kind, status, says):
    assert says in outlook.friendly(outlook.SyncError("x", kind, status))


def test_try_link_and_connect(outlook, store):
    found = outlook.try_link(GOOD, fetcher=lambda url: FIXTURE)
    assert found["count"] >= 0 and len(found["preview"]) <= 3
    status = outlook.connect(GOOD, found["data"])
    assert status["ok"] and outlook.ics_url() == GOOD                  # saved to the (fake) Keychain
    assert store.outlook_between("2026-10-01", "2026-12-31")
    outlook.disconnect()
    assert outlook.ics_url() is None and store.outlook_between("2026-10-01", "2026-12-31") == []



# --- Claude, settings, backups ---

def test_claude_status(store, tmp_path, monkeypatch):
    from venato import assistant
    from venato import setup_checks
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.setattr(assistant, "find_claude", lambda: None)
    assert setup_checks.claude_status()["found"] is False

    # A found CLI; what `claude auth status --json` prints is faked, so this works on every OS.
    answer = {}

    def fake_run(args, **kwargs):
        assert args[1:] == ["auth", "status", "--json"]
        return subprocess.CompletedProcess(args, 0, stdout=json.dumps(answer), stderr="")

    monkeypatch.setattr(assistant, "find_claude", lambda: str(tmp_path / "claude"))
    monkeypatch.setattr(setup_checks.subprocess, "run", fake_run)
    answer.update(loggedIn=False)
    status = setup_checks.claude_status()
    assert status["found"] and not status["logged_in"]

    answer.update(loggedIn=True, email="me@example.com")
    assert setup_checks.claude_status()["account"] == "me@example.com"


def test_settings_and_backups(store):
    from venato import setup_checks
    setup_checks.save_settings(wizard_done=False, other=1)
    assert setup_checks.load_settings() == {"wizard_done": False, "timezone": "Europe/London", "other": 1}
    path = setup_checks.backup_now()
    assert path.exists() and path.parent == store.DATA_DIR / "backups"
    assert setup_checks.list_backups() == [path]


# --- the wizard (new setup tests are further down) ---

def test_api_key_setup(store, monkeypatch):
    """Pasting a key: it's checked, saved in the (fake) secret store, and then Claude counts as ready."""
    from venato import assistant
    from venato import setup_checks
    monkeypatch.setattr(assistant, "find_claude", lambda: "/sdk/_bundled/claude")
    monkeypatch.setattr(assistant, "bundled_claude", lambda: "/sdk/_bundled/claude")
    status = setup_checks.claude_status()
    assert not status["logged_in"] and status["bundled"] and not status["found"]

    checked = []
    monkeypatch.setattr(assistant, "check_api_key", lambda key: (checked.append(key) or key.endswith("good"), "nope"))
    at = AppTest.from_file(APP, default_timeout=60).run()
    goto(at, "Settings")
    at.text_input[[t.label for t in at.text_input].index("Anthropic API key")].input("sk-ant-bad")
    at.button[[b.label for b in at.button].index("Save key")].click().run()
    assert checked == ["sk-ant-bad"] and not assistant.saved_api_key()
    assert any(e.value == "nope" for e in at.error)

    at.text_input[[t.label for t in at.text_input].index("Anthropic API key")].input("sk-ant-good")
    at.button[[b.label for b in at.button].index("Save key")].click().run()
    assert assistant.api_key() == "sk-ant-good"
    assert setup_checks.claude_status()["account"] == "API key"
    assert assistant._env("/sdk/_bundled/claude")["ANTHROPIC_API_KEY"] == "sk-ant-good"
    assert any("using an Anthropic API key" in s.value for s in at.success)

    assistant.forget_api_key()
    assert assistant.api_key() is None


def test_check_api_key_messages(monkeypatch):
    from venato import assistant
    assert not assistant.check_api_key("hello")[0]                       # not even the right shape

    class Reply:
        def __init__(self, code):
            self.status_code = code
    for code, ok, words in ((200, True, "works"), (401, False, "didn't accept"), (500, False, "error (500)")):
        monkeypatch.setattr(assistant.requests, "get", lambda *a, code=code, **k: Reply(code))
        result = assistant.check_api_key("sk-ant-x")
        assert result[0] is ok and words in result[1] and "sk-ant-x" not in result[1]


def test_appearance_setting(store):
    from venato.ui import appearance
    assert appearance.mode() == "System"
    at = AppTest.from_file(APP, default_timeout=60).run()
    goto(at, "Settings")
    at.segmented_control(key="set_theme").set_value("Dark").run()
    assert not at.exception and store.load_settings()["theme"] == "Dark" and appearance.mode() == "Dark"
    store.save_settings(theme="Purple")                         # anything odd falls back to System
    assert appearance.mode() == "System"


def test_automatic_backups(store, tmp_path):
    from datetime import date as d
    from venato import setup_checks
    folder = tmp_path / "cloud" / "Venato backups"
    assert setup_checks.set_backups_dir(str(folder)) == folder and setup_checks.backups_dir() == folder
    made = setup_checks.auto_backup_if_due()
    assert made and made.parent == folder
    assert setup_checks.auto_backup_if_due() is None                 # one a day
    # Keeps only the newest N plain backups; others (e.g. -before-todos) are left alone.
    for day in range(1, 8):
        (folder / f"life-2026-09-0{day}-120000.db").write_bytes(b"x")
    (folder / "life-2026-01-01-120000-before-todos.db").write_bytes(b"x")
    store.save_settings(backup_keep=3)
    for p in folder.glob("life-*.db"):                               # pretend today's isn't made yet
        if p.name.startswith(f"life-{d.today().isoformat()}"):
            p.unlink()
    setup_checks.auto_backup_if_due()
    names = sorted(p.name for p in folder.glob("life-*.db"))
    assert len([n for n in names if "before" not in n]) == 3 and "life-2026-01-01-120000-before-todos.db" in names
    store.save_settings(auto_backup=False)
    for p in folder.glob(f"life-{d.today().isoformat()}*"):
        p.unlink()
    assert setup_checks.auto_backup_if_due() is None                 # switched off
    with pytest.raises(ValueError):
        setup_checks.set_backups_dir("relative/path")
    setup_checks.set_backups_dir(None)
    assert setup_checks.backups_dir() == store.DATA_DIR / "backups"


def test_text_size_setting(store):
    from venato.ui import appearance
    at = AppTest.from_file(APP, default_timeout=60).run()
    assert not any("font-size: 20px" in h.value for h in at.get("html"))
    goto(at, "Settings")
    at.segmented_control(key="set_text_size").set_value("Extra large").run()
    assert not at.exception and appearance.text_size() == "Extra large"
    assert any("html { font-size: 20px !important; }" in h.value for h in at.get("html"))


def test_time_zone(store, monkeypatch):
    from datetime import datetime
    from zoneinfo import ZoneInfo
    assert store.zone_name() == "Europe/London"                  # (the tests pin it)
    store.save_settings(timezone="America/New_York")
    assert store.local_today() == datetime.now(ZoneInfo("America/New_York")).date()
    assert store.stamp().endswith(("-04:00", "-05:00"))
    store.save_settings(timezone="Not/AZone")                    # nonsense: the computer's zone
    monkeypatch.setattr(store, "computer_zone_name", lambda: "Asia/Tokyo")
    assert store.zone_name() == "Asia/Tokyo"
    store.save_settings(timezone=None)
    at = AppTest.from_file(APP, default_timeout=60).run()
    goto(at, "Settings")
    assert not at.exception and at.toggle(key="region_tz_auto").value is True
    at.toggle(key="region_tz_auto").set_value(False).run()
    at.selectbox(key="region_tz").set_value("Australia/Sydney").run()
    assert store.load_settings()["timezone"] == "Australia/Sydney" and not at.exception


def test_finish_keeps_a_saved_block_choice(store):
    """Finishing the wizard again (wizard_done false, blocks already chosen) doesn't wipe the choice."""
    from venato import setup_checks
    from venato.ui import settings_ui
    store.save_settings(wizard_done=False, blocks=["grades"])
    settings_ui._finish()
    s = setup_checks.load_settings()
    assert s["blocks"] == ["grades"] and s["wizard_done"] is True


# --- the setup wizard (Phase 6) ---

import datetime as _dt

FIXTURES = Path(__file__).parent / "fixtures"
UNI_ICS = (FIXTURES / "uni_timetable_sample.ics").read_bytes()
CANVAS_ICS = (FIXTURES / "canvas_sample.ics").read_bytes()
UNI_URL = "https://outlook.office365.com/published/0000fake/1111fake/calendar.ics"
CANVAS_URL = "https://canvas.example.edu/feeds/calendars/user_fake.ics"
MON = _dt.date(2026, 11, 16)
NOW = _dt.datetime(2026, 11, 16, 9, 0)


@pytest.fixture
def fresh(blank_store, monkeypatch):
    """A brand-new data folder (no settings: the wizard shows), the feeds served from the fixtures, a pinned Monday."""
    from venato import outlook as ol
    os.remove(blank_store.DATA_DIR / "settings.json")
    monkeypatch.setattr(ol, "fetch", lambda url: CANVAS_ICS if "canvas" in url else UNI_ICS)
    monkeypatch.setattr(blank_store, "local_now", lambda: NOW)
    monkeypatch.setattr(blank_store, "local_today", lambda: MON)
    return blank_store


def _next(at, key="wiz_next"):
    at.button(key=key).click().run()
    assert not at.exception, at.exception


def _skip_to_the_end(at):
    """Skip every step from here to the last; the headers seen on the way."""
    seen = []
    while not [b for b in at.button if b.key == "wiz_finish"]:
        seen.append(at.header[0].value)
        _next(at, "wiz_skip")
    return seen


def _submit(at, label="Connect"):
    next(b for b in at.button if b.label == label).click().run()
    assert not at.exception, at.exception


def test_skipping_everything_lands_on_a_blank_home(fresh):
    from venato import blocks, setup_checks
    at = AppTest.from_file(APP, default_timeout=60).run()
    assert at.title[0].value == "Welcome to Venato" and "page" not in at.session_state
    _next(at, "wiz_skip_all")
    s = setup_checks.load_settings()
    assert s["wizard_done"] is True and s["ai_enabled"] is False and "home" not in s
    assert s["blocks"] == blocks.STARTER
    assert at.session_state["page"] == "Home"
    assert fresh.load_categories().empty and fresh.get_habits() == [] and fresh.deadlines() == []
    assert fresh.goals_open() == [] and fresh.load_label_map().empty
    for page in page_names():
        goto(at, page)
        assert not at.exception, (page, at.exception)


def test_skipping_every_step_one_by_one_adds_nothing(fresh):
    at = AppTest.from_file(APP, default_timeout=60).run()
    _next(at)                                                    # Get started
    seen = _skip_to_the_end(at)
    assert seen[0].endswith("Are you a student?") and not any(h.endswith(("Canvas", "Your modules")) for h in seen)
    _next(at, "wiz_finish")
    assert at.session_state["page"] == "Home"
    assert fresh.load_categories().empty and fresh.goals_open() == [] and fresh.get_habits() == []


def test_a_non_student_gets_no_uni_steps(fresh):
    from venato.ui import onboarding
    assert [k for k, *_ in onboarding.STEPS if k in ("timetable", "canvas", "modules", "hours")] == \
        ["timetable", "canvas", "modules", "hours"]
    at = AppTest.from_file(APP, default_timeout=60).run()
    _next(at)
    at.radio(key="ob_student").set_value("No").run()
    _next(at)
    assert at.header[0].value.endswith("Your goals")             # straight past the four uni steps
    names = _skip_to_the_end(at)
    assert not any(n.endswith(("Canvas", "Your modules", "Study hours", "Your uni timetable")) for n in names)
    _next(at, "wiz_finish")
    from venato import blocks
    assert not blocks.is_on("grades") and blocks.chosen_keys() == blocks.STARTER


def test_a_student_gets_the_uni_steps_and_modules(fresh):
    from venato import blocks
    at = AppTest.from_file(APP, default_timeout=60).run()
    _next(at)
    at.radio(key="ob_student").set_value("Yes").run()
    _next(at)
    assert at.header[0].value.endswith("Your uni timetable")
    _next(at, "wiz_skip")
    assert at.header[0].value.endswith("Canvas")
    _next(at, "wiz_skip")
    assert at.header[0].value.endswith("Your modules")
    assert any("Add a module" in t.label for t in at.text_input)  # no feed: a plain box
    _next(at, "wiz_skip")
    assert at.header[0].value.endswith("Study hours")
    _next(at)
    _skip_to_the_end(at)
    _next(at, "wiz_finish")
    assert blocks.is_on("grades")


def test_student_with_the_fixture_feeds_ends_up_with_everything(fresh):
    """Timetable and Canvas links, modules, study hours, goals, tracking, categories and the first week."""
    from venato import blocks, setup_checks
    from venato.blocks import grades as gr
    at = AppTest.from_file(APP, default_timeout=90).run()
    _next(at)
    at.radio(key="ob_student").set_value("Yes").run()
    _next(at)

    # Uni timetable: the preview counts lectures
    at.text_input(key="ob_link_uni").set_value(UNI_URL)
    _submit(at)
    assert any("lecture" in s.value and "Connected" in s.value for s in at.success), [s.value for s in at.success]
    assert fresh.outlook_between("2026-11-16", "2026-11-22")
    _next(at)

    # Canvas: the preview counts assignments
    at.text_input(key="ob_link_canvas").set_value(CANVAS_URL)
    _submit(at)
    assert any("assignments due" in s.value for s in at.success), [s.value for s in at.success]
    assert len(fresh.deadlines()) == 7
    _next(at)

    # Modules: the detected ones, a Canvas course linked to one of them
    assert at.header[0].value.endswith("Your modules")
    assert any("Organic Chemistry" in t.value for t in at.text_input)
    course = next(s for s in at.selectbox if s.key.startswith("ob_course_"))
    assert "Not linked" in course.options and course.value == "Not linked"
    assert any(("Assignment" in s.label) or ("[" in s.label) for s in at.selectbox)
    at.segmented_control(key="ob_target").set_value("First").run()
    course.set_value("Organic Chemistry").run()
    _next(at)
    mods = gr.modules()
    assert {"Organic Chemistry"} <= {m["name"] for m in mods} and all(m["category_id"] and m["target"] == 70 for m in mods)
    assert {c["id"] for c in fresh.load_categories().to_dict("records")} >= {m["category_id"] for m in mods}
    assert any(d["module_id"] for d in fresh.deadlines())                # the linked course's deadlines

    # Study hours
    at.slider(key="ob_hours").set_value(4.0).run()
    _next(at)
    study = [g for g in fresh.goals_open() if g["unit"] == "h"]
    assert len(study) == len(mods) and all(g["target"] == 4 * 12 for g in study)

    # Goals
    at.text_input(key="ob_goal_0").set_value("Get a First in my degree")
    at.text_input(key="ob_goal_1").set_value("Run a 10k")
    at.number_input(key="ob_goal_n_1").set_value(20.0)
    at.run()
    _next(at)
    mine = {g["title"]: g for g in fresh.goals_open()}
    assert mine["Get a First in my degree"]["due"] == "2027-02-16" and mine["Run a 10k"]["due"] == "2027-05-16"
    assert mine["Run a 10k"]["target"] == 20

    # What would you track: examples, all unticked to start
    boxes = [c for c in at.checkbox if c.key.startswith("ob_sg_")]
    assert boxes and not any(c.value for c in boxes)
    assert fresh.get_habits() == [] and "log_sleep" not in setup_checks.load_settings()
    next(c for c in boxes if "Trained" in c.label).set_value(True)
    next(c for c in boxes if "category: Study" in c.label).set_value(True)
    at.run()
    _next(at)
    assert fresh.find_habit("Trained") and "study" in set(fresh.load_categories()["id"])
    assert fresh.get_goal(mine["Run a 10k"]["id"])["habit_id"] == fresh.find_habit("Trained")[0]

    # Your day: module categories and the picked one are there; add one of our own in a new group
    assert at.header[0].value.endswith("Your day")
    at.text_input(key="ob_cat_name").set_value("Lab work")
    at.run()
    at.selectbox(key="ob_cat_group").set_value("New group…").run()
    at.text_input(key="ob_cat_newgroup").set_value("Uni").run()
    at.button(key="ob_cat_add").click().run()
    assert not at.exception, at.exception
    row = fresh.load_categories().set_index("name").loc["Lab work"]
    assert row["grp"] == "Uni"
    _next(at)

    # First week: suggested sittings go into the Plan
    assert at.header[0].value.endswith("Your first week")
    before = len(fresh.blocks_between("2026-11-16", "2026-11-23", "plan"))
    at.button(key="ob_week_add").click().run()
    assert not at.exception, at.exception
    assert len(fresh.blocks_between("2026-11-16", "2026-11-23", "plan")) > before

    # Home, then done
    assert at.header[0].value.endswith("Home")
    assert at.checkbox(key="ob_home_modules").value
    _next(at, "wiz_finish")
    s = setup_checks.load_settings()
    assert blocks.is_on("grades") and s["wizard_done"] and s["student"] is True
    assert any(c.get("w") == "modules" or "modules" in c.get("stack", []) for c in s["home"])
    assert at.session_state["page"] == "Home"
    for page in page_names():
        goto(at, page)
        assert not at.exception, (page, at.exception)


def test_running_setup_again_deletes_nothing(fresh):
    """Setup adds: every module, deadline, goal, habit, category and block already there is still there."""
    from venato import blocks, setup_checks
    from venato.blocks import grades as gr
    from venato.ui import onboarding
    mid = gr.add_module("Organic Chemistry", code="CHEM50001")
    did = fresh.add_deadline("Lab report", "2026-12-01", module_id=mid)
    goal = fresh.add_goal("Read more", "monthly", MON, 4, "books")
    fresh.add_habit("Gym")
    fresh.save_category("music", "Music", "#112233", "Life")
    setup_checks.save_settings(wizard_done=True, blocks=["log"], blocks_optional=True, student=True)
    before_cats = set(fresh.load_categories()["id"])
    at = AppTest.from_file(APP, default_timeout=60).run()
    at.session_state["wizard_open"] = True
    at.run()
    assert at.title[0].value == "Welcome to Venato"
    _next(at)
    _next(at, "wiz_skip")                                        # student step: still a student
    names = _skip_to_the_end(at)
    assert any(n.endswith("Your modules") for n in names)
    _next(at, "wiz_finish")
    assert [m["id"] for m in gr.modules()] == [mid] and fresh.get_deadline(did)["module_id"] == mid
    assert fresh.get_goal(goal["id"]) and fresh.find_habit("Gym")
    assert set(fresh.load_categories()["id"]) >= before_cats | {gr.get_module(mid)["category_id"]}
    assert blocks.chosen_keys()[0] == "log" and blocks.is_on("grades")         # their choice kept; Modules added
    # and the same pieces of setup run twice add nothing twice
    onboarding.add_modules([{"code": "CHEM50001", "name": "Organic Chemistry"}])
    onboarding.apply_study_hours(6, MON)
    onboarding.apply_study_hours(6, MON)
    assert len(gr.modules()) == 1 and len([g for g in fresh.goals_open(MON) if g["unit"] == "h"]) == 0


def test_study_goals_respect_a_modules_own_hours(fresh):
    from venato.blocks import grades as gr
    from venato.ui import onboarding
    a, b = onboarding.add_modules([{"name": "Algebra"}, {"name": "Analysis"}])
    gr.set_week_hours_goal(b, 9)
    made = onboarding.apply_study_hours(5, MON)
    by = {g["title"]: g for g in made}
    assert by["Algebra study"]["target"] == 5 * 12 and by["Analysis study"]["target"] == 9 * 12
    assert fresh.load_settings()["study_hours"] == 5
    assert by["Algebra study"]["due"] == (MON + _dt.timedelta(weeks=12)).isoformat()
    assert onboarding.apply_study_hours(0, MON) == []


def test_study_hours_leave_old_modules_alone(fresh):
    from venato.blocks import grades as gr
    from venato.ui import onboarding
    old = gr.add_module("Old module")
    with fresh.db() as conn:                                   # from before: no category, finished
        conn.execute("UPDATE gr_modules SET category_id = NULL, final = 65 WHERE id = ?", (old,))
    onboarding.restart()
    new = onboarding.add_modules([{"name": "Fresh"}])
    made = onboarding.apply_study_hours(5, MON)
    assert [g["title"] for g in made] == ["Fresh study"]
    assert gr.get_module(old)["category_id"] is None
    assert not [g for g in fresh.goals_open(MON) if g["title"] == "Old module study"] and new


def test_check_feed_is_canvas_aware(fresh):
    from venato import outlook as ol
    from venato.ui import onboarding
    canvas = onboarding.check_feed(CANVAS_URL, "canvas", day=MON)
    assert canvas["kind"] == "canvas" and canvas["count"] == 6 and len(canvas["preview"]) == 3
    assert ol.found_text(canvas) == "Found 6 assignments due."
    uni = onboarding.check_feed(UNI_URL, "uni", day=MON)
    assert uni["kind"] == "calendar" and uni["lectures"] > 0
    assert {m["code"] for m in uni["modules"]} >= {"CHEM50001", "CHEM50002"}
    with pytest.raises(ol.LinkError, match="Canvas"):
        onboarding.check_feed(CANVAS_URL, "uni", day=MON)
    with pytest.raises(ol.LinkError, match="isn't a Canvas"):
        onboarding.check_feed(UNI_URL, "canvas", day=MON)
    with pytest.raises(ol.LinkError):
        onboarding.check_feed("not a link", "uni")


def test_goals_save_once_and_update_in_place(fresh):
    from venato.ui import onboarding
    ids = onboarding.save_goals([("Get a First", None, 3), ("", None, 6), ("Run", 100, 12)], MON)
    assert set(ids) == {0, 2} and len(fresh.goals_open(MON)) == 2
    again = onboarding.save_goals([("Get a 2:1", None, 3), ("", None, 6), ("Run", 100, 12)], MON)
    assert again == ids and len(fresh.goals_open(MON)) == 2
    assert fresh.get_goal(ids[0])["title"] == "Get a 2:1"
    onboarding.save_goals([("", None, 3), ("", None, 6), ("Run", 100, 12)], MON)
    assert [g["title"] for g in fresh.goals_open(MON)] == ["Run"]
    assert onboarding.months_on(_dt.date(2026, 11, 30), 3) == _dt.date(2027, 2, 28)


def test_keyword_suggestions():
    from venato import suggest
    names = lambda text: {(s["kind"], s["name"]) for s in suggest.for_goal(text)}
    assert names("Run a 10k") == {("category", "Exercise"), ("habit", "Trained")}
    assert ("category", "Study") in names("Get a First in my exams")
    assert names("I'm always tired") == {("sleep", "Track my sleep")}
    assert names("prune the hedge") == set() and names("") == set()
    assert not [s for s in suggest.for_goal("run, read, tired, drink water") if s["kind"] == "block"]


def test_tracking_suggestions_link_and_switch(fresh):
    from venato.ui import onboarding
    ids = onboarding.save_goals([("Run 100 hours", 100, 3), ("Be less tired", None, 6), ("", None, 12)], MON)
    goal = fresh.get_goal(ids[0])
    onboarding.apply_suggestion({"kind": "category", "name": "Exercise", "cid": "exercise"}, ids[0], number=True)
    g = fresh.get_goal(ids[0])
    assert g["category_id"] == "exercise" and g["unit"] == "h" and goal["habit_id"] is None
    assert "exercise" in set(fresh.load_categories()["id"]) and fresh.load_label_map().set_index("label").loc["Gym", "category_id"] == "exercise"
    onboarding.apply_suggestion({"kind": "habit", "name": "Trained"}, ids[0])
    g = fresh.get_goal(ids[0])
    assert g["habit_id"] == fresh.find_habit("Trained")[0]                           # a habit wins over a category
    assert g["category_id"] is None and g["unit"] is None
    onboarding.apply_suggestion({"kind": "category", "name": "Exercise", "cid": "exercise"}, ids[0], number=True)
    g = fresh.get_goal(ids[0])                                                       # either order ends the same
    assert g["habit_id"] and g["category_id"] is None and g["unit"] is None
    assert fresh.tracks_sleep() is False
    onboarding.apply_suggestion({"kind": "sleep", "name": "Track my sleep"}, ids[1])
    assert fresh.tracks_sleep() is True


def test_add_category_needs_a_name_and_group(fresh):
    from venato.ui import onboarding
    cid = onboarding.add_category("Lab work", "#112233", "Uni")
    assert fresh.groups() == ["Uni"] and cid == "lab-work"
    with pytest.raises(ValueError):
        onboarding.add_category("lab WORK", "#112233", "Uni")
    with pytest.raises(ValueError):
        onboarding.add_category("", "#112233", "Uni")
    assert onboarding.add_category("Lab-work", "#445566", "Uni") == "lab-work-2"


def test_first_week_suggestions_become_planned_blocks(fresh):
    from venato import pace
    from venato.blocks import grades as gr
    from venato.ui import onboarding
    onboarding.add_modules([{"name": "Organic Chemistry", "code": "CHEM50001"}])
    onboarding.apply_study_hours(6, MON)
    ctx = pace.Ctx(NOW)
    sittings = onboarding.first_week(MON, ctx)
    assert sittings and all("2026-11-16" <= s["date"] < "2026-11-23" for s in sittings)
    n = onboarding.add_first_week(sittings)
    assert n == len(sittings)
    slots = lambda rows: sum(fresh.slot_of(r["end"]) - fresh.slot_of(r["start"]) for r in rows)
    # (neighbours merge into one block; today's already started, so its sitting goes to the Actual track)
    assert slots(fresh.blocks_between("2026-11-16", "2026-11-23")) == slots(sittings)
    assert onboarding.add_first_week(sittings) == 0                  # the slots are taken now: nothing twice


def test_a_wrong_link_shows_an_error_not_a_crash(fresh):
    at = AppTest.from_file(APP, default_timeout=60).run()
    _next(at)
    at.radio(key="ob_student").set_value("Yes").run()
    _next(at)
    at.text_input(key="ob_link_uni").set_value("hello")
    _submit(at)
    assert at.error and not at.exception
    at.text_input(key="ob_link_uni").set_value(CANVAS_URL)
    _submit(at)
    assert any("Canvas" in e.value for e in at.error)


def test_try_link_keeps_the_calendar_message(outlook, store):
    found = outlook.try_link(GOOD, fetcher=lambda url: FIXTURE)
    assert found["kind"] == "calendar" and outlook.found_text(found).endswith("in the next 2 weeks.")


def test_pasting_a_connected_link_again_says_already_connected(fresh):
    at = AppTest.from_file(APP, default_timeout=60).run()
    _next(at)
    at.radio(key="ob_student").set_value("Yes").run()
    _next(at)
    at.text_input(key="ob_link_uni").set_value(UNI_URL)
    _submit(at)
    assert at.success and not at.error
    at.text_input(key="ob_link_uni").set_value(UNI_URL)
    _submit(at)
    assert not at.error and any("Already connected" in i.value for i in at.info)


def test_setup_parses_the_calendars_once_until_one_is_connected(fresh, monkeypatch):
    from venato import outlook as ol
    from venato.ui import onboarding
    calls = []
    real = ol.parse
    monkeypatch.setattr(ol, "parse", lambda *a, **k: calls.append(1) or real(*a, **k))
    state = {}
    monkeypatch.setattr(onboarding, "_ob", lambda: state)
    onboarding.connect_feed(onboarding.check_feed(UNI_URL, "uni", day=MON), MON)
    calls.clear()
    first = onboarding.detected_modules()
    n = len(calls)
    assert n and onboarding.detected_modules() == first and len(calls) == n       # the second is from `ob`
    onboarding.connect_feed(onboarding.check_feed(CANVAS_URL, "canvas", day=MON), MON)
    assert "detected" not in state                                                  # a new calendar: parse again
