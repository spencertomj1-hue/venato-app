from datetime import date

from pathlib import Path

import pytest
from streamlit.testing.v1 import AppTest

APP = str(Path(__file__).resolve().parents[1] / "app.py")


@pytest.fixture
def apps(store):
    """The Applications block (its store functions and Claude's tools)."""
    import importlib
    from venato import tools
    importlib.reload(tools)                       # picks up the reloaded store
    from venato.blocks import applications
    from venato import blocks
    blocks.save([*blocks.chosen_keys(), "applications"])      # optional now: switched on for these tests
    return applications


def test_add_list_update_delete(store, apps):
    a = apps.add_application(company="  Acme  ", industry="Finance", route="Internship",
                              deadline="2026-12-01", contact="Priya")
    b = apps.add_application(company="Beta", status="Applied")
    apps.add_application(company="Gamma", deadline=date(2026, 11, 20))
    rows = apps.applications()
    assert [r["company"] for r in rows] == ["Gamma", "Acme", "Beta"]       # soonest deadline first, none last
    assert rows[1]["status"] == "To apply" and rows[1]["contact"] == "Priya"
    apps.update_application(a, status="Interview", notes="Round 2 on Friday", deadline=None)
    got = apps.get_application(a)
    assert got["status"] == "Interview" and got["deadline"] is None and got["notes"] == "Round 2 on Friday"
    apps.update_application(b, deadline="2026-11-05T00:00:00", company="")   # table dates come back as timestamps
    assert apps.get_application(b)["deadline"] == "2026-11-05" and apps.get_application(b)["company"] is None
    apps.delete_application(a)
    assert apps.get_application(a) is None and len(apps.applications()) == 2


def test_rules(store, apps):
    with pytest.raises(ValueError):
        apps.add_application(notes="just notes")              # nothing saying what it is
    with pytest.raises(ValueError):
        apps.add_application(company="Acme", status="Maybe")
    aid = apps.add_application(company="Acme", notes="nan")   # pandas' empty cell
    assert apps.get_application(aid)["notes"] is None


def test_search_finds_applications(store, apps):
    apps.add_application(company="Acme Bank", route="Graduate scheme", contact="Sam Lee", status="Applied")
    hits = [h for h in store.search("sam") if h["kind"] == "Application"]
    assert hits and hits[0]["title"] == "Acme Bank" and hits[0]["detail"] == "Graduate scheme · Applied"


def test_page_and_table_edits(store, apps):
    from venato import blocks
    blocks.save([*blocks.chosen_keys(), "network"])
    apps.add_application(company="Acme", status="Applied", deadline="2099-01-01")
    at = AppTest.from_file(APP, default_timeout=60).run()
    at.sidebar.radio[0].set_value("Applications").run()
    assert not at.exception
    assert list(at.sidebar.radio[0].options).index("Applications") == list(at.sidebar.radio[0].options).index("Network") - 1
    assert list(at.sidebar.radio[0].options).index("Network") > list(at.sidebar.radio[0].options).index("Review")
    assert any("1 in total" in c.value for c in at.caption)

    # What the table sends: one op per change.
    from venato.ui import applications as ui
    from venato import undo
    apps.add_application(company="Beta")
    acme, beta = [r["id"] for r in apps.applications()]           # Acme (has a deadline), Beta
    ui.apply_op({"kind": "edit", "id": acme, "field": "status", "value": "Interview"})
    ui.apply_op({"kind": "edit", "id": acme, "field": "deadline", "value": "2099-02-01"})
    ui.apply_op({"kind": "edit", "id": beta, "field": "route", "value": "Spring week"})
    ui.apply_op({"kind": "edit", "id": beta, "field": "status", "value": "Nonsense"})   # ignored
    ui.apply_op({"kind": "edit", "id": beta, "field": "id", "value": "x"})            # not a column: ignored
    rows = {r["company"]: r for r in apps.applications()}
    assert rows["Acme"]["status"] == "Interview" and rows["Acme"]["deadline"] == "2099-02-01"
    assert rows["Beta"]["route"] == "Spring week" and rows["Beta"]["status"] == "To apply"
    ui.apply_op({"kind": "edit", "id": beta, "field": "route", "value": ""})            # cleared
    assert apps.get_application(beta)["route"] is None
    ui.apply_op({"kind": "delete", "id": acme})
    assert [r["company"] for r in apps.applications()] == ["Beta"] and undo.pending() == "Deleted Acme"
    undo.restore()
    assert len(apps.applications()) == 2


def _tools():
    import importlib
    from venato import tools
    return importlib.reload(tools)


