"""Network: store rules and the Network page (AppTest), with the throwaway data folder."""

from datetime import date
from pathlib import Path

import pytest
from streamlit.testing.v1 import AppTest

APP = str(Path(__file__).resolve().parents[1] / "app.py")


@pytest.fixture
def net(store):
    """The Network block (its store functions and Claude's tools)."""
    import importlib
    from venato import tools
    importlib.reload(tools)                       # picks up the reloaded store
    from venato.blocks import network
    from venato import blocks
    blocks.save([*blocks.chosen_keys(), "network"])      # optional now: switched on for these tests
    return network


@pytest.fixture
def tools(net):
    from venato import tools
    return tools


def test_people_links_and_groups(store, net):
    assert [g["name"] for g in net.net_groups()] == ["Family", "Friends", "Uni", "Work", "Mentors", "Other"]
    sam = net.add_person("Sam", "Uni friend", "Google", net.find_net_group("FRIENDS"))
    alex = net.add_person("Alex")
    net.link_people(alex["id"], sam["id"], "Football")
    net.link_people(sam["id"], alex["id"], "Five-a-side")          # same pair, either order: one row
    assert net.net_links() == [{"a": min(sam["id"], alex["id"]), "b": max(sam["id"], alex["id"]), "reason": "Five-a-side"}]
    assert [(o["name"], r) for o, r in net.connections_of(sam["id"])] == [("Alex", "Five-a-side")]
    with pytest.raises(ValueError):
        net.link_people(sam["id"], sam["id"])
    net.update_person(sam["id"], works_for="", group_id=None)       # clear both
    assert (net.get_person(sam["id"])["works_for"], net.get_person(sam["id"])["group_id"]) == (None, None)
    net.update_person(sam["id"], description="Best man")            # the group stays as it is
    assert net.get_person(sam["id"])["description"] == "Best man"
    net.delete_person(alex["id"])
    assert net.net_links() == []


def test_sub_groups(store, net):
    northfield = net.add_net_group("Northfield", "#123abc")
    society = net.add_net_group("Physics Society", parent_id=northfield)                     # takes Northfield's colour
    lab = net.add_net_group("Robotics Lab", parent_id=northfield)
    names = [g["name"] for g in net.net_groups()]
    assert names[names.index("Northfield"):names.index("Northfield") + 3] == ["Northfield", "Physics Society", "Robotics Lab"]
    assert next(g for g in net.net_groups() if g["id"] == society)["colour"] == "#123ABC"
    assert net.group_path(society) == "Northfield › Physics Society"
    with pytest.raises(ValueError):
        net.update_net_group(northfield, parent_id=society)                       # no loops
    net.update_net_group(lab, parent_id=society)
    assert net.group_path(lab) == "Northfield › Physics Society › Robotics Lab"
    p = net.add_person("Sam", group_id=society)
    net.delete_net_group(society)                                              # people and sub-groups move up
    assert net.get_person(p["id"])["group_id"] == northfield
    assert net.group_path(lab) == "Northfield › Robotics Lab"


def test_find_people(store, net):
    net.add_person("Sam Smith")
    net.add_person("Sam")
    assert [p["name"] for p in net.find_people("sam")] == ["Sam"]           # exact wins
    assert [p["name"] for p in net.find_people("smi")] == ["Sam Smith"]


def test_page_and_edit_dialogs(store, net):
    northfield = net.add_net_group("Northfield")
    sam = net.add_person("Sam", group_id=net.add_net_group("Physics Society", parent_id=northfield))
    alex = net.add_person("Alex")
    net.link_people(sam["id"], alex["id"], "Football")
    at = AppTest.from_file(APP, default_timeout=60).run()
    at.sidebar.radio[0].set_value("Network").run()
    assert not at.exception and at.header[0].value == "Network"

    # What a card's buttons do; each opens its dialog. (AppTest reruns the whole page on a click
    # inside a dialog, unlike the browser, so the clicking is checked in a real browser instead.)
    at.session_state["net_edit"] = {"kind": "person", "id": sam["id"]}
    at.run()
    assert not at.exception
    assert at.text_input(key=f"net_edit_{sam['id']}_name").value == "Sam"
    assert at.button(key=f"net_unlink_{alex['id']}")
    at.session_state["net_edit"] = {"kind": "group", "id": northfield}
    at.run()
    assert at.text_input(key=f"net_editg_{northfield}_name").value == "Northfield"
    for edit in ({"kind": "new_person", "group": northfield}, {"kind": "new_group", "parent": northfield}):
        at.session_state["net_edit"] = edit
        at.run()
        assert not at.exception
    at.run()                                             # and they don't reopen on the next run
    assert not [t for t in at.text_input if t.key and t.key.startswith("net_")]


