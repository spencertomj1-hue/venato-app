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


def _row(row, text, how="tick", number=None, months=3, **kw):
    """One goal row for onboarding.save_goals."""
    return {"row": row, "text": text, "how": how, "number": number, "months": months, **kw}


def _skip_to_the_end(at):
    """Skip every step from here to the last; the headers seen on the way."""
    seen = []
    while not [b for b in at.button if b.key == "wiz_finish"]:
        seen.append((at.header or at.title)[0].value)
        if [b for b in at.button if b.key == "ob_student_no"]:      # the student question has no Skip
            _next(at, "ob_student_no")
        else:                                                    # (a student's goals step starts filled in)
            _next(at, "wiz_skip" if [b for b in at.button if b.key == "wiz_skip"] else "wiz_next")
    return seen


def _skip_to_the_end_after(at, habit_key, habit):
    """Goals step -> Next, add a habit on the track step with Next, then skip the rest."""
    _next(at)
    at.text_input(key=habit_key).set_value(habit).run()
    _next(at)
    _skip_to_the_end(at)


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
    seen = _skip_to_the_end(at)                                  # Welcome: "Not a student" is the way on
    assert seen == ["Welcome to Venato", "Your goals for the next few months", "What would you track?"]      # up to the last step
    _next(at, "wiz_finish")
    assert at.session_state["page"] == "Home"
    assert fresh.load_categories().empty and fresh.goals_open() == [] and fresh.get_habits() == []


def test_a_non_student_gets_no_uni_steps(fresh):
    from venato.ui import onboarding
    assert [k for k, *_ in onboarding.STEPS] == ["welcome", "goals", "calendars", "modules", "track", "week"]
    at = AppTest.from_file(APP, default_timeout=60).run()
    _next(at, "ob_student_no")
    assert at.header[0].value.startswith("Your goals")             # straight past the uni steps
    names = _skip_to_the_end(at)
    assert not any(n.endswith(("Connect your calendars", "Your modules")) for n in names)
    _next(at, "wiz_finish")
    from venato import blocks
    assert not blocks.is_on("grades") and blocks.chosen_keys() == blocks.STARTER


def test_a_student_gets_the_uni_steps_and_modules(fresh):
    from venato import blocks
    at = AppTest.from_file(APP, default_timeout=60).run()
    _next(at, "ob_student_yes")
    assert at.header[0].value.startswith("Your goals")            # goals first (D3)
    _next(at)
    assert at.header[0].value == "Connect your calendars"
    _next(at, "wiz_skip")
    assert at.header[0].value.endswith("Your modules")
    assert any("Add a module" in t.label for t in at.text_input)  # no feed: a plain box
    _next(at, "wiz_skip")
    assert at.header[0].value == "What would you track?"
    _skip_to_the_end(at)
    _next(at, "wiz_finish")
    assert blocks.is_on("grades")


def test_student_with_the_fixture_feeds_ends_up_with_everything(fresh):
    """Timetable and Canvas links, modules, study hours, goals, tracking, categories and the first week."""
    from venato import blocks, setup_checks
    from venato.blocks import grades as gr
    at = AppTest.from_file(APP, default_timeout=90).run()
    _next(at, "ob_student_yes")

    # Goals first (D3): the term goal is there to start (D4); a second goal with a number; a first step
    assert at.text_input(key="ob_goal_0").value == "Do well this term"
    assert at.segmented_control(key="ob_goal_when_0").value == "3 months"
    assert at.segmented_control(key="ob_goal_how_0").value == "Tick it off"
    assert at.button(key="ob_goal_rm_0")                         # removable
    at.text_input(key="ob_goal_step_0").set_value("Buy a planner")
    _next(at, "ob_goal_add")
    at.text_input(key="ob_goal_1").set_value("Run a 10k")
    at.segmented_control(key="ob_goal_when_1").set_value("6 months")
    at.segmented_control(key="ob_goal_how_1").set_value("A number").run()
    at.number_input(key="ob_goal_n_1").set_value(20.0)
    at.run()
    _next(at)
    goals = {g["title"]: g for g in fresh.life_goals()}
    term, run = goals["Do well this term"], goals["Run a 10k"]
    assert term["end_date"] == "2027-02-16" and run["end_date"] == "2027-05-16"
    (target,) = fresh.goals_open()
    assert target["life_goal_id"] == run["id"] and target["target"] == 20 and target["due"] == "2027-05-16"
    assert [t["title"] for t in fresh.life_goal_todos(term["id"])] == ["Buy a planner"]

    # Calendars: both on one step; the previews count lectures and assignments
    assert at.header[0].value == "Connect your calendars"
    assert at.text_input(key="ob_link_uni").proto.type == 0 and at.text_input(key="ob_link_canvas").proto.type == 0   # 0: plain text, not a password
    at.text_input(key="ob_link_uni").set_value(UNI_URL)
    at.button(key="ob_connect_uni").click().run()
    assert any("lecture" in s.value and "Connected" in s.value for s in at.success), [s.value for s in at.success]
    assert fresh.outlook_between("2026-11-16", "2026-11-22")
    at.text_input(key="ob_link_canvas").set_value(CANVAS_URL)
    at.button(key="ob_connect_canvas").click().run()
    assert any("assignments due" in s.value for s in at.success), [s.value for s in at.success]
    assert len(fresh.deadlines()) == 7
    _next(at)

    # Modules: the detected ones, a Canvas course linked to one of them
    assert at.header[0].value.endswith("Your modules")
    assert any("Organic Chemistry" in t.value for t in at.text_input)
    course = next(s for s in at.selectbox if s.key.startswith("ob_course_"))
    assert "Not linked" in course.options and course.value == "Not linked"
    assert any(("Assignment" in s.label) or ("[" in s.label) for s in at.selectbox)
    assert not at.segmented_control and not any(n.key == "ob_credits" for n in at.number_input)   # no grade questions
    assert all(n.value == 6 for n in at.number_input if n.key.startswith("ob_hours_"))
    assert any("module" in c.value and "h a week, lectures included" in c.value for c in at.caption)
    course.set_value("Organic Chemistry").run()
    _next(at)
    mods = gr.modules()
    assert {"Organic Chemistry"} <= {m["name"] for m in mods} and all(m["category_id"] and m["target"] is None for m in mods)
    assert {c["id"] for c in fresh.load_categories().to_dict("records")} >= {m["category_id"] for m in mods}
    assert any(d["module_id"] for d in fresh.deadlines())                # the linked course's deadlines

    study = [g for g in fresh.goals_open() if g["unit"] == "h"]                   # the default 6 h each
    assert len(study) == len(mods) and all(g["target"] == 6 * 12 for g in study)
    assert all(g["life_goal_id"] == term["id"] for g in study)                    # under the term goal (D4)

    # What would you track: examples, all unticked to start
    boxes = [c for c in at.checkbox if c.key.startswith("ob_sg_")]
    assert boxes and not any(c.value for c in boxes)
    assert fresh.get_habits() == [] and "log_sleep" not in setup_checks.load_settings()
    next(c for c in boxes if "Trained" in c.label).set_value(True)
    next(c for c in boxes if "category: Study" in c.label).set_value(True)
    at.run()
    # Colours on the same step: a chip for each example, none of them on yet; add one of our own
    pills = at.get("pills")[0]
    assert "Sleep" in pills.options and not any("(Life)" in o or "(Work)" in o for o in pills.options)
    assert "Organic Chemistry" in pills.value                    # the existing categories start on
    at.text_input(key="ob_cat_name").set_value("Lab work")
    at.run()
    at.button(key="ob_cat_add").click().run()
    assert not at.exception, at.exception
    row = fresh.load_categories().set_index("name").loc["Lab work"]
    assert row["grp"] != "Modules"
    _next(at)
    assert fresh.find_habit("Trained") and "study" in set(fresh.load_categories()["id"])
    assert fresh.get_goal(target["id"])["habit_id"] == fresh.find_habit("Trained")[0]

    # First week: suggested sittings go into the Plan
    assert at.header[0].value.endswith("Your first week")
    before = len(fresh.blocks_between("2026-11-16", "2026-11-23", "plan"))
    at.button(key="ob_week_add").click().run()
    assert not at.exception, at.exception
    assert any(s.value.startswith("Added ") and "to your Plan" in s.value for s in at.success)
    assert not any("Nothing to suggest yet" in str(m.value) for m in at.markdown)
    assert len(fresh.blocks_between("2026-11-16", "2026-11-23", "plan")) > before

    # Done: Home gets the Modules widget by itself
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
    _next(at, "ob_student_yes")                                  # student step: still a student
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


