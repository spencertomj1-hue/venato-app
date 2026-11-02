from datetime import date

from pathlib import Path

import pytest
from streamlit.testing.v1 import AppTest

APP = str(Path(__file__).resolve().parents[1] / "app.py")


def test_add_list_update_delete(store):
    a = store.add_application(company="  Acme  ", industry="Finance", route="Internship",
                              deadline="2026-12-01", contact="Priya")
    b = store.add_application(company="Beta", status="Applied")
    store.add_application(company="Gamma", deadline=date(2026, 11, 20))
    rows = store.applications()
    assert [r["company"] for r in rows] == ["Gamma", "Acme", "Beta"]       # soonest deadline first, none last
    assert rows[1]["status"] == "To apply" and rows[1]["contact"] == "Priya"
    store.update_application(a, status="Interview", notes="Round 2 on Friday", deadline=None)
    got = store.get_application(a)
    assert got["status"] == "Interview" and got["deadline"] is None and got["notes"] == "Round 2 on Friday"
    store.update_application(b, deadline="2026-11-05T00:00:00", company="")   # table dates come back as timestamps
    assert store.get_application(b)["deadline"] == "2026-11-05" and store.get_application(b)["company"] is None
    store.delete_application(a)
    assert store.get_application(a) is None and len(store.applications()) == 2


def test_rules(store):
    with pytest.raises(ValueError):
        store.add_application(notes="just notes")              # nothing saying what it is
    with pytest.raises(ValueError):
        store.add_application(company="Acme", status="Maybe")
    aid = store.add_application(company="Acme", notes="nan")   # pandas' empty cell
    assert store.get_application(aid)["notes"] is None


def test_search_finds_applications(store):
    store.add_application(company="Acme Bank", route="Graduate scheme", contact="Sam Lee", status="Applied")
    hits = [h for h in store.search("sam") if h["kind"] == "Application"]
    assert hits and hits[0]["title"] == "Acme Bank" and hits[0]["detail"] == "Graduate scheme · Applied"


def test_page_and_table_edits(store):
    store.add_application(company="Acme", status="Applied", deadline="2099-01-01")
    at = AppTest.from_file(APP, default_timeout=60).run()
    at.sidebar.radio[0].set_value("Applications").run()
    assert not at.exception
    assert list(at.sidebar.radio[0].options).index("Applications") == list(at.sidebar.radio[0].options).index("Network") - 1
    assert list(at.sidebar.radio[0].options).index("Network") < list(at.sidebar.radio[0].options).index("Stats")
    assert any("1 in total" in c.value for c in at.caption)

    # What the table's on_change gets: edits by row number, deleted row numbers.
    from venato.ui import applications as ui
    from venato import undo
    store.add_application(company="Beta")
    ids = [r["id"] for r in store.applications()]                 # Acme (has a deadline), Beta
    ui.apply_edits({"edited_rows": {0: {"Status": "Interview", "Deadline": "2099-02-01"}, 1: {"Route": "Spring week"}},
                    "added_rows": [], "deleted_rows": []}, ids)
    rows = {r["company"]: r for r in store.applications()}
    assert rows["Acme"]["status"] == "Interview" and rows["Acme"]["deadline"] == "2099-02-01"
    assert rows["Beta"]["route"] == "Spring week"
    ui.apply_edits({"edited_rows": {}, "added_rows": [], "deleted_rows": [0]}, ids)
    assert [r["company"] for r in store.applications()] == ["Beta"] and undo.pending() == "Deleted Acme"
    undo.restore()
    assert len(store.applications()) == 2


def _tools():
    import importlib
    from venato import tools
    return importlib.reload(tools)


def test_assistant_tools(store):
    tools = _tools()
    r = tools.add_application(company="Acme Bank", route="Internship", status="applied", deadline="2026-12-01")
    assert r.changed and "Acme Bank (Internship): Applied" in r.text
    tools.add_application(company="Beta", industry="Tech")
    assert "Acme Bank" in tools.list_applications(status="Applied").text
    assert "Beta" not in tools.list_applications(status="Applied").text
    assert "Beta" in tools.list_applications(query="tech").text

    # filling in / status changes go straight through; overwriting written text asks first
    tools.edit_application("acme", status="Interview", contact="Priya", notes="Round 1 Friday")
    a = store.applications()[0]
    assert (a["status"], a["contact"], a["notes"]) == ("Interview", "Priya", "Round 1 Friday")
    tools.edit_application("acme", notes="Round 2 Monday", append_notes=True)
    assert store.get_application(a["id"])["notes"] == "Round 1 Friday\nRound 2 Monday"
    r = tools.edit_application("acme", contact="Sam")
    assert r.pending and store.get_application(a["id"])["contact"] == "Priya"
    r.pending.run()
    assert store.get_application(a["id"])["contact"] == "Sam"
    with pytest.raises(tools.ToolError):
        tools.edit_application("acme", status="Maybe")
    with pytest.raises(tools.ToolError):
        tools.edit_application("nothing like it", status="Offer")

    r = tools.delete_application("beta")
    assert r.pending and len(store.applications()) == 2
    r.pending.run()
    assert [x["company"] for x in store.applications()] == ["Acme Bank"]


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

    tools.add_person("Priya")
    tools.log_interaction("Priya", "Coffee; talked about her thesis", "2026-11-01")
    tools.log_interaction("Priya", "Call", "2026-11-02")
    assert "id " in tools.person_history("Priya").text
    r = tools.delete_interaction("Priya", "coffee")
    assert r.pending and len(store.interactions_of(store.net_people()[0]["id"])) == 2
    r.pending.run()
    assert [x["note"] for x in store.interactions_of(store.net_people()[0]["id"])] == ["Call"]

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
               "describe_goal", "describe_person", "describe_application"}
    actions = {n for n, f in inspect.getmembers(tools, inspect.isfunction)
               if f.__module__ == tools.__name__ and not n.startswith("_") and n not in helpers}
    assert actions <= offered, actions - offered
    prompt = assistant.system_prompt()
    assert all(name in prompt for name in ("add_application", "edit_application", "edit_todo", "delete_habit",
                                           "save_review_answers", "delete_interaction"))
