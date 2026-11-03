"""The assistant's fast path pieces that don't need a real Claude: the [Now] snapshot,
a prompt that stays the same (so sessions and caching work), tool status labels and jobs."""

import importlib
from datetime import datetime


def _assistant():
    from venato import assistant, tools
    importlib.reload(tools)
    return importlib.reload(assistant)


def test_system_prompt_is_stable(store):
    a = _assistant()
    assert a.system_prompt() == a.system_prompt()                 # no clock in it: cacheable, reusable
    assert "[Now]" in a.system_prompt()
    assert a.DEFAULT_MODEL == "claude-haiku-5-5" and a.DEFAULT_EFFORT == "low"


def test_context_snapshot(store):
    from venato import tools
    a = _assistant()
    today = store.local_today().isoformat()
    tools.add_block(today, "plan", "10:00", "12:00", "Lecture")
    tools.add_habit("Gym")
    tools.add_todo("Finish essay", "daily")
    tools.add_application(company="Acme", status="Interview")
    tools.add_application(company="Old Co", status="Rejected")
    text = a.with_context("hi", datetime(2026, 11, 3, 9, 30))
    assert text.startswith("[Now]\nIt is Tuesday 03 November 2026, 09:30") and text.endswith("[/Now]\n\nhi")
    for bit in ("Lecture", "Gym", "Finish essay", "Acme"):
        assert bit in text, bit
    assert "Old Co" not in text                                  # finished applications are left out
    a.CONTEXT_EXTRAS.append(("Broken", lambda: 1 / 0))           # a failing section is skipped, not fatal
    try:
        assert "Broken" not in a.context()
    finally:
        a.CONTEXT_EXTRAS.clear()


def test_tool_status_labels(store):
    a = _assistant()
    assert a._status("mcp__venato__add_block") == "Updating your timetable"
    assert a._status("mcp__venato__list_applications") == "Looking that up"
    assert a._status("mcp__venato__edit_application") == "Updating your applications"
    assert a._status("mcp__venato__plan_time") == "Finding free time"


def test_job_gives_up_after_the_timeout(store, monkeypatch):
    a = _assistant()
    job = a.Job()
    monkeypatch.setattr(a, "TURN_TIMEOUT", 0)
    assert job.done and "too long" in job.turn.error
    assert a.Job.finished(a.Turn(reply="hi")).wait().reply == "hi"