def test_changing_one_modules_hours_box_gives_just_that_module_a_different_goal(fresh):
    from venato.blocks import grades as gr
    at = _student_at(fresh)
    _next(at, "wiz_skip")
    at.text_input(key="ob_new_module").set_value("Algebra")
    at.button(key="ob_add_module").click().run()
    at.text_input(key="ob_new_module").set_value("Analysis")
    at.button(key="ob_add_module").click().run()
    boxes = {n.label: n for n in at.number_input if n.key.startswith("ob_hours_")}
    assert set(boxes) == {"Algebra", "Analysis"} and all(n.value == 6 for n in boxes.values())
    assert any(c.value == "2 modules · 12 h a week, lectures included" for c in at.caption)
    boxes["Analysis"].set_value(9.0).run()
    assert any(c.value == "2 modules · 15 h a week, lectures included" for c in at.caption)
    assert _main_label(at) == "Next"
    _next(at)
    by = {g["title"]: g["target"] for g in fresh.goals_open() if g["unit"] == "h"}
    assert by == {"Algebra study": 6 * 12, "Analysis study": 9 * 12}
    assert {m["name"]: gr.week_hours_goal(m) for m in gr.modules()} == {"Algebra": 6, "Analysis": 9}
    assert all(m["target"] is None and m["credits"] == 15 for m in gr.modules())


def test_a_hours_box_for_a_detected_module_is_kept(fresh):
    from venato.blocks import grades as gr
    at = _student_at(fresh)
    at.text_input(key="ob_link_uni").set_value(UNI_URL)
    at.button(key="ob_connect_uni").click().run()
    _next(at)
    box = next(n for n in at.number_input if n.key.startswith("ob_hours_") and "Organic Chemistry" in n.label)
    box.set_value(2.5).run()
    _next(at)
    m = next(m for m in gr.modules() if m["name"] == "Organic Chemistry")
    assert gr.week_hours_goal(m) == 2.5
    assert all(gr.week_hours_goal(o) == 6 for o in gr.modules() if o["id"] != m["id"])


def test_a_chip_switched_on_in_setup_makes_its_category_and_activity_names(fresh):
    at = _student_at(fresh, student=False)
    _next(at, "wiz_skip")
    assert at.header[0].value.endswith("What would you track?")
    pills = at.get("pills")[0]
    assert pills.value == [] and "Exercise" in pills.options
    pills.set_value(["Exercise"]).run()
    assert _main_label(at) == "Next"
    _next(at)
    assert "exercise" in set(fresh.load_categories()["id"]) and "sleep" not in set(fresh.load_categories()["id"])
    labels = fresh.load_label_map().set_index("label")["category_id"].to_dict()
    assert labels["Gym"] == "exercise" and labels["Run"] == "exercise" and "Lecture" not in labels