def test_interaction_log(store, net):
    sam = net.add_person("Sam")
    a = net.add_interaction(sam["id"], "Coffee; talked about her thesis", "2026-10-28")
    net.add_interaction(sam["id"], "Football", "2026-10-30")
    assert [i["note"] for i in net.interactions_of(sam["id"])] == ["Football", "Coffee; talked about her thesis"]
    assert net.last_interactions() == {sam["id"]: "2026-10-30"}
    net.delete_interaction(a)
    assert len(net.interactions_of(sam["id"])) == 1
    with pytest.raises(ValueError):
        net.add_interaction(sam["id"], "  ", "2026-10-30")
    net.delete_person(sam["id"])                                   # goes with the person
    assert net.last_interactions() == {}


def test_person_dialog_shows_interactions(store, net):
    sam = net.add_person("Sam")
    net.add_interaction(sam["id"], "Coffee in town", "2026-10-28")
    at = AppTest.from_file(APP, default_timeout=60).run()
    at.sidebar.radio[0].set_value("Network").run()
    at.session_state["net_edit"] = {"kind": "person", "id": sam["id"]}
    at.run()
    assert not at.exception
    assert any("Coffee in town" in m.value for m in at.markdown)


# --- Claude's tools ---

@pytest.fixture
def friday(store, monkeypatch):
    """Pin "today" (Europe/London) to Friday 30 Oct 2026."""
    monkeypatch.setattr(store, "local_today", lambda: date(2026, 10, 30))


def test_add_people_and_connect(tools, net):
    r = net.tool_add_person("Sam", "Friend from uni", "Google", "friends")
    assert r.changed and "Sam (Friends, works for Google)" in r.text
    assert "already someone called Sam" in net.tool_add_person("sam").text
    net.tool_add_person("Alex Jones", group="Work")
    assert net.tool_connect_people("sam", "alex", "Football").text == "Connected Sam and Alex Jones (Football)."
    assert net.tool_connect_people("Alex", "Sam", "Five-a-side").changed           # updates the reason
    text = net.tool_find_people().text
    assert "Knows Alex Jones (Five-a-side)" in text and text.startswith("Groups: Family, Friends")
    found = net.tool_find_people("Jones").text.splitlines()[1:]
    assert len(found) == 1 and "Alex Jones" in found[0]                         # only Alex matches
    with pytest.raises(tools.ToolError, match="no group"):
        net.tool_add_person("Kim", group="Rowing")
    assert net.tool_add_group("Rowing", colour="#123abc").changed
    assert "Rowing" in net.tool_add_person("Kim", group="rowing").text
    with pytest.raises(tools.ToolError, match="no one called"):
        net.tool_connect_people("Sam", "Nobody")
    with pytest.raises(tools.ToolError, match="themselves"):
        net.tool_connect_people("Sam", "sam")


def test_update_and_ambiguous_people(tools, net):
    net.tool_add_person("Sam Smith")
    net.tool_add_person("Sam Lee")
    with pytest.raises(tools.ToolError, match="More than one"):
        net.tool_update_person("sam", works_for="BBC")
    assert "works for BBC" in net.tool_update_person("sam lee", works_for="BBC", group="Work").text
    assert "(works for BBC)" in net.tool_update_person("Sam Lee", clear_group=True).text


def test_disconnect_and_delete_need_confirm(tools, net):
    net.tool_add_person("Sam")
    net.tool_add_person("Alex")
    net.tool_connect_people("Sam", "Alex")
    r = net.tool_disconnect_people("Sam", "Alex")
    assert r.pending and r.pending.summary == "Remove the connection between Sam and Alex"
    assert net.net_links()
    r.pending.run()
    assert net.net_links() == []
    net.tool_connect_people("Sam", "Alex")
    r = net.tool_delete_person("Sam")
    assert r.pending.summary == "Remove Sam from the network, with their 1 connection"
    r.pending.run()
    assert [p["name"] for p in net.net_people()] == ["Alex"] and net.net_links() == []


