"""Phase 2: finding modules and Canvas courses in the real-feed fixtures (pure functions, no network)."""

import importlib
from datetime import date
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

FIXTURES = Path(__file__).parent / "fixtures"
CANVAS = (FIXTURES / "canvas_sample.ics").read_bytes()
UNI = (FIXTURES / "uni_timetable_sample.ics").read_bytes()
LONDON = ZoneInfo("Europe/London")
CANVAS_URL = "https://canvas.example.ac.uk/feeds/calendars/user_abc123.ics"


@pytest.fixture
def feeds():
    from venato import feeds as module
    return importlib.reload(module)


@pytest.fixture
def outlook(store):
    from venato import outlook as module
    return importlib.reload(module)


def _ev(title, module=None, uid="x"):
    return {"uid": uid, "title": title, "module": module}


# --- Module codes ---

def test_codes_from_module_lines(feeds):
    assert feeds.split_module("CHEM50001 - Organic Chemistry") == ("CHEM50001", "Organic Chemistry")
    assert feeds.split_module("CHEM60004 - Lasers; CHEM70014 - Lasers") == ("CHEM60004", "Lasers")   # the first
    assert feeds.split_module("CH-Talk to Students") == (None, "CH-Talk to Students")                 # no code
    assert feeds.split_module("PHYS 1234A Waves") == ("PHYS1234A", "Waves")
    assert feeds.event_code(_ev("Organic Chemistry", "CHEM50001 - Organic Chemistry")) == "CHEM50001"
    assert feeds.event_code(_ev("MATH101 Lecture")) == "MATH101"                                   # else the title
    assert feeds.event_code(_ev("Lunch with Sam")) is None
    assert feeds.event_code(_ev("Town hall", "CH-Talk to Students")) is None


def test_parse_keeps_the_raw_module_line(outlook):
    events = outlook.parse(UNI, today=date(2026, 11, 20))
    lasers = next(e for e in events if e["title"] == "Lasers")
    assert lasers["module"] == "CHEM60004 - Lasers; CHEM70014 - Lasers"
    personal = next(e for e in events if e["title"] == "Summer project chat")
    assert personal["module"] is None


def test_detect_modules_from_the_uni_timetable(feeds, outlook):
    events = outlook.parse(UNI, today=date(2026, 10, 20))         # the window reaches back to 6 Oct
    found = feeds.detect_modules(events)
    assert [(m["code"], m["name"]) for m in found] == [
        ("CHEM50001", "Organic Chemistry"), ("CHEM50002", "Spectroscopy and Structure"),
        ("CHEM50003", "Mathematical Methods for Chemists"), ("CHEM50005", "Practical Chemistry"),
        ("CHEM60004", "Lasers")]
    counts = {m["code"]: m["count"] for m in found}
    assert counts["CHEM50002"] > counts["CHEM50001"] >= 2           # the make-up lecture counts too
    assert not any("Talk" in m["name"] or "Social" in m["name"] for m in found)   # no code: not a module


def test_a_module_needs_two_events(feeds):
    events = [_ev("A", "ABC1001 - Alpha"), _ev("A", "ABC1001 - Alpha"), _ev("B", "XYZ2002 - Beta")]
    assert [m["code"] for m in feeds.detect_modules(events)] == ["ABC1001"]


def test_fallbacks_only_when_no_module_lines(feeds):
    by_code = [_ev("MATH101 Lecture"), _ev("MATH101 Tutorial"), _ev("Dentist")]
    assert [(m["code"], m["count"]) for m in feeds.detect_modules(by_code)] == [("MATH101", 2)]
    by_title = [_ev("Organic Chemistry Lecture"), _ev("Organic Chemistry Seminar"), _ev("Organic chemistry lab"),
                _ev("Dentist")]
    found = feeds.detect_modules(by_title)
    assert [(m["code"], m["name"], m["count"]) for m in found] == [(None, "Organic Chemistry", 3)]
    # with a Module: line anywhere, the fallbacks don't run
    mixed = by_title + [_ev("X", "ABC1001 - Alpha"), _ev("X", "ABC1001 - Alpha")]
    assert [m["code"] for m in feeds.detect_modules(mixed)] == ["ABC1001"]
    assert feeds.detect_modules([]) == []


# --- Canvas ---

def test_canvas_events(feeds):
    events = {e["uid"]: e for e in feeds.canvas_events(CANVAS, LONDON)}
    assert len(events) == 7
    a1 = events["event-assignment-override-4101"]
    assert a1 == {"uid": "event-assignment-override-4101", "title": "Term 1 - Assignment 1 (OC Grp4)",
                  "label": "20501.202610", "course_id": "1101", "due": "2026-10-23", "due_time": "17:00"}   # BST
    lab = events["event-assignment-500210"]
    assert (lab["title"], lab["due"], lab["due_time"]) == \
        ("Lab Report 2 (Kinetics) Data Entry: Due Wed 25th Nov at 5pm", "2026-11-25", "17:00")       # GMT
    assert events["event-assignment-500233"]["due_time"] == "12:00"


def test_canvas_all_day_and_courses_url(feeds):
    ics = (b"BEGIN:VCALENDAR\r\nVERSION:2.0\r\nBEGIN:VEVENT\r\nUID:event-assignment-77\r\n"
           b"DTSTART;VALUE=DATE:20261201\r\nSUMMARY:Essay [ABC1001.2026]\r\n"
           b"URL:https://school.instructure.com/courses/555/assignments/77\r\nEND:VEVENT\r\n"
           b"BEGIN:VEVENT\r\nUID:event-calendar-event-9\r\nDTSTART:20261201T100000Z\r\nSUMMARY:Office hours\r\n"
           b"END:VEVENT\r\nEND:VCALENDAR\r\n")
    events = feeds.canvas_events(ics, LONDON)
    assert events == [{"uid": "event-assignment-77", "title": "Essay", "label": "ABC1001.2026", "course_id": "555",
                       "due": "2026-12-01", "due_time": None}]          # only assignments become deadlines


def test_canvas_courses(feeds):
    courses = feeds.canvas_courses(feeds.canvas_events(CANVAS, LONDON))
    assert courses == [{"course_id": "1101", "label": "20501.202610", "count": 2},
                       {"course_id": "1102", "label": "20502.202610", "count": 2},
                       {"course_id": "2201", "label": "TRNG-260812134148.202610", "count": 3}]


def test_is_canvas(feeds):
    assert feeds.is_canvas("https://school.instructure.com/feeds/calendars/user_x.ics")
    assert feeds.is_canvas(CANVAS_URL)                                       # a uni's own Canvas host
    assert feeds.is_canvas("https://example.org/cal.ics", CANVAS)            # recognised by its content
    assert not feeds.is_canvas("https://example.org/cal.ics", UNI)
    assert not feeds.is_canvas("https://outlook.office365.com/owa/calendar/x/reachcalendar.ics")


def test_check_any_link_names_canvas(outlook):
    assert outlook.check_any_link(CANVAS_URL) == (CANVAS_URL, "Canvas")
    assert outlook.check_any_link("webcal://school.instructure.com/feeds/calendars/user_1.ics")[1] == "Canvas"