def test_an_existing_category_with_an_examples_name_is_not_made_twice(fresh):
    fresh.save_category("study-2", "Study", "#123456", "Work")
    at = _student_at(fresh, student=False)
    _next(at, "wiz_skip")
    assert "Study" in at.get("pills")[0].value                    # on already, by name
    at.get("pills")[0].set_value(["Study", "Exercise"]).run()
    _next(at)
    cats = fresh.load_categories()
    assert list(cats[cats["name"] == "Study"]["id"]) == ["study-2"] and "exercise" in set(cats["id"])


def test_a_stale_skip_click_on_track_still_saves_a_ticked_chip(fresh):
    at = _student_at(fresh, student=False)
    _next(at, "wiz_skip")
    at.get("pills")[0].set_value(["Exercise"])
    at.button(key="wiz_skip").click().run()
    assert at.header[0].value.endswith("Your first week") and "exercise" in set(fresh.load_categories()["id"])


def test_an_untouched_hours_box_over_40_is_left_alone(fresh):
    from venato.blocks import grades as gr
    mid = gr.add_module("Marathon")
    gr.set_week_hours_goal(mid, 50)
    at = _student_at(fresh)
    _next(at, "wiz_skip")
    assert next(n for n in at.number_input if n.key == f"ob_hours_{mid}").value == 50
    _next(at, "wiz_skip")
    assert gr.week_hours_goal(gr.get_module(mid)) == 50


def test_the_default_group_for_an_own_category_is_the_smallest_not_modules(fresh):
    from venato.ui import onboarding
    assert onboarding.default_group() == "Life"
    fresh.save_category("a", "A", "#111111", "Work")
    fresh.save_category("b", "B", "#222222", "Work")
    fresh.save_category("c", "C", "#333333", "Life")
    fresh.save_category("m", "M", "#444444", fresh.MODULES_GROUP)
    assert onboarding.default_group() == "Life"


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


def test_goal_rows_make_long_term_goals_with_a_target_and_a_first_step(fresh):
    from venato.ui import onboarding
    onboarding.restart()
    out = onboarding.save_goals([
        _row(0, "Get a First", step="Book a library room"),
        _row(1, "", months=6),
        _row(2, "Run a 10k", "number", 20, 6, why="Feel fitter"),
        _row(3, "Learn guitar", "hours", 2, end=_dt.date(2027, 1, 11)),
    ], MON)
    assert set(out) == {0, 2, 3}
    first, run, guitar = (fresh.get_life_goal(out[i]["goal"]) for i in (0, 2, 3))
    assert first["end_date"] == "2027-02-16" and run["end_date"] == "2027-05-16" and guitar["end_date"] == "2027-01-11"
    assert run["why"] == "Feel fitter" and first["start"] == MON.isoformat()
    assert out[0]["target"] is None                                                # Tick it off: no target (D1)
    t = fresh.get_goal(out[2]["target"])
    assert t["life_goal_id"] == run["id"] and t["target"] == 20 and t["due"] == run["end_date"] and t["unit"] is None
    h = fresh.get_goal(out[3]["target"])                                           # 8 weeks to 11 January
    assert h["life_goal_id"] == guitar["id"] and h["unit"] == "h" and h["category_id"] and h["target"] == 2 * 8
    assert h["title"] == "Learn guitar: 2 h a week" and t["title"] == "Run a 10k: 20"
    todo = fresh.get_todo(out[0]["todo"])                                          # this week's list, the goal's category
    assert todo["title"] == "Book a library room" and todo["period"] == "weekly"
    assert todo["group_id"] == fresh.life_goal_group(first["id"])["id"]
    assert [x["id"] for x in fresh.life_goal_todos(first["id"])] == [todo["id"]]
    assert out[2]["todo"] is None and len(fresh.goals_open(MON)) == 2


def test_saving_goal_rows_again_changes_them_in_place(fresh):
    from venato.ui import onboarding
    onboarding.restart()
    out = onboarding.save_goals([_row(0, "Get a First", step="Book a room"), _row(1, "Run", "number", 100, 12)], MON)
    again = onboarding.save_goals([_row(0, "Get a 2:1", months=6, step="Book a quiet room"),
                                   _row(1, "Run", "hours", 3, 12)], MON)
    assert again == out and len(fresh.life_goals(MON)) == 2 and len(fresh.goals_open(MON)) == 1
    g = fresh.get_life_goal(out[0]["goal"])
    assert g["title"] == "Get a 2:1" and g["end_date"] == "2027-05-16"
    assert fresh.get_todo(out[0]["todo"])["title"] == "Book a quiet room"
    t = fresh.get_goal(out[1]["target"])                                           # number -> hours: same target
    assert t["unit"] == "h" and t["category_id"] == "exercise" and t["target"] == 3 * 52
    third = onboarding.save_goals([_row(0, "Get a 2:1", months=6), _row(1, "Run", "tick", None, 12)], MON)
    assert third[0]["todo"] is None and fresh.get_todo(out[0]["todo"]) is None   # step emptied: its to-do goes
    assert third[1]["target"] is None and fresh.get_goal(out[1]["target"]) is None  # tick: the target goes
    assert fresh.get_life_goal(out[1]["goal"])
    back = onboarding.save_goals([_row(1, "Run", "number", 5, 12)], MON)          # and comes back as a new one
    assert back[1]["target"] and fresh.get_goal(back[1]["target"])["life_goal_id"] == out[1]["goal"]


