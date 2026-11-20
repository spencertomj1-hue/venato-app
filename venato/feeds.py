"""
What a student's calendar feeds say about their modules (pure functions: no database, no network).

  Uni timetable (Outlook / Exchange publish): one event per occurrence, the module in the
  description's "Module: CHEM50001 - Organic Chemistry" line (parsed events keep it as "module").
  detect_modules() finds the modules; event_code() is the code an event is tagged with.

  Canvas: one event per assignment (UID event-assignment-<id>), the title ending in a bracketed
  SIS label ("[20501.202610]"), the course in the URL (course_<id>), the due time in DTSTART (UTC).
  canvas_events() turns the feed into deadlines to import; canvas_courses() lists its courses.
"""

import re
from collections import Counter
from datetime import datetime, timezone
from urllib.parse import urlparse

CODE = re.compile(r"\b[A-Z]{2,5}\s?\d{3,5}[A-Z]?\b")
KINDS = re.compile(r"\b(lectures?|seminars?|labs?|tutorials?)\b", re.I)
LABEL = re.compile(r"\s*\[([^\]]*)\]\s*$")
COURSE = re.compile(r"course_(\d+)|/courses/(\d+)")
MIN_EVENTS = 2                       # a module appears on 2+ events (the feed has no RRULE)


def norm_code(code):
    """'CHEM 50001' -> 'CHEM50001'."""
    return re.sub(r"\s+", "", str(code)).upper()


def find_code(text):
    """The first module code in a text (normalised), or None."""
    m = CODE.search(str(text or ""))
    return norm_code(m.group()) if m else None


def module_line(description):
    """The text after "Module:" in an event's (raw) description, or None."""
    m = re.search(r"^\s*Module:\s*(.+?)\s*$", str(description or ""), re.M)
    return m.group(1) if m else None


def split_module(line):
    """(code, name) of the first module on a Module: line ('A - x; B - y' -> A). code is None without one."""
    first = str(line or "").split(";")[0].strip()
    m = CODE.search(first)
    if not m:
        return None, first or None
    name = (first[:m.start()] + " " + first[m.end():]).strip(" -–—:")
    return norm_code(m.group()), re.sub(r"\s+", " ", name) or None


def event_code(ev):
    """The module code a parsed timetable event belongs to: its Module: line, else a code in its title."""
    if ev.get("module"):
        code, _ = split_module(ev["module"])
        if code:
            return code
    return find_code(ev.get("title"))


def _strip_kind(title):
    return re.sub(r"\s+", " ", KINDS.sub(" ", str(title or ""))).strip(" -–—:,()")


def _most_common(values):
    values = [v for v in values if v]
    return Counter(values).most_common(1)[0][0] if values else None


def detect_modules(events):
    """
    Modules in parsed timetable events, as [{code, name, count}] (by code, or by name without codes).
    The Module: line's code and name; events whose line has no code ("CH-Talk to Students") and events
    with no line (personal meetings) are not modules. Only when that finds nothing: a code in the title,
    else titles grouped with Lecture / Seminar / Lab / Tutorial taken off. A module needs 2+ events.
    """
    found = {}
    for ev in events:
        code, name = split_module(ev.get("module")) if ev.get("module") else (None, None)
        if code:
            m = found.setdefault(code, {"code": code, "names": [], "titles": []})
            m["names"].append(name)
            m["titles"].append(ev.get("title"))
    if not found:                                        # fallback 1: a code in the title
        for ev in events:
            code = find_code(ev.get("title"))
            if code:
                m = found.setdefault(code, {"code": code, "names": [], "titles": []})
                m["titles"].append(_strip_kind(CODE.sub(" ", ev["title"])))
    if not found:                                        # fallback 2: the same title, whatever the kind
        for ev in events:
            name = _strip_kind(ev.get("title"))
            if name:
                m = found.setdefault(name.lower(), {"code": None, "names": [], "titles": []})
                m["names"].append(name)
    out = [{"code": m["code"], "name": _most_common(m["names"]) or _most_common(m["titles"]) or m["code"],
            "count": len(m["names"]) or len(m["titles"])} for m in found.values()]
    out = [m for m in out if m["count"] >= MIN_EVENTS]
    return sorted(out, key=lambda m: (m["code"] or "", m["name"].lower()))


# ---------------------------------------------------------------------------
# Canvas
# ---------------------------------------------------------------------------

def is_canvas(url, data=None):
    """A Canvas calendar feed: an instructure.com host or a /feeds/calendars/ path (a uni's own Canvas
    host), or a feed whose events are Canvas assignments."""
    parts = urlparse(str(url or ""))
    if "instructure.com" in (parts.hostname or "").lower() or "/feeds/calendars/" in parts.path.lower():
        return True
    return bool(data) and re.search(rb"(?m)^UID:event-assignment-", data) is not None


def canvas_events(ics_bytes, zone):
    """
    Canvas assignments as deadlines to import: [{uid, title, label, course_id, due, due_time}].
    title: the SUMMARY without its trailing " [label]"; due / due_time: the local date and "HH:MM"
    in `zone` (due_time None for an all-day one). Other Canvas events (not assignments) are skipped.
    """
    import icalendar
    out = []
    for ev in icalendar.Calendar.from_ical(ics_bytes).walk("VEVENT"):
        uid = str(ev.get("UID", "")).strip()
        if not uid.startswith("event-assignment-") or "DTSTART" not in ev:
            continue
        summary = re.sub(r"\s+", " ", str(ev.get("SUMMARY", ""))).strip()
        label = LABEL.search(summary)
        title = LABEL.sub("", summary).strip() or summary or "(No title)"
        course = COURSE.search(str(ev.get("URL", "")))
        start = ev.decoded("DTSTART")
        if isinstance(start, datetime):
            start = (start if start.tzinfo else start.replace(tzinfo=timezone.utc)).astimezone(zone)
            due, due_time = start.date().isoformat(), f"{start:%H:%M}"
        else:
            due, due_time = start.isoformat(), None
        out.append({"uid": uid, "title": title, "label": label.group(1).strip() if label else None,
                    "course_id": (course.group(1) or course.group(2)) if course else None,
                    "due": due, "due_time": due_time})
    return out


def canvas_courses(events):
    """The courses in canvas_events(): [{course_id, label, count}], by course id."""
    courses = {}
    for ev in events:
        if ev.get("course_id"):
            c = courses.setdefault(ev["course_id"], {"course_id": ev["course_id"], "label": None, "count": 0})
            c["label"] = c["label"] or ev.get("label")
            c["count"] += 1
    return sorted(courses.values(), key=lambda c: (len(c["course_id"]), c["course_id"]))