def test_assistant_tools(store, apps):
    tools = _tools()
    r = apps.tool_add_application(company="Acme Bank", route="Internship", status="applied", deadline="2026-12-01")
    assert r.changed and "Acme Bank (Internship): Applied" in r.text
    apps.tool_add_application(company="Beta", industry="Tech")
    assert "Acme Bank" in apps.tool_list_applications(status="Applied").text
    assert "Beta" not in apps.tool_list_applications(status="Applied").text
    assert "Beta" in apps.tool_list_applications(query="tech").text

    # filling in / status changes go straight through; overwriting written text asks first
    apps.tool_edit_application("acme", status="Interview", contact="Priya", notes="Round 1 Friday")
    a = apps.applications()[0]
    assert (a["status"], a["contact"], a["notes"]) == ("Interview", "Priya", "Round 1 Friday")
    apps.tool_edit_application("acme", notes="Round 2 Monday", append_notes=True)
    assert apps.get_application(a["id"])["notes"] == "Round 1 Friday\nRound 2 Monday"
    r = apps.tool_edit_application("acme", contact="Sam")
    assert r.pending and apps.get_application(a["id"])["contact"] == "Priya"
    r.pending.run()
    assert apps.get_application(a["id"])["contact"] == "Sam"
    with pytest.raises(tools.ToolError):
        apps.tool_edit_application("acme", status="Maybe")
    with pytest.raises(tools.ToolError):
        apps.tool_edit_application("nothing like it", status="Offer")

    r = apps.tool_delete_application("beta")
    assert r.pending and len(apps.applications()) == 2
    r.pending.run()
    assert [x["company"] for x in apps.applications()] == ["Acme Bank"]


def test_assistant_reaches_every_section(store):
    """The tools added so Claude can change everything the pages can."""
    tools = _tools()
    tools.add_habit("Gym")
    with store.db() as conn:
        store.set_habit_done(conn, store.find_habit("Gym")[0], "2026-11-01", True)
    tools.rename_habit("Gym", "Gym session")
    assert [n for _, n in store.get_habits()] == ["Gym session"]
    tools.add_habit("Read")
    with pytest.raises(tools.ToolError):
        tools.rename_habit("Read", "gym session")
    r = tools.delete_habit("Gym session")
    assert "1 tick" in r.pending.summary
    r.pending.run()
    assert [n for _, n in store.get_habits()] == ["Read"]

    tools.add_todo("Finish problem sheet", "daily")
    tools.edit_todo("problem sheet", title="Finish problem sheet 4", notes="Q3 is hard", move_to="weekly")
    with store.db() as conn:
        (tid,) = conn.execute("SELECT id FROM todos").fetchone()
    t = store.get_todo(tid)
    assert (t["title"], t["notes"], t["period"]) == ("Finish problem sheet 4", "Q3 is hard", "weekly")

    tools.save_review_answers(went_well="Gym 3 times", date="2026-11-02")
    week = store.week_start_of(date(2026, 11, 2)).isoformat()
    assert next(r for r in store.reviews() if r["week_start"] == week)["went_well"] == "Gym 3 times"
    r = tools.save_review_answers(went_well="Slept well", to_change="Less phone", date="2026-11-02")
    assert r.pending
    r.pending.run()
    got = next(r for r in store.reviews() if r["week_start"] == week)
    assert (got["went_well"], got["to_change"]) == ("Slept well", "Less phone")


def test_every_tool_is_registered(store):
    """Every public action in tools.py is offered to Claude, and the prompt mentions it."""
    import inspect
    import importlib
    from venato import assistant
    tools = _tools()
    assistant = importlib.reload(assistant)
    offered = {spec[0] for spec in assistant.TOOL_SPECS}
    helpers = {"nice_day", "describe_block", "todo_list_name", "describe_todo", "describe_deadline",
               "describe_goal",
               "resolve_goal",           # the Goals page's negotiation buttons (not one of Claude's tools)
               "goal_spots"}             # where plan_goals puts time (the Timetable's suggested sittings)
    actions = {n for n, f in inspect.getmembers(tools, inspect.isfunction)
               if f.__module__ == tools.__name__ and not n.startswith("_") and n not in helpers}
    assert actions <= offered, actions - offered
    prompt = assistant.system_prompt()
    assert all(name in prompt for name in ("edit_todo", "delete_habit", "save_review_answers"))


def test_block_offers_its_tools_prompt_and_snapshot(store, apps):
    from datetime import datetime
    from venato import assistant
    assert {spec[0] for spec in apps.TOOLS} <= {spec[0] for spec in assistant.tool_specs()}
    assert all(name in assistant.system_prompt() for name in ("add_application", "edit_application"))
    assert assistant._status("mcp__venato__list_applications") == "Looking that up"
    assert assistant._status("mcp__venato__edit_application") == "Updating your applications"
    apps.tool_add_application(company="Acme", status="Interview")
    apps.tool_add_application(company="Old Co", status="Rejected")
    text = assistant.with_context("hi", datetime(2026, 11, 3, 9, 30))
    assert "Acme" in text and "Old Co" not in text               # finished applications are left out

