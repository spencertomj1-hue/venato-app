"""Network's Meetings: a timetable category that comes with Network, and meetings marked done are
logged as interactions with the people they name. Uses the `store` fixture's data folder."""

from pathlib import Path

import pytest
from streamlit.testing.v1 import AppTest
from nav_helpers import goto

APP = str(Path(__file__).resolve().parents[1] / "app.py")


@pytest.fixture
def net(store):
    import importlib
    from venato import tools
    importlib.reload(tools)
    from venato.blocks import network
    from venato import blocks
    blocks.save([*blocks.chosen_keys(), "network"])
    return network


def done(cid, label, status="done", bid="outlook:abc", day="2026-11-20"):
    return {"kind": "set_status", "id": bid, "status": status, "date": day, "start": "10:00", "end": "10:30",
            "label": label, "categoryId": cid}


def test_meetings_category_is_made_once_and_titles_mean_it(store, net):
    net.ensure_meetings()
    assert net.MEETINGS_ID in set(store.load_categories()["id"])
    assert store.match_category("Call with Nina") == net.MEETINGS_ID
    assert store.match_category("Coffee - Sam") == net.MEETINGS_ID
    with store.db() as conn:                                   # the user deletes it
        conn.execute("DELETE FROM tt_categories WHERE id = ?", (net.MEETINGS_ID,))
    net.ensure_meetings()                                      # made once: deleting it is respected
    assert net.MEETINGS_ID not in set(store.load_categories()["id"])


def test_people_named_in_a_title(store, net):
    nina = net.add_person("Nina Smith")
    sam = net.add_person("Sam Jones")
    net.add_person("Sam Lee")
    assert [p["id"] for p in net.people_named_in("Call with Nina")] == [nina["id"]]
    assert [p["id"] for p in net.people_named_in("Coffee with Sam Jones")] == [sam["id"]]
    assert net.people_named_in("Coffee with Sam") == []              # two Sams: can't tell which
    assert net.people_named_in("Marina's party") == []               # whole words only


def test_done_meeting_logs_and_not_done_takes_it_back(store, net):
    from venato.ui import timetable
    net.ensure_meetings()
    nina = net.add_person("Nina Smith")
    timetable._apply(done(net.MEETINGS_ID, "Call with Nina"))
    assert [i["note"] for i in net.interactions_of(nina["id"])] == ["Meeting: Call with Nina"]
    timetable._apply(done(net.MEETINGS_ID, "Call with Nina"))       # marked again: still once
    assert len(net.interactions_of(nina["id"])) == 1
    timetable._apply(done(net.MEETINGS_ID, "Call with Nina", status="missed"))
    assert net.interactions_of(nina["id"]) == []
    timetable._apply(done("work", "Call with Nina"))                 # not a Meetings one: nothing logged
    assert net.interactions_of(nina["id"]) == []


def test_meeting_naming_nobody_asks_who(store, net):
    import streamlit as st
    from venato.ui import timetable
    net.ensure_meetings()
    timetable._apply(done(net.MEETINGS_ID, "Team meeting", bid="b1"))
    assert st.session_state["meeting_who"]["id"] == "b1"
    st.session_state.pop("meeting_who")
    sam = net.add_person("Sam")
    net.log_meeting("b1", "2026-11-20", "Team meeting", [sam["id"]])  # what the pop-up's "Log it" does
    assert net.meeting_logged("b1") and net.interactions_of(sam["id"])[0]["date"] == "2026-11-20"


def test_timetable_page_has_meetings_only_with_network(store):
    at = AppTest.from_file(APP, default_timeout=60).run()
    goto(at, "Timetable")
    assert not at.exception, at.exception
    assert "meetings" not in set(store.load_categories()["id"])
    from venato import blocks
    blocks.save([*blocks.chosen_keys(), "network"])
    goto(at, "Timetable")
    assert not at.exception, at.exception
    assert "meetings" in set(store.load_categories()["id"])