def test_emptying_a_goal_row_deletes_only_what_setup_made_for_it(fresh):
    from venato.ui import onboarding
    onboarding.restart()
    mine = fresh.add_life_goal("Mine from before", months=3)
    other = fresh.add_goal("Old target", None, MON, 5, due="2027-01-01", life_goal_id=mine["id"])
    out = onboarding.save_goals([_row(0, "Run a 10k", "number", 10, step="Buy shoes"), _row(1, "Read", "number", 12)], MON)
    by_hand = fresh.add_todo("Stretch", "weekly", MON, group_id=fresh.life_goal_group(out[0]["goal"])["id"])
    onboarding.save_goals([_row(0, "", "number", 10), _row(1, "Read", "number", 12)], MON)
    assert fresh.get_life_goal(out[0]["goal"]) is None and fresh.get_goal(out[0]["target"]) is None
    assert fresh.get_todo(out[0]["todo"]) is None and fresh.get_todo(by_hand["id"])        # only its own to-do
    assert fresh.get_life_goal(mine["id"]) and fresh.get_goal(other["id"]) and fresh.get_life_goal(out[1]["goal"])
    onboarding.forget_goal_row(1)
    assert [g["title"] for g in fresh.life_goals(MON)] == ["Mine from before"]
    assert [g["title"] for g in fresh.goals_open(MON)] == ["Old target"]
    assert onboarding.months_on(_dt.date(2026, 11, 30), 3) == _dt.date(2027, 2, 28)


def test_my_goals_are_the_rows_goals_and_their_targets(fresh):
    from venato.ui import onboarding
    onboarding.restart()
    out = onboarding.save_goals([_row(0, "Get a First"), _row(2, "Run a 10k", "number", 20)], MON)
    mine = onboarding._my_goals()
    assert [(r, g["id"], t and t["id"]) for r, g, t in mine] == [(0, out[0]["goal"], None),
                                                               (2, out[2]["goal"], out[2]["target"])]
    fresh.delete_life_goal(out[0]["goal"])                                         # deleted elsewhere: gone here too
    assert [r for r, *_ in onboarding._my_goals()] == [2]


def test_a_goal_ending_before_it_starts_is_an_error(fresh):
    from venato.ui import onboarding
    onboarding.restart()
    with pytest.raises(ValueError):
        onboarding.save_goals([_row(0, "Run", end=MON)], MON)


def test_keyword_suggestions():
    from venato import suggest
    names = lambda text: {(s["kind"], s["name"]) for s in suggest.for_goal(text)}
    assert names("Run a 10k") == {("category", "Exercise"), ("habit", "Trained")}
    assert ("category", "Study") in names("Get a First in my exams")
    assert names("Do well this term") == {("category", "Study")}                # the students' first goal
    assert names("I'm always tired") == {("sleep", "Track my sleep")}
    assert names("prune the hedge") == set() and names("") == set()
    assert not [s for s in suggest.for_goal("run, read, tired, drink water") if s["kind"] == "block"]


def test_tracking_suggestions_link_and_switch(fresh):
    from venato.ui import onboarding
    onboarding.restart()
    out = onboarding.save_goals([_row(0, "Run 100 hours", "number", 100), _row(1, "Be less tired", months=6)], MON)
    ids = {0: out[0]["target"], 1: None}
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
    at = _student_at(fresh)
    at.text_input(key="ob_link_uni").set_value("hello")
    at.button(key="ob_connect_uni").click().run()
    assert at.error and not at.exception
    at.text_input(key="ob_link_uni").set_value(CANVAS_URL)
    at.button(key="ob_connect_uni").click().run()
    assert any("Canvas" in e.value for e in at.error)


def test_try_link_keeps_the_calendar_message(outlook, store):
    found = outlook.try_link(GOOD, fetcher=lambda url: FIXTURE)
    assert found["kind"] == "calendar" and outlook.found_text(found).endswith("in the next 2 weeks.")


def test_pasting_a_connected_link_again_says_already_connected(fresh):
    at = _student_at(fresh)
    at.text_input(key="ob_link_uni").set_value(UNI_URL)
    at.button(key="ob_connect_uni").click().run()
    assert at.success and not at.error
    at.text_input(key="ob_link_uni").set_value(UNI_URL)
    at.button(key="ob_connect_uni").click().run()
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


# --- Phase 1 of the redesign: Next saves what's typed, one action button, the student cards ---

def _student_at(fresh, student=True):
    """Past Welcome. A student also goes on past Goals (saving the prefilled term goal) to the calendars step."""
    at = AppTest.from_file(APP, default_timeout=60).run()
    _next(at, "ob_student_yes" if student else "ob_student_no")
    if student:
        _next(at)
    return at


def _main_label(at):
    """The label of the one main button on the right of the footer (Skip or Next)."""
    mains = [b for b in at.button if b.key in ("wiz_skip", "wiz_next")]
    assert len(mains) == 1, [b.key for b in at.button]
    return mains[0].label


def test_next_connects_a_pasted_link(fresh):
    at = _student_at(fresh)
    assert at.header[0].value == "Connect your calendars"
    at.text_input(key="ob_link_uni").set_value(UNI_URL)
    at.text_input(key="ob_link_canvas").set_value(CANVAS_URL).run()
    _next(at)                                                    # Next, not Connect: both are connected
    assert at.header[0].value.endswith("Your modules") and not at.error
    assert fresh.outlook_between("2026-11-16", "2026-11-22") and len(fresh.deadlines()) == 7


def test_next_with_a_bad_link_stays_and_says_why(fresh):
    at = _student_at(fresh)
    at.text_input(key="ob_link_uni").set_value("hello").run()
    _next(at)
    assert at.header[0].value == "Connect your calendars" and at.error
    at.text_input(key="ob_link_uni").set_value(CANVAS_URL).run()
    _next(at)
    assert at.header[0].value == "Connect your calendars" and any("Canvas" in e.value for e in at.error)
    at.text_input(key="ob_link_uni").set_value("").run()
    at.text_input(key="ob_link_canvas").set_value(CANVAS_URL).run()     # one good box, one bad box: stays
    at.text_input(key="ob_link_uni").set_value("hello").run()
    _next(at)
    assert at.header[0].value == "Connect your calendars" and at.error


