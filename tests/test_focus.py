"""Focus block: the timer's life (start, pause, run out, break), logging, timetable, tools."""

import importlib
from pathlib import Path

import pytest
from streamlit.testing.v1 import AppTest

APP = str(Path(__file__).resolve().parents[1] / "app.py")
T0 = 1_800_000_000.0          # a fixed "now" (Unix seconds)


@pytest.fixture
def focus(store):
    from venato import blocks, tools
    importlib.reload(tools)
    importlib.reload(blocks)
    from venato.blocks import focus as module
    module = importlib.reload(module)
    blocks.save(blocks.chosen_keys() + ["focus"])
    return module


def test_timer_runs_out_logs_and_starts_a_break(focus, store):
    focus.start("Essay", 25, "focus", now=T0)
    focus.pause(now=T0 + 600)
    focus.resume(now=T0 + 900)                                    # 5 minutes paused
    r = focus.running()
    assert focus.remaining(r, now=T0 + 1000) == pytest.approx(25 * 60 - 700)
    assert focus.finish_if_due(now=T0 + 1500) == ""               # not done yet
    msg = focus.finish_if_due(now=T0 + 1800 + 5)                  # 25 min of focus + 5 paused, just now
    assert "Essay: 25 min done" in msg and "Break: 5 min" in msg
    r = focus.running()
    assert r["kind"] == "break" and r["planned"] == 5 and r["cycle"] == 1
    day = focus._local(T0).date()
    s = focus.sessions(day, day)[0]
    assert (s["label"], s["kind"], s["minutes"], s["completed"]) == ("Essay", "focus", 25.0, 1)


def test_long_break_and_no_break_after_a_long_absence(focus, store):
    focus.save_settings(long_every=2)
    focus.start("A", 25, "focus", cycle=1, now=T0)
    assert "Long break" in focus.finish_if_due(now=T0 + 1500)
    focus.cancel()
    focus.start("B", 25, "focus", now=T0)
    focus.finish_if_due(now=T0 + 1500 + 3600)                     # ran out an hour ago (app closed)
    assert focus.running() is None


def test_stop_early_stopwatch_and_timetable(focus, store):
    focus.start("Reading", 50, "focus", now=T0)
    session, note = focus.stop(now=T0 + 20 * 60)
    assert session["minutes"] == 20 and session["completed"] == 0
    focus.start("Emails", None, "track", now=T0)                  # stopwatch: no limit
    assert focus.remaining(focus.running()) is None
    session, _ = focus.stop(now=T0 + 45 * 60)
    assert session["minutes"] == 45 and session["kind"] == "track"


def test_manual_log_goes_into_actual(focus, store):
    from venato import tools
    tools.edit_category("Study", create=True, colour="#1B7F3B") if "Study" not in set(store.load_categories()["name"]) else None
    today = store.local_today()
    session, note = focus.log_manual("Revision", 60, today, "10:00", store.resolve_category(category="Study"))
    assert "10:00–11:00" in note
    blocks = store.blocks_between(today.isoformat(), today.isoformat(), "actual")
    assert [(b["start"], b["end"], b["label"]) for b in blocks] == [("10:00", "11:00", "Revision")]
    _, note = focus.log_manual("Revision again", 30, today, "10:00", store.resolve_category(category="Study"))
    assert "already" in note                                      # never overwrites the timetable
    by_label, _ = focus.totals(today, today)
    assert by_label == {"Revision": 60, "Revision again": 30} and focus.streak(today) == 1


def test_tools_and_quick_commands(focus, store):
    from venato import quick
    importlib.reload(quick)
    r = quick.handle("focus 50 on essay")
    assert r and "Essay" in r.reply and focus.running()["planned"] == 50
    assert "50" in focus.tool_status().text
    assert quick.handle("pause focus").changed and focus.running()["paused_at"]
    quick.handle("stop focus")
    assert focus.running() is None
    assert "Essay" in focus.tool_summary(7).text


def test_page_renders(focus, store):
    at = AppTest.from_file(APP, default_timeout=60).run()
    at.sidebar.radio[0].set_value("Focus").run()
    assert not at.exception
    focus.start("Essay", 25, "focus")
    at.run()
    assert not at.exception
