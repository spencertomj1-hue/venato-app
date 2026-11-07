"""Involvement block: organisations, the log, goals with progress, events and tickets, quick, tools."""

import importlib
from datetime import timedelta

import pytest


@pytest.fixture
def inv(store):
    from venato import blocks, tools, quick
    importlib.reload(tools)
    importlib.reload(blocks)
    importlib.reload(quick)
    from venato.blocks import involvement as module
    module = importlib.reload(module)
    blocks.save(blocks.chosen_keys() + ["involvement"])
    return module


def test_orgs_log_and_goals(inv, store):
    today = store.local_today()
    oid = inv.add_org("Oxfam Shop", "Volunteering", "Volunteer", "Saturday shifts")
    inv.add_org("St Mary's", "Faith")
    with pytest.raises(inv.InvError):
        inv.add_org("oxfam shop")
    assert inv.find_org("oxfam")["id"] == oid
    gid = inv.add_goal("oxfam", "20 hours by summer", 20, "hours", today + timedelta(days=90),
                       start=today - timedelta(days=10))
    inv.log("Volunteering", "Oxfam", 4, day=today - timedelta(days=3))
    inv.log("Volunteering", "Oxfam", 3.5)
    inv.log("Volunteering", "Oxfam", 2, day=today - timedelta(days=40))     # before the goal started
    inv.log("Donation", None, amount=10, title="Shelter")
    inv.log("Practice", "St Mary's", title="Sunday service")
    g = next(x for x in inv.goals() if x["id"] == gid)
    assert inv.goal_progress(g) == {"have": 7.5, "pct": pytest.approx(37.5)}
    t = inv.totals(today - timedelta(days=29), today)
    assert t["volunteering"] == 7.5 and t["donated"] == 10 and t["practice"] == 1
    with pytest.raises(inv.InvError):
        inv.log("Donation")
    with pytest.raises(inv.InvError):
        inv.log("Volunteering", hours=30)
    with pytest.raises(inv.InvError):
        inv.log("Volunteering", "Nowhere", 1)
    with pytest.raises(inv.InvError):
        inv.add_goal(None, "x", 5)                                         # target without a unit
    inv.delete_org(oid)
    assert not inv.goals(oid) and len(inv.entries()) == 5


def test_events(inv, store):
    today = store.local_today()
    eid = inv.add_event("Ball", today + timedelta(days=3), start="19:30", ticket="Need to buy", price=45,
                        url="https://tickets.example")
    with pytest.raises(inv.InvError):
        inv.add_event("Bad", today, url="javascript:alert(1)")
    with pytest.raises(inv.InvError):
        inv.add_event("Bad", today, start="25:00")
    assert [e["title"] for e in inv.upcoming(7)] == ["Ball"]
    inv.update_event(eid, ticket="Bought")
    assert inv.upcoming(7)[0]["ticket"] == "Bought"
    inv.attended(eid, 3)
    assert inv.entries()[0]["kind"] == "Event" and inv.entries()[0]["hours"] == 3


def test_quick_and_tools(inv):
    from venato import quick, assistant
    inv.add_org("Oxfam", "Volunteering")
    inv.add_org("St Mary's", "Faith")
    assert "volunteering · 3 h for Oxfam" in quick.handle("volunteered 3h at oxfam").reply
    assert "£10.00" in quick.handle("donated £10").reply
    assert "practice for St Mary's" in quick.handle("went to church").reply
    assert quick.handle("volunteered 2 hours at the zoo") is None       # unknown: left to Claude
    assert "Treasurer" in inv.tool_org("Hiking Society", "Society", "Treasurer").text
    assert "Updated" in inv.tool_org("Hiking Society", duties="Runs the accounts").text
    assert inv.find_org("hiking")["duties"] == "Runs the accounts"
    inv.tool_goal("Run 2 trips", "Hiking Society", 2, "times")
    inv.tool_event("Snowdon trip", (inv.store.local_today() + timedelta(days=2)).isoformat(), "Hiking Society")
    out = inv.tool_summary(30).text
    assert "3 h volunteering" in out and "Run 2 trips" in out and "Snowdon trip" in out and "Treasurer" in out
    names = {t[0] for t in assistant.tool_specs()}
    assert {"add_organisation", "log_involvement", "add_event", "add_involvement_goal", "involvement_summary"} <= names
    assert "Snowdon trip" in inv._context()