def test_next_with_an_already_connected_link_just_moves_on(fresh):
    at = _student_at(fresh)
    at.text_input(key="ob_link_uni").set_value(UNI_URL).run()
    at.button(key="ob_connect_uni").click().run()
    at.text_input(key="ob_link_uni").set_value(UNI_URL).run()
    _next(at)
    assert at.header[0].value.endswith("Your modules") and not at.error


def test_next_keeps_a_typed_module_habit_and_category(fresh):
    from venato.blocks import grades as gr
    at = _student_at(fresh)
    _next(at, "wiz_skip")
    assert at.header[0].value.endswith("Your modules")
    at.text_input(key="ob_new_module").set_value("Organic Chemistry").run()
    _next(at)                                                    # Next, not Add
    assert [m["name"] for m in gr.modules()] == ["Organic Chemistry"]
    assert at.header[0].value.endswith("What would you track?")
    at.text_input(key="ob_own_name").set_value("Stretch").run()
    at.text_input(key="ob_cat_name").set_value("Lab work").run()
    _next(at)                                                    # one Next saves both
    assert fresh.find_habit("Stretch")
    assert fresh.load_categories().set_index("name").loc["Lab work", "grp"] == "Life"
    assert at.header[0].value.endswith("Your first week")


def test_next_with_a_taken_category_name_stays_on_the_step(fresh):
    fresh.save_category("lab-work", "Lab work", "#112233", "Life")
    at = _student_at(fresh, student=False)
    _next(at, "wiz_skip")
    assert at.header[0].value.endswith("What would you track?")
    at.text_input(key="ob_cat_name").set_value("lab work").run()
    _next(at)
    assert at.header[0].value.endswith("What would you track?") and at.error


def test_the_main_button_says_skip_until_something_is_filled_in(fresh):
    at = AppTest.from_file(APP, default_timeout=60).run()
    _next(at, "ob_student_yes")
    assert at.header[0].value.startswith("Your goals") and _main_label(at) == "Next"    # the term goal is filled in
    at.text_input(key="ob_goal_0").set_value("").run()
    assert _main_label(at) == "Skip"
    at.text_input(key="ob_goal_0").set_value("Run").run()
    assert _main_label(at) == "Next"
    _next(at)
    assert _main_label(at) == "Skip" and at.button(key="wiz_back")
    at.text_input(key="ob_link_uni").set_value(UNI_URL).run()
    assert _main_label(at) == "Next" and at.button(key="wiz_next")
    at.text_input(key="ob_link_uni").set_value("").run()
    assert _main_label(at) == "Skip"
    at.text_input(key="ob_link_uni").set_value(UNI_URL).run()
    at.button(key="ob_connect_uni").click().run()                # connected in this run: Next
    assert _main_label(at) == "Next"
    at.text_input(key="ob_link_canvas").set_value(CANVAS_URL).run()
    assert _main_label(at) == "Next"                             # either box fills the step
    _next(at, "wiz_next")
    at.text_input(key="ob_new_module").set_value("Algebra").run()   # Your modules
    assert _main_label(at) == "Next"
    _next(at)
    assert at.header[0].value == "What would you track?"


def test_the_student_question_is_two_buttons_and_nothing_else(fresh):
    at = AppTest.from_file(APP, default_timeout=60).run()
    assert at.title[0].value == "Welcome to Venato" and not at.radio
    assert {b.key for b in at.button} >= {"ob_student_yes", "ob_student_no", "wiz_skip_all"}
    assert not any(b.key in ("wiz_skip", "wiz_next") for b in at.button)
    assert {b.label for b in at.button if b.key.startswith("ob_student_")} == {"I'm at uni", "Not a student"}
    _next(at, "ob_student_yes")
    assert fresh.load_settings()["student"] is True and at.header[0].value == "Your goals for the next few months"


def test_welcome_shows_the_step_names_and_a_saved_answer(fresh):
    at = AppTest.from_file(APP, default_timeout=60).run()
    assert not any("**Welcome**" in c.value for c in at.caption)     # no step list until the uni question is answered
    assert not any(b.type == "primary" for b in at.button if b.key.startswith("ob_student_"))
    _next(at, "ob_student_yes")
    cap = at.caption[0].value
    assert cap == "Welcome · **Goals** · Calendars · Modules · Track · First week"
    at.button(key="wiz_back").click().run()                      # a re-run: the saved answer is on its button
    assert at.title[0].value == "Welcome to Venato"
    assert at.button(key="ob_student_yes").proto.type == "primary" and at.button(key="ob_student_no").proto.type == "secondary"
    assert at.button(key="wiz_skip_all")


def test_the_calendars_step_explains_other_calendars(fresh):
    at = _student_at(fresh)
    assert [e.label for e in at.expander] == ["Not using Outlook?"]
    assert any("Secret address in iCal format" in m.value for m in at.expander[0].markdown)


def test_finishing_with_a_goal_and_a_habit_puts_goals_and_habits_on_home(fresh):
    from venato import setup_checks
    at = _student_at(fresh, student=False)
    at.text_input(key="ob_goal_0").set_value("Run a 10k").run()
    _skip_to_the_end_after(at, "ob_own_name", "Stretch")
    _next(at, "wiz_finish")
    from venato import home_layout as hl
    from venato.ui import home
    sizes = {k: w.size for k, w in home.catalog().items()}
    on_home = set(hl.keys(hl.normalise(setup_checks.load_settings().get("home"), sizes)))
    assert fresh.find_habit("Stretch") and {"goals", "habits"} <= on_home
    assert at.session_state["page"] == "Home"


def test_welcome_and_home_copy(fresh):
    at = AppTest.from_file(APP, default_timeout=60).run()
    assert at.button(key="wiz_skip_all").label == "Skip setup and start blank"
    assert not any("two minutes" in m.value for m in at.markdown)
    _next(at, "ob_student_no")
    _skip_to_the_end(at)
    assert any("**Edit Home**" in c.value for c in at.caption) and not any("Arrange" in c.value for c in at.caption)