def test_sub_group_tools(tools, net):
    assert net.tool_add_group("Northfield", colour="#123456").changed
    assert net.tool_add_group("Physics Society", inside="northfield").text == "Added the group Northfield › Physics Society."
    with pytest.raises(tools.ToolError, match="no group"):
        net.tool_add_group("Lab", inside="Oxford")
    net.tool_add_person("Sam", group="physics society")
    assert "Sam (Northfield › Physics Society)" in net.tool_find_people().text
    assert "Northfield (Physics Society)" in net.tool_find_people().text.splitlines()[0]
    assert "Chess" in net.tool_edit_group("Physics Society", name="Chess Club", top_level=True).text.replace("Chess Club", "Chess")
    with pytest.raises(tools.ToolError, match="inside itself"):
        net.tool_edit_group("Northfield", inside="Northfield")
    r = net.tool_delete_group("Chess Club")
    assert r.pending.summary == "Delete the group Chess Club; its people and sub-groups move to the top level"
    r.pending.run()
    assert net.find_people("Sam")[0]["group_id"] is None


def test_log_interaction_tools(tools, net, friday):
    net.tool_add_person("Priya")
    assert net.tool_log_interaction("priya", "Coffee; talked about her thesis").text == \
        "Logged for Priya on Fri 30 Oct: Coffee; talked about her thesis"
    net.tool_log_interaction("Priya", "Lab meeting", date="2026-10-20")
    assert [l.split(", ", 1)[1] for l in net.tool_person_history("Priya").text.splitlines()[1:]] == [
        "Fri 30 Oct (2026-10-30): Coffee; talked about her thesis", "Tue 20 Oct (2026-10-20): Lab meeting"]
    assert "Last interaction Fri 30 Oct: Coffee" in net.tool_find_people().text
    with pytest.raises(tools.ToolError, match="no one called"):
        net.tool_log_interaction("Zed", "Lunch")


def test_interaction_tools_and_confirm(tools, net):
    net.tool_add_person("Priya")
    net.tool_log_interaction("Priya", "Coffee; talked about her thesis", "2026-11-01")
    net.tool_log_interaction("Priya", "Call", "2026-11-02")
    assert "id " in net.tool_person_history("Priya").text
    r = net.tool_delete_interaction("Priya", "coffee")
    assert r.pending and len(net.interactions_of(net.net_people()[0]["id"])) == 2
    r.pending.run()
    assert [x["note"] for x in net.interactions_of(net.net_people()[0]["id"])] == ["Call"]


def test_block_offers_its_tools_and_prompt(store, net):
    from venato import assistant
    names = {spec[0] for spec in assistant.tool_specs()}
    assert {spec[0] for spec in net.TOOLS} <= names
    prompt = assistant.system_prompt()
    assert all(name in prompt for name in ("add_person", "add_group", "log_interaction", "delete_interaction"))
    assert assistant._status("mcp__venato__connect_people") == "Updating your network"
    assert assistant._status("mcp__venato__person_history") == "Looking that up"


def test_search_and_weekly_review(store, net):
    from venato import review
    p = net.add_person("Priya", "Lab partner", "University")
    net.add_interaction(p["id"], "Coffee, talked about her thesis", "2026-10-21")
    met = [r for r in store.search("thesis") if r["kind"] == "Met"]
    assert met and (met[0]["title"], met[0]["detail"]) == ("Coffee, talked about her thesis", "Priya")
    s = review.summary(date(2026, 10, 19))
    sec = next(x for x in s["sections"] if x["key"] == "network")
    assert sec == {"key": "network", "title": "People you saw", "lines": ["Priya · Coffee, talked about her thesis"]}
    assert s["has_data"] and "People you saw: Priya · Coffee" in review.as_text(s)


def test_search_result_opens_the_person(store, net):
    net.add_person("Priya", "Lab partner", "University")
    at = AppTest.from_file(APP, default_timeout=60).run()
    at.text_input(key="global_search").set_value("priya").run()
    assert not at.exception
    assert any("Lab partner" in h.value for h in at.get("html"))
    person = next(b for b in at.button if b.key and b.key.startswith("search_open_") and "Person" in b.key)
    person.click().run()
    assert not at.exception and at.sidebar.radio[0].value == "Network"

