"""Phase 0: the anonymised real-feed fixtures parse and keep the shapes module detection relies on."""

import importlib
import re
from datetime import date, time
from pathlib import Path

import icalendar
import pytest

FIXTURES = Path(__file__).parent / "fixtures"
CANVAS = (FIXTURES / "canvas_sample.ics").read_bytes()
UNI = (FIXTURES / "uni_timetable_sample.ics").read_bytes()
CODE = re.compile(r"\b[A-Z]{2,5}\s?\d{3,5}[A-Z]?\b")


@pytest.fixture
def outlook(store):
    from venato import outlook as module
    return importlib.reload(module)


def _events(raw):
    return icalendar.Calendar.from_ical(raw).walk("VEVENT")


def test_canvas_shape():
    events = _events(CANVAS)
    assert len(events) == 7
    for ev in events:
        assert re.fullmatch(r"event-assignment-(override-)?\d+", str(ev["UID"]))
        assert re.search(r"include_contexts=course_\d+", str(ev["URL"]))
        assert re.search(r" \[[^\]]+\]$", str(ev["SUMMARY"]))
        assert ev.decoded("DTSTART") == ev.decoded("DTEND")
    courses = {re.search(r"course_(\d+)", str(ev["URL"])).group(1) for ev in events}
    assert courses == {"1101", "1102", "2201"}


def test_uni_shape_has_module_lines_and_no_rrule():
    events = _events(UNI)
    assert not any("RRULE" in ev for ev in events)
    codes = set()
    for ev in events:
        m = re.search(r"^Module:\s*(.+)$", str(ev.get("DESCRIPTION", "")), re.M)
        if m and (c := CODE.search(m.group(1).split(";")[0])):
            codes.add(c.group())
    assert codes == {"CHEM50001", "CHEM50002", "CHEM50003", "CHEM50005", "CHEM60004"}


def test_both_feeds_parse_with_the_app_parser(outlook):
    uni = outlook.parse(UNI, today=date(2026, 11, 20))
    lectures = [e for e in uni if e["title"] == "Organic Chemistry"]
    assert lectures and all(e["start"].time() == time(10) for e in lectures)   # GMT Standard Time -> London
    canvas = outlook.parse(CANVAS, today=date(2026, 11, 20))
    assert {e["uid"] for e in canvas} >= {"event-assignment-500210", "event-assignment-900501"}