def test_a_click_on_a_stale_skip_button_still_saves_what_was_just_typed(fresh):
    """Typing and clicking at once sends both in one run; the click lands on the button drawn before the typing."""
    from venato.blocks import grades as gr
    at = _student_at(fresh)
    at.text_input(key="ob_link_uni").set_value(UNI_URL)
    at.button(key="wiz_skip").click().run()
    assert at.header[0].value.endswith("Your modules") and fresh.outlook_between("2026-11-16", "2026-11-22")


def test_a_stale_skip_click_on_the_modules_step_still_adds_the_typed_module(fresh):
    from venato.blocks import grades as gr
    at = _student_at(fresh)
    _next(at, "wiz_skip")
    assert at.header[0].value.endswith("Your modules")
    at.text_input(key="ob_new_module").set_value("Algebra")
    at.button(key="wiz_skip").click().run()
    assert [m["name"] for m in gr.modules()] == ["Algebra"] and at.header[0].value == "What would you track?"


def test_picking_only_a_canvas_course_link_says_next(fresh):
    from venato.blocks import grades as gr
    gr.add_module("Organic Chemistry")
    at = _student_at(fresh)
    at.text_input(key="ob_link_uni").set_value(UNI_URL)
    at.text_input(key="ob_link_canvas").set_value(CANVAS_URL).run()
    _next(at)
    for c in [c for c in at.checkbox if c.key.startswith("ob_keep_")]:
        c.set_value(False)
    at.run()
    assert _main_label(at) == "Skip"
    next(s for s in at.selectbox if s.key.startswith("ob_course_")).set_value("Organic Chemistry").run()
    assert _main_label(at) == "Next"


def test_skip_setup_leaves_home_as_it_is_even_with_data(fresh):
    from venato import setup_checks
    from venato.blocks import grades as gr
    gr.add_module("Organic Chemistry")
    fresh.add_goal("Run a 10k", "monthly", MON, 1)
    fresh.add_habit("Stretch")
    setup_checks.save_settings(wizard_done=True, student=True, home=[{"w": "todos", "size": "wide"}])
    at = AppTest.from_file(APP, default_timeout=60).run()
    at.session_state["wizard_open"] = True
    at.run()
    _next(at, "ob_student_yes")
    at.button(key="wiz_back").click().run()
    _next(at, "wiz_skip_all")
    assert setup_checks.load_settings()["home"] == [{"w": "todos", "size": "wide"}]


def _goal_keys(at):
    return [t.key for t in at.text_input if t.key.startswith("ob_goal_") and not t.key.startswith(("ob_goal_why_", "ob_goal_step_"))]


def test_goal_rows_can_be_added_up_to_five_and_removed(fresh):
    at = _student_at(fresh, student=False)
    assert _goal_keys(at) == ["ob_goal_0"] and not [b for b in at.button if b.key.startswith("ob_goal_rm_")]
    assert at.text_input(key="ob_goal_0").placeholder == "e.g. Run a 10k"
    assert at.segmented_control(key="ob_goal_when_0").options == ["3 months", "6 months", "1 year", "Pick an end date"]
    assert at.segmented_control(key="ob_goal_how_0").options == ["Tick it off", "Hours a week", "A number"]
    assert not at.number_input                                   # Tick it off: no box
    for _ in range(4):
        _next(at, "ob_goal_add")
    assert len(_goal_keys(at)) == 5 and not [b for b in at.button if b.key == "ob_goal_add"]
    assert [at.text_input(key=k).placeholder for k in _goal_keys(at)] == [
        "e.g. Run a 10k", "e.g. Read 12 books", "e.g. Get a 2:1", "e.g. Learn to cook 10 meals", "e.g. Save £500"]
    at.text_input(key="ob_goal_0").set_value("Run a 10k")
    at.text_input(key="ob_goal_1").set_value("Read 12 books")
    at.text_input(key="ob_goal_2").set_value("Save £500").run()
    _next(at)                                                    # saved: three goals, no targets
    assert len(fresh.life_goals()) == 3 and fresh.goals_open() == []
    at.button(key="wiz_back").click().run()
    assert at.text_input(key="ob_goal_1").value == "Read 12 books"
    _next(at, "ob_goal_rm_1")                                    # removes only that row's goal
    assert "ob_goal_1" not in _goal_keys(at) and len(_goal_keys(at)) == 4
    assert sorted(g["title"] for g in fresh.life_goals()) == ["Run a 10k", "Save £500"]
    assert at.text_input(key="ob_goal_2").value == "Save £500"
    assert [b for b in at.button if b.key == "ob_goal_add"]


def test_an_hours_a_week_goal_is_an_hours_goal_with_a_category(fresh):
    at = _student_at(fresh, student=False)
    at.text_input(key="ob_goal_0").set_value("Run a 10k")
    at.segmented_control(key="ob_goal_how_0").set_value("Hours a week").run()
    box = at.number_input(key="ob_goal_n_0")
    assert box.min == 0
    box.set_value(3.0).run()
    _next(at)
    g = fresh.goals_open()[0]
    # 3 months from Monday 16 November is 16 February: 92 days, 13 weeks
    assert g["unit"] == "h" and g["category_id"] == "exercise" and g["target"] == 3 * 13 and g["due"] == "2027-02-16"
    assert "exercise" in set(fresh.load_categories()["id"])


def test_hours_goals_get_a_category_even_without_an_example(fresh):
    from venato import setup_checks
    from venato.ui import onboarding
    onboarding.restart()                                         # nothing remembered from another test
    ids = onboarding.save_goals([_row(0, "Practise guitar", "hours", 2, 3)], MON)   # no example: its own category
    g = fresh.get_goal(ids[0]["target"])
    cats = fresh.load_categories().set_index("id")
    assert g["unit"] == "h" and cats.loc[g["category_id"], "name"] == "Practise guitar" and g["target"] == 2 * 13
    onboarding.save_goals([_row(0, "Practise guitar", "number", 30, 3)], MON)      # to a number: no hours
    g = fresh.get_goal(ids[0]["target"])
    assert g["unit"] is None and g["category_id"] is None and g["target"] == 30
    setup_checks.save_settings(student=True)
    st_ids = onboarding.save_goals([_row(1, "Learn Spanish", "hours", 4, 12)], MON)  # a student: Study
    assert fresh.get_goal(st_ids[1]["target"])["category_id"] == "study"
    empty = onboarding.save_goals([_row(2, "Get fit", "hours", None)], MON)[2]       # no hours given: no target
    assert empty["target"] is None and fresh.get_life_goal(empty["goal"])


def test_a_stale_skip_click_on_goals_still_saves_the_typed_goal(fresh):
    at = _student_at(fresh, student=False)
    assert at.header[0].value.startswith("Your goals")
    at.text_input(key="ob_goal_0").set_value("Run a 10k")
    at.button(key="wiz_skip").click().run()
    assert [g["title"] for g in fresh.life_goals()] == ["Run a 10k"]
    assert at.header[0].value.endswith("What would you track?")


def test_fallback_sittings_are_three_spread_out_hours_in_free_time(fresh):
    from venato.ui import onboarding
    onboarding.restart()                                         # nothing remembered from another test
    onboarding.save_goals([_row(0, "Read 12 books"), _row(1, "Save £500", "number", 500, 6),
                           _row(2, "Learn guitar", "hours", 2)], MON)
    goals = onboarding.week_goals()                              # the goal itself when it has no target
    fresh.save_category("reading", "Reading", "#7030A0", "Life")
    fresh.paint("2026-11-17", "plan", fresh.slot_of("09:00"), fresh.slot_of("12:00"), {"label": "Busy", "category_id": None})
    out = onboarding.fallback_sittings(goals, MON)
    read = [s for s in out if s["label"] == "Read 12 books"]
    save = [s for s in out if s["label"] == "Save £500: 500"]                      # named after the target
    assert not [s for s in out if s["label"].startswith("Learn guitar")]           # an hours target gets its own
    assert len(read) == 3 and len({s["date"] for s in read}) == 3 and len(save) == 3
    assert all("2026-11-17" <= s["date"] <= "2026-11-22" for s in out)            # from tomorrow, in the 7 days
    assert all(fresh.slot_of(s["end"]) - fresh.slot_of(s["start"]) == 2 for s in out)
    assert all("09:00" <= s["start"] and s["end"] <= "21:00" for s in out)
    assert read[0] == {**read[0], "date": "2026-11-17", "start": "12:00", "end": "13:00"}    # first free hour
    assert {s["categoryId"] for s in read} == {"reading"} and {s["categoryId"] for s in save} == {None}
    slots = {(s["date"], t) for s in out for t in range(fresh.slot_of(s["start"]), fresh.slot_of(s["end"]))}
    assert len(slots) == 2 * len(out)                                              # no two overlap
    taken = [{"date": "2026-11-17", "start": "12:00", "end": "14:00"}]
    assert all(not (s["date"] == "2026-11-17" and s["start"] < "14:00") for s in onboarding.fallback_sittings(goals, MON, taken))
    assert onboarding.add_first_week(out) == 6
    assert onboarding.fallback_sittings(goals, MON) == []                         # added: nothing more to suggest


def test_first_week_is_never_empty_with_a_goal(fresh):
    at = _student_at(fresh, student=False)
    at.text_input(key="ob_goal_0").set_value("Run a 10k").run()
    _next(at)
    _skip_to_the_end(at)
    assert at.header[0].value.endswith("Your first week")
    assert not any("Nothing to suggest yet" in str(m.value) for m in at.markdown)
    assert any("Run a 10k" in h.value for h in at.get("html"))
    before = fresh.blocks_between("2026-11-16", "2026-11-23", "plan")
    at.button(key="ob_week_add").click().run()
    assert not at.exception, at.exception
    after = fresh.blocks_between("2026-11-16", "2026-11-23", "plan")
    mine = [b for b in after if b["label"] == "Run a 10k"]
    assert not before and len(mine) == 3 and len({b["date"] for b in mine}) == 3
    assert not [b for b in at.button if b.key == "ob_week_add"]                   # nothing more offered


def test_a_plan_block_named_like_the_goal_does_not_hide_its_sittings(fresh):
    from venato.ui import onboarding
    onboarding.restart()
    for d in ("2026-11-17", "2026-11-18", "2026-11-19", "2026-11-20"):            # the user's own, from before setup
        fresh.paint(d, "plan", fresh.slot_of("07:00"), fresh.slot_of("08:00"), {"label": "Study", "category_id": None})
    onboarding.save_goals([_row(0, "Study")], MON)
    out = onboarding.fallback_sittings(onboarding.week_goals(), MON)
    assert len(out) == 3 and len({s["date"] for s in out}) == 3
    onboarding.add_first_week(out)
    assert onboarding.fallback_sittings(onboarding.week_goals(), MON) == []       # added once: not offered again


def test_a_rerun_puts_back_no_home_tile_the_user_removed(fresh):
    from venato import setup_checks
    fresh.add_goal("Run a 10k", "monthly", MON, 1)
    fresh.add_habit("Stretch")
    cells = [{"w": "todos", "size": "wide"}]                     # a saved Home without Habits or Goals
    setup_checks.save_settings(wizard_done=True, home=cells)
    at = AppTest.from_file(APP, default_timeout=60).run()
    at.session_state["wizard_open"] = True
    at.run()
    _next(at, "ob_student_no")
    _skip_to_the_end(at)
    _next(at, "wiz_finish")
    assert setup_checks.load_settings()["home"] == cells


def test_the_goals_step_asks_how_long_why_and_a_first_step(fresh):
    at = _student_at(fresh, student=False)
    assert at.header[0].value == "Your goals for the next few months"
    assert any("**goal**" in m.value and "**target**" in m.value for m in at.markdown)
    assert at.segmented_control(key="ob_goal_how_0").label == "How you'll know"
    assert [e.label for e in at.expander] == ["Why it matters, and a first step"]
    assert not at.date_input
    at.text_input(key="ob_goal_0").set_value("Learn guitar")
    at.segmented_control(key="ob_goal_when_0").set_value("Pick an end date").run()
    at.date_input(key="ob_goal_end_0").set_value(_dt.date(2027, 3, 1))
    at.text_input(key="ob_goal_why_0").set_value("Play at the wedding")
    at.text_input(key="ob_goal_step_0").set_value("Find a teacher").run()
    _next(at)
    (g,) = fresh.life_goals()
    assert g["title"] == "Learn guitar" and g["end_date"] == "2027-03-01" and g["why"] == "Play at the wedding"
    assert [t["title"] for t in fresh.life_goal_todos(g["id"])] == ["Find a teacher"] and fresh.goals_open() == []
    at.button(key="wiz_back").click().run()                      # back: what was saved is shown, and Next changes it
    assert at.date_input(key="ob_goal_end_0").value == _dt.date(2027, 3, 1)
    at.text_input(key="ob_goal_step_0").set_value("Find a cheaper teacher").run()
    _next(at)
    assert len(fresh.life_goals()) == 1
    assert [t["title"] for t in fresh.life_goal_todos(g["id"])] == ["Find a cheaper teacher"]


def test_a_habit_picked_for_a_goal_without_a_target_makes_a_habit_target(fresh):
    at = _student_at(fresh, student=False)
    at.text_input(key="ob_goal_0").set_value("Run a 10k").run()        # Tick it off: no target
    _next(at, "ob_goal_add")
    at.text_input(key="ob_goal_1").set_value("Be calm").run()
    _next(at)
    assert fresh.goals_open() == []
    goals = {g["title"]: g for g in fresh.life_goals()}
    next(c for c in at.checkbox if "Trained" in c.label).set_value(True).run()
    at.text_input(key="ob_own_name").set_value("Breathe").run()
    at.selectbox(key="ob_own_link").set_value("Be calm").run()
    _next(at)
    by = {t["life_goal_id"]: t for t in fresh.goals_open()}
    run, calm = by[goals["Run a 10k"]["id"]], by[goals["Be calm"]["id"]]
    assert run["habit_id"] == fresh.find_habit("Trained")[0] and calm["habit_id"] == fresh.find_habit("Breathe")[0]
    assert run["due"] == goals["Run a 10k"]["end_date"] and run["target"] == 3 * 13 and run["unit"] is None
    assert run["title"] == "Trained: 3 times a week"
    at.button(key="wiz_back").click().run()
    at.button(key="wiz_back").click().run()                      # back to Goals and Next again: the habit target stays
    _next(at)
    assert len(fresh.goals_open()) == 2 and fresh.get_goal(run["id"])["habit_id"]


def test_the_first_week_is_named_after_the_target_else_the_goal(fresh):
    from venato.ui import onboarding
    onboarding.restart()
    onboarding.save_goals([_row(0, "Read more"), _row(1, "Save money", "number", 500)], MON)
    labels = {s["label"] for s in onboarding.fallback_sittings(onboarding.week_goals(), MON)}
    assert labels == {"Read more", "Save money: 500"}                              # one set per goal


def test_module_targets_go_under_the_term_goal_or_none_if_it_was_removed(fresh):
    at = AppTest.from_file(APP, default_timeout=60).run()
    _next(at, "ob_student_yes")
    _next(at, "ob_goal_rm_0")                                    # the term goal removed: one empty row left
    assert at.text_input(key=_goal_keys(at)[0]).value == "" and _main_label(at) == "Skip"
    _next(at, "wiz_skip")
    _next(at, "wiz_skip")                                        # calendars
    at.text_input(key="ob_new_module").set_value("Algebra").run()
    _next(at)
    (t,) = fresh.goals_open()
    assert t["title"] == "Algebra study" and t["life_goal_id"] is None and fresh.life_goals() == []


def test_module_targets_go_under_the_renamed_term_goal(fresh):
    at = AppTest.from_file(APP, default_timeout=60).run()
    _next(at, "ob_student_yes")
    at.text_input(key="ob_goal_0").set_value("Get a 2:1 this year").run()
    _next(at)
    _next(at, "wiz_skip")
    at.text_input(key="ob_new_module").set_value("Algebra").run()
    _next(at)
    (g,) = fresh.life_goals()
    assert g["title"] == "Get a 2:1 this year" and [t["life_goal_id"] for t in fresh.goals_open()] == [g["id"]]


def test_a_rerun_does_not_prefill_the_term_goal_twice(fresh):
    from venato import setup_checks
    fresh.add_life_goal("Do well this term", months=3)
    setup_checks.save_settings(wizard_done=True, student=True)
    at = AppTest.from_file(APP, default_timeout=60).run()
    at.session_state["wizard_open"] = True
    at.run()
    _next(at, "ob_student_yes")
    assert at.text_input(key="ob_goal_0").value == "" and _main_label(at) == "Skip"


def test_home_offers_goals_for_a_long_term_goal_alone(fresh):
    from venato.ui import onboarding
    onboarding.restart()
    assert ("goals", "Goals") not in onboarding.home_picks()
    fresh.add_life_goal("Run a 10k", months=3)
    assert ("goals", "Goals") in onboarding.home_picks()
