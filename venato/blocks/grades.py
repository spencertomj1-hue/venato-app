"""
Grades: modules (credits, year, a target) with weighted assessments; the running average,
marks secured so far, what you need on the rest to hit your target, and an overall mark
for each year and the whole degree (credit-weighted, years weighted as you set) shown as a
UK classification or a US GPA. Marks are percentages.

Each module has its own timetable category (group "Modules"), made with it and renamed with it.
Deadlines (module_id), imported timetable events (tt_outlook.module_id: the student's choice for the series,
else its code, else a title rule; see store/outlook.py) and Canvas courses (gr_canvas_courses) link to a module;
deleting the module only clears those links. Modules and courses found in the calendars after setup are offered
on the Modules page and in Needs you.
"""

import re
import uuid

from venato import store
from venato.blocks import Block, Widget

SYSTEMS = ("UK", "US", "Percent")
UK_CLASSES = [(70, "First"), (60, "2:1"), (50, "2:2"), (40, "Third"), (0, "Fail")]
US_GRADES = [(93, "A", 4.0), (90, "A-", 3.7), (87, "B+", 3.3), (83, "B", 3.0), (80, "B-", 2.7), (77, "C+", 2.3),
             (73, "C", 2.0), (70, "C-", 1.7), (67, "D+", 1.3), (63, "D", 1.0), (60, "D-", 0.7), (0, "F", 0.0)]

SCHEMA = """
CREATE TABLE IF NOT EXISTS gr_modules (
    id         TEXT PRIMARY KEY,
    name       TEXT NOT NULL UNIQUE COLLATE NOCASE,
    code       TEXT,
    credits    REAL NOT NULL DEFAULT 10,
    year       TEXT,                       -- e.g. "Year 2"
    target     REAL,                       -- %
    final      REAL,                       -- the final module mark, once it's known (%)
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS gr_assessments (
    id        TEXT PRIMARY KEY,
    module_id TEXT NOT NULL REFERENCES gr_modules(id) ON DELETE CASCADE,
    name      TEXT NOT NULL,
    weight    REAL NOT NULL,               -- % of the module
    mark      REAL,                        -- %, once marked
    due       TEXT                         -- YYYY-MM-DD
);
-- Canvas courses seen in a Canvas feed (it gives no names or codes: the label is the SIS bracket
-- text, e.g. "20501.202610"), and the module the student linked each one to (NULL = none).
-- The student's choice for an imported event series, by store.series_key(title, code): its module, or NULL
-- for "not a module". Kept apart from tt_outlook, which every sync replaces. Beats the code and title rules.
CREATE TABLE IF NOT EXISTS gr_event_links (
    key       TEXT PRIMARY KEY,
    module_id TEXT,                        -- gr_modules.id, NULL = not a module
    title     TEXT,                        -- the series as the student saw it (to list and restore it)
    code      TEXT
);
CREATE TABLE IF NOT EXISTS gr_canvas_courses (
    course_id TEXT PRIMARY KEY,
    label     TEXT,
    module_id TEXT                         -- gr_modules.id
);
"""


def _migrate(conn):
    """Later columns: each module's timetable category (modules made before it have none: existing data isn't
    rewritten; a later phase offers to make them), and `match`, words a lecture title must contain (NULL: the
    module's name when it has no code)."""
    store._add_column(conn, "gr_modules", "category_id", "TEXT")
    store._add_column(conn, "gr_modules", "match", "TEXT")


class GradeError(ValueError):
    pass


def _id():
    return uuid.uuid4().hex


def _pct(v, what="mark"):
    if v in (None, ""):
        return None
    v = float(v)
    if not 0 <= v <= 100:
        raise GradeError(f"A {what} is a percentage from 0 to 100.")
    return v


# --- Settings ---

def settings():
    s = store.load_settings().get("grades") or {}
    return {"system": s.get("system", "UK"), "years": s.get("years") or {}}


def save_settings(system=None, years=None):
    s = settings()
    if system and system not in SYSTEMS:
        raise GradeError(f"Grading is one of {', '.join(SYSTEMS)}.")
    store.save_settings(grades={"system": system or s["system"],
                                "years": s["years"] if years is None else {k: float(v) for k, v in years.items() if v}})


# --- Modules and assessments ---

M_COLS = ("id", "name", "code", "credits", "year", "target", "final", "category_id", "created_at", "match")
EDITABLE = ("name", "code", "credits", "year", "target", "final", "match")
A_COLS = ("id", "module_id", "name", "weight", "mark", "due")


def modules():
    with store.db() as conn:
        rows = conn.execute(f"SELECT {', '.join(M_COLS)} FROM gr_modules ORDER BY year, name COLLATE NOCASE").fetchall()
    return [dict(zip(M_COLS, r)) for r in rows]


def get_module(mid):
    return next((m for m in modules() if m["id"] == mid), None)


def find_module(name):
    want = str(name or "").strip().lower()
    pool = modules()
    hit = [m for m in pool if m["name"].lower() == want or (m["code"] or "").lower() == want]
    if hit:
        return hit[0]
    part = [m for m in pool if want and (m["name"].lower().startswith(want) or want in m["name"].lower())]
    return part[0] if len(part) == 1 else None


def add_module(name, credits=10, year=None, target=None, code=None, match=None):
    name = str(name or "").strip()
    if not name:
        raise GradeError("The module needs a name.")
    credits = float(credits or 10)
    if not 0 < credits <= 200:
        raise GradeError("Credits must be between 1 and 200.")
    if any(m["name"].lower() == name.lower() for m in modules()):
        raise GradeError(f"There's already a module called {name}.")
    target = _pct(target, "target")
    mid = _id()
    cid = f"module-{mid[:12]}"
    with store.db() as conn:                                          # one transaction: no orphan category
        conn.execute("INSERT INTO gr_modules (id, name, code, credits, year, target, final, category_id, created_at, "
                     "match) VALUES (?, ?, ?, ?, ?, ?, NULL, ?, ?, ?)",
                     (mid, name, _code(code), credits, year, target, cid, store.stamp(), _match(match)))
        store.add_module_category(conn, cid, name)                    # its own category, next free colour
    store.tag_outlook_modules()                                       # its timetable events (by code, rule or name)
    return mid


def _code(code):
    return (str(code).strip() or None) if code is not None else None


def _match(words):
    """A title rule as saved: its words with single spaces, or None."""
    return " ".join(str(words or "").split()) or None


def update_module(mid, **fields):
    """Change a module's details. Renaming it renames its category; a new name, code or title rule re-tags the
    timetable."""
    f = {k: v for k, v in fields.items() if k in EDITABLE}
    for k in ("target", "final"):
        if k in f:
            f[k] = _pct(f[k], k)
    if "name" in f:
        f["name"] = str(f["name"] or "").strip()
        if not f["name"]:
            raise GradeError("The module needs a name.")
    if "code" in f:
        f["code"] = _code(f["code"])
    if "match" in f:
        f["match"] = _match(f["match"])
    if f:
        with store.db() as conn:
            conn.execute(f"UPDATE gr_modules SET {', '.join(f'{k} = ?' for k in f)} WHERE id = ?", (*f.values(), mid))
    m = get_module(mid)
    if m and "name" in f and m["category_id"]:
        store.rename_category(m["category_id"], f["name"])
    if {"name", "code", "match"} & set(f):
        store.tag_outlook_modules()


def file_series(title, module_id, code=None):
    """The student's choice for an imported event series (the events with that title, kind words and case aside,
    and that module code): `module_id`, or None for "not a module". It beats the code and title rules, and
    survives a sync."""
    from venato import feeds
    code = feeds.norm_code(code) if code else None
    with store.db() as conn:
        conn.execute("INSERT INTO gr_event_links (key, module_id, title, code) VALUES (?, ?, ?, ?) "
                     "ON CONFLICT(key) DO UPDATE SET module_id = excluded.module_id, title = excluded.title",
                     (store.series_key(title, code), module_id or None, title, code))
    store.tag_outlook_modules()


def unfile_series(title, code=None):
    """Forget the choice made for a series: its code and the title rules decide again."""
    with store.db() as conn:
        conn.execute("DELETE FROM gr_event_links WHERE key = ?", (store.series_key(title, code),))
    store.tag_outlook_modules()


def not_a_module_series():
    """[{title, code}]: the series the student marked "not a module"."""
    with store.db() as conn:
        rows = conn.execute("SELECT title, code FROM gr_event_links WHERE module_id IS NULL "
                            "ORDER BY title COLLATE NOCASE").fetchall()
    return [{"title": t, "code": c} for t, c in rows]


def delete_module(mid):
    """Delete a module and its assessments. Only its links go: its category, deadlines, Canvas courses
    and timetable events stay (unlinked; its series show as Unfiled again, unless another module's rule
    takes them)."""
    with store.db() as conn:
        conn.execute("UPDATE deadlines SET module_id = NULL WHERE module_id = ?", (mid,))
        conn.execute("UPDATE tt_outlook SET module_id = NULL WHERE module_id = ?", (mid,))
        conn.execute("UPDATE gr_canvas_courses SET module_id = NULL WHERE module_id = ?", (mid,))
        conn.execute("DELETE FROM gr_event_links WHERE module_id = ?", (mid,))   # its series: Unfiled again
        conn.execute("DELETE FROM gr_assessments WHERE module_id = ?", (mid,))
        conn.execute("DELETE FROM gr_modules WHERE id = ?", (mid,))
    store.tag_outlook_modules()


def _group_series(rows, minimum=1):
    """[(title, date, code)] -> [{title, code, count, next}] by series_key, the most common title for each."""
    from collections import Counter
    groups = {}
    for title, day, code in rows:
        g = groups.setdefault(store.series_key(title, code), {"titles": Counter(), "count": 0, "next": day, "code": code})
        g["titles"][title] += 1
        g["count"] += 1
    return [{"title": g["titles"].most_common(1)[0][0], "code": g["code"], "count": g["count"], "next": g["next"]}
            for g in groups.values() if g["count"] >= minimum]


_SERIES = ("SELECT title, date, module_code FROM tt_outlook WHERE all_day = 0 AND date BETWEEN ? AND ? "
           "AND uid NOT IN (SELECT uid FROM tt_outlook_hidden) AND ")


def unfiled_series(today, weeks=8):
    """[{title, code, count, next}]: timed event series in the next `weeks` (from `today`) on no module and with
    no choice made for them ("not a module" counts as a choice), 2+ sessions each, soonest first. The same title
    under two module codes is two series."""
    from datetime import timedelta
    from venato import feeds
    window = (today.isoformat(), (today + timedelta(weeks=weeks)).isoformat())
    with store.db() as conn:
        rows = conn.execute(_SERIES + "module_id IS NULL ORDER BY date, start", window).fetchall()
        filed = {r[0] for r in conn.execute("SELECT key FROM gr_event_links")}
    out = [s for s in _group_series(rows, feeds.MIN_EVENTS) if store.series_key(s["title"], s["code"]) not in filed]
    return sorted(out, key=lambda s: (s["next"], s["title"].lower()))


def series_of(mid, today, weeks=8):
    """[{title, code, count, next}]: the module's event series in the next `weeks`."""
    from datetime import timedelta
    window = (today.isoformat(), (today + timedelta(weeks=weeks)).isoformat())
    with store.db() as conn:
        rows = conn.execute(_SERIES + "module_id = ? ORDER BY date, start", (*window, mid)).fetchall()
    return _group_series(rows)


def link_summary(m, today, weeks=8):
    """What's linked to a module: {"lectures": timed events in the next `weeks`, "deadlines": open ones,
    "canvas": the linked Canvas course's label (or id), or None}."""
    from datetime import timedelta
    lectures = [e for e in week_events(m["id"], today, today + timedelta(weeks=weeks)) if not e["all_day"]]
    course = next((c for c in canvas_courses() if c["module_id"] == m["id"]), None)
    return {"lectures": len(lectures), "deadlines": len(open_deadlines(m["id"])),
            "canvas": (course["label"] or course["course_id"]) if course else None}


def unfiled_deadlines():
    """Open Canvas deadlines on no module (not from a course the student ignored), soonest first. Ones typed in
    by hand are left out: plenty belong to no module."""
    with store.db() as conn:
        courses = dict(conn.execute("SELECT id, course_id FROM deadlines WHERE source = 'canvas'").fetchall())
    gone = dismissed()["course"]
    return [d for d in store.deadlines() if d["module_id"] is None and d["id"] in courses
            and courses[d["id"]] not in gone]


def create_category(mid):
    """Give a module made before categories existed its own category (group "Modules"). Does nothing for
    one that has it. Returns the category id (None if there's no such module)."""
    m = get_module(mid)
    if not m:
        return None
    if m["category_id"]:
        return m["category_id"]
    cid = f"module-{mid[:12]}"
    with store.db() as conn:
        store.add_module_category(conn, cid, m["name"])
        conn.execute("UPDATE gr_modules SET category_id = ? WHERE id = ?", (cid, mid))
    return cid


def safe_colour(colour, default=None):
    """`colour` if it is #RRGGBB (so it is safe in a style attribute), else `default`."""
    return colour if re.fullmatch(r"#[0-9A-Fa-f]{6}", str(colour)) else default


def category_colour(m):
    """A module's colour: its category's (#RRGGBB), or None while it has no category or a bad colour."""
    if not m["category_id"]:
        return None
    cats = store.load_categories()
    row = cats[cats["id"] == m["category_id"]]
    return None if row.empty else safe_colour(row.iloc[0]["colour"])


# --- A module's time ---

DEFAULT_WEEK_HOURS = 6


def week_hours_goal(m):
    """Study hours a week for a module: its own number if set, else the default for every module (6 h)."""
    s = store.load_settings()
    own = (s.get("module_hours") or {}).get(m["id"])
    return float(own if own is not None else s.get("study_hours", DEFAULT_WEEK_HOURS))


def set_week_hours_goal(mid, hours):
    """Set one module's hours a week (None goes back to the default)."""
    own = dict(store.load_settings().get("module_hours") or {})
    if hours is None:
        own.pop(mid, None)
    else:
        own[mid] = float(hours)
    store.save_settings(module_hours=own)


def module_hours(m, ctx):
    """{"done", "planned", "goal", "term"} hours of the module's category: this week's Actual (confirmed days),
    this week's Plan (its lectures count once, under this category), the weekly goal, and the Actual since
    the module was added. All zero while the module has no category."""
    from venato import pace
    week = pace.week_days(ctx.today)
    goal = {"category_id": m["category_id"], "label": None}
    since = min(ctx.today, store._as_date((m.get("created_at") or ctx.today.isoformat())[:10]))
    return {"done": ctx.hours(goal, week[0], week[-1], "actual"), "planned": ctx.hours(goal, week[0], week[-1], "plan"),
            "goal": week_hours_goal(m), "term": ctx.hours(goal, since, ctx.today, "actual")}


def open_deadlines(mid):
    """The module's deadlines not yet done, soonest first."""
    return [d for d in store.deadlines() if d["module_id"] == mid]


def week_events(mid, first, last):
    """The module's timetable events (lectures) between two days."""
    return [e for e in store.outlook_between(first.isoformat(), last.isoformat()) if e.get("module_id") == mid]


def week_blocks(m, first, last):
    """The Plan blocks the student put in the module's category between two days."""
    return [b for b in store.blocks_between(first.isoformat(), last.isoformat(), "plan")
            if m["category_id"] and b["category_id"] == m["category_id"]]


# --- Canvas courses ---

def canvas_courses():
    """[{course_id, label, module_id}] of the Canvas courses seen so far."""
    with store.db() as conn:
        rows = conn.execute("SELECT course_id, label, module_id FROM gr_canvas_courses "
                            "ORDER BY LENGTH(course_id), course_id").fetchall()
    return [dict(zip(("course_id", "label", "module_id"), r)) for r in rows]


def link_canvas_course(course_id, module_id):
    """Link a Canvas course to a module (None: unlink). Its deadlines, already imported or still to come,
    move with it, except any the student gave another module themselves."""
    module_id = module_id or None
    with store.db() as conn:
        row = conn.execute("SELECT module_id FROM gr_canvas_courses WHERE course_id = ?", (course_id,)).fetchone()
        previous = row[0] if row else None
        conn.execute("INSERT INTO gr_canvas_courses (course_id, module_id) VALUES (?, ?) "
                     "ON CONFLICT(course_id) DO UPDATE SET module_id = excluded.module_id", (course_id, module_id))
        # Only the ones that followed the course (no module, or its old one): one the student moved stays put.
        conn.execute("UPDATE deadlines SET module_id = ? WHERE source = 'canvas' AND course_id = ? "
                     "AND (module_id IS NULL OR module_id = ?)", (module_id, course_id, previous))


# --- Detection: modules and Canvas courses in the connected calendars (after setup too) ---

_parsed = {}                                   # {(kind, day, zone, calendar bytes): parsed events}


def _calendars(canvas, day=None):
    """Parsed events of the connected calendars of one kind (timetable or Canvas), parsed again only when a
    calendar or the day changed (Home asks on every rerun). A calendar that no longer parses adds nothing."""
    from venato import feeds, outlook
    data = tuple(d for _, d in outlook.cached_calendars() if feeds.is_canvas("", d) == canvas)
    key = ("canvas" if canvas else "uni", day or store.local_today(), str(store.tz()), data)
    events = _parsed.get(key)                      # one read: another session's thread may clear _parsed
    if events is None:
        events = []
        for d in data:
            try:
                events += feeds.canvas_events(d, store.tz()) if canvas else outlook.parse(d, day)
            except Exception:
                continue
        if len(_parsed) > 4:
            _parsed.clear()
        _parsed[key] = events
    return events


def detected(day=None):
    """[{code, name, count}]: the modules in the connected timetable calendars (Canvas has no module names)."""
    from venato import feeds
    return feeds.detect_modules(_calendars(False, day))


def detected_courses(day=None):
    """The connected Canvas courses: [{course_id, label, titles (a couple of its assignments), module_id}].
    The module links are read fresh."""
    from venato import feeds
    events = _calendars(True, day)
    linked = {c["course_id"]: c["module_id"] for c in canvas_courses()}
    return [{"course_id": c["course_id"], "label": c["label"], "module_id": linked.get(c["course_id"]),
             "titles": [e["title"] for e in events if e.get("course_id") == c["course_id"]][:2]}
            for c in feeds.canvas_courses(events)]


def _module_for(code, name):
    """The module already in Venato for a detected one: the same code, or the same name when one of them has no
    code (last year's module with the same name and another code is another module). Or None."""
    from venato import feeds
    for m in modules():
        if code and m["code"]:                                       # both have codes: only the codes count
            if feeds.norm_code(m["code"]) == feeds.norm_code(code):
                return m
        elif m["name"].lower() == str(name or "").strip().lower():
            return m
    return None


def _dismiss_key(m):
    return m["code"] or m["name"].lower()


def dismissed():
    d = store.load_settings().get("modules_dismissed") or {}
    return {"module": set(d.get("module") or []), "course": set(d.get("course") or [])}


def dismiss(kind, key):
    """Stop offering a detected module (key: its code, or its lowercased name without one) or a Canvas course
    (key: its course id)."""
    if kind not in ("module", "course"):
        raise GradeError("Ignore a module or a course.")
    d = dismissed()
    d[kind].add(str(key))
    store.save_settings(modules_dismissed={k: sorted(v) for k, v in d.items()})


def new_found(day=None):
    """{"modules", "courses"}: detected modules not in Venato (_module_for), not ignored and whose lectures aren't
    all on a module already (a rule or the student's choice took them), and
    Canvas courses linked to no module and not ignored."""
    gone = dismissed()
    with store.db() as conn:                                         # codes whose events are all on a module
        filed = {c for c, loose in conn.execute("SELECT module_code, SUM(module_id IS NULL) FROM tt_outlook "
                                                "WHERE module_code IS NOT NULL GROUP BY module_code") if not loose}
    return {"modules": [m for m in detected(day) if not _module_for(m["code"], m["name"])
                        and _dismiss_key(m) not in gone["module"] and m["code"] not in filed],
            "courses": [c for c in detected_courses(day) if c["module_id"] is None
                        and c["course_id"] not in gone["course"]]}


def _plural(n, word):
    return f"{n} {word}" if n == 1 else f"{n} {word}s"


def _needs():
    """Home's "Needs you": one item when the calendars have modules or Canvas courses to sort out."""
    found = new_found()
    bits = []
    if found["modules"]:
        bits.append(f"{_plural(len(found['modules']), 'new module')} in your timetable")
    if found["courses"]:
        bits.append(f"{_plural(len(found['courses']), 'Canvas course')} to link")
    return [{"text": " · ".join(bits), "icon": ":material/school:", "page": "grades"}] if bits else []


def assessments(mid):
    with store.db() as conn:
        rows = conn.execute(f"SELECT {', '.join(A_COLS)} FROM gr_assessments WHERE module_id = ? "
                            "ORDER BY due IS NULL, due, rowid", (mid,)).fetchall()
    return [dict(zip(A_COLS, r)) for r in rows]


def add_assessment(mid, name, weight, mark=None, due=None):
    name = str(name or "").strip()
    if not name:
        raise GradeError("The assessment needs a name.")
    weight = _pct(weight, "weighting")
    if not weight:
        raise GradeError("Give its weighting: what % of the module it's worth.")
    used = sum(a["weight"] for a in assessments(mid))
    if used + weight > 100.001:
        raise GradeError(f"That would make the module's assessments add up to {used + weight:g}% (over 100%).")
    aid = _id()
    with store.db() as conn:
        conn.execute(f"INSERT INTO gr_assessments ({', '.join(A_COLS)}) VALUES (?, ?, ?, ?, ?, ?)",
                     (aid, mid, name, weight, _pct(mark), str(store._as_date(due)) if due else None))
    return aid


def update_assessment(aid, **fields):
    f = {k: v for k, v in fields.items() if k in ("name", "weight", "mark", "due")}
    if "mark" in f:
        f["mark"] = _pct(f["mark"])
    if "weight" in f:
        f["weight"] = _pct(f["weight"], "weighting")
    if "due" in f and f["due"]:
        f["due"] = str(store._as_date(f["due"]))
    if f:
        with store.db() as conn:
            conn.execute(f"UPDATE gr_assessments SET {', '.join(f'{k} = ?' for k in f)} WHERE id = ?", (*f.values(), aid))


def delete_assessment(aid):
    with store.db() as conn:
        conn.execute("DELETE FROM gr_assessments WHERE id = ?", (aid,))


# --- The maths ---

def module_numbers(m):
    """For one module: average so far, marks secured, weight marked / planned, projected mark,
    and what's needed on the rest for its target."""
    rows = assessments(m["id"])
    marked = [a for a in rows if a["mark"] is not None]
    done_w = sum(a["weight"] for a in marked)
    planned_w = sum(a["weight"] for a in rows)
    secured = sum(a["weight"] * a["mark"] for a in marked) / 100           # % of the module already banked
    average = secured / done_w * 100 if done_w else None
    projected = m["final"] if m["final"] is not None else average
    left = max(0.0, 100 - done_w)
    needed = None
    if m["target"] is not None and m["final"] is None and left > 0:
        needed = (m["target"] - secured) / left * 100
    return {"average": average, "secured": secured, "done_weight": done_w, "planned_weight": planned_w,
            "projected": projected, "left": left, "needed": needed,
            "status": None if needed is None else "reached" if needed <= 0 else "impossible" if needed > 100 else "possible"}


def overall():
    """Credit-weighted projected mark per year and for the degree (years weighted as set)."""
    by_year = {}
    for m in modules():
        n = module_numbers(m)
        if n["projected"] is None:
            continue
        y = by_year.setdefault(m["year"] or "Modules", {"credits": 0.0, "points": 0.0, "gpa_points": 0.0})
        y["credits"] += m["credits"]
        y["points"] += m["credits"] * n["projected"]
        y["gpa_points"] += m["credits"] * letter(n["projected"])[1]
    years = {y: v["points"] / v["credits"] for y, v in by_year.items() if v["credits"]}
    gpas = {y: v["gpa_points"] / v["credits"] for y, v in by_year.items() if v["credits"]}
    weights = settings()["years"]
    if years:
        w = {y: float(weights.get(y, 1)) for y in years}
        total_w = sum(w.values()) or 1
        degree = sum(years[y] * w[y] for y in years) / total_w
        gpa = sum(gpas[y] * w[y] for y in gpas) / total_w
    else:
        degree = gpa = None
    return {"years": years, "degree": degree, "gpa": gpa}


def classification(pct):
    if pct is None:
        return None
    return next(name for floor, name in UK_CLASSES if pct >= floor)


def letter(pct):
    """(letter, grade points) on the usual US scale."""
    return next((l, p) for floor, l, p in US_GRADES if pct >= floor)


def describe(pct, gpa=None):
    if pct is None:
        return "no marks yet"
    system = settings()["system"]
    if system == "UK":
        return f"{pct:.1f}% ({classification(pct)})"
    if system == "US":
        return f"{pct:.1f}% ({letter(pct)[0]}, GPA {gpa if gpa is not None else letter(pct)[1]:.2f})"
    return f"{pct:.1f}%"


# --- The assistant ---

def _module_line(m):
    n = module_numbers(m)
    bits = [f"{m['name']}: {describe(n['projected'])}", f"{n['done_weight']:g}% marked"]
    if n["needed"] is not None:
        bits.append(f"needs {n['needed']:.0f}% on the remaining {n['left']:g}% for {m['target']:g}%"
                    if n["status"] == "possible" else f"target {m['target']:g}% " + n["status"])
    return ", ".join(bits)


def tool_summary():
    from venato import tools
    ms = modules()
    if not ms:
        return tools.Result("No modules yet.")
    o = overall()
    head = f"Overall: {describe(o['degree'], o['gpa'])}."
    years = " ".join(f"{y}: {v:.1f}%." for y, v in o["years"].items()) if len(o["years"]) > 1 else ""
    return tools.Result(f"{head} {years}\n" + "\n".join(f"- {_module_line(m)}" for m in ms))


def tool_add_module(name, credits=10, year=None, target=None, code=None):
    from venato import tools
    try:
        add_module(name, credits, year, target, code)
    except GradeError as e:
        raise tools.ToolError(str(e))
    return tools.Result(f"Added the module {name} ({credits:g} credits).", changed=True)


def tool_add_grade(module, assessment, mark=None, weight=None, due=None):
    """Record a mark (or add an assessment). An existing assessment is found by name."""
    from venato import tools
    m = find_module(module)
    if not m:
        raise tools.ToolError(f"No module called '{module}'. Modules: {', '.join(x['name'] for x in modules()) or 'none'}.")
    rows = assessments(m["id"])
    hit = [a for a in rows if a["name"].lower() == str(assessment).strip().lower()] or \
          [a for a in rows if str(assessment).strip().lower() in a["name"].lower()]
    try:
        if len(hit) == 1:
            update_assessment(hit[0]["id"], **{k: v for k, v in (("mark", mark), ("weight", weight), ("due", due))
                                             if v is not None})
        elif weight is None:
            raise tools.ToolError(f"{m['name']} has no assessment '{assessment}'. Give its weighting to add it.")
        else:
            add_assessment(m["id"], assessment, weight, mark, due)
    except GradeError as e:
        raise tools.ToolError(str(e))
    return tools.Result(f"Saved. {_module_line(get_module(m['id']))}.", changed=True)


def tool_needed(module, target=None):
    from venato import tools
    m = find_module(module)
    if not m:
        raise tools.ToolError(f"No module called '{module}'.")
    if target is not None:
        update_module(m["id"], target=target)
        m = get_module(m["id"])
    return tools.Result(_module_line(m), changed=target is not None)


QUICK = re.compile(r"(?:i\s+)?(?:got|scored|received)\s+(\d+(?:\.\d+)?)\s*%?\s+(?:in|on|for)\s+(?:my\s+|the\s+)?(.+)")


def _quick(text, day):
    """'got 68 in ACP coursework': a module and one of its assessments that already exist."""
    m = QUICK.fullmatch(text)
    if not m:
        return None
    words = m.group(2)
    for mod in modules():
        for key in filter(None, (mod["name"].lower(), (mod["code"] or "").lower())):
            if words.startswith(key + " "):
                rest = words[len(key):].strip()
                hit = [a for a in assessments(mod["id"]) if a["name"].lower() == rest or rest in a["name"].lower()]
                if len(hit) == 1:
                    return tool_add_grade(mod["name"], hit[0]["name"], float(m.group(1)))
    return None


def _context():
    ms = modules()
    if not ms:
        return "No modules yet."
    o = overall()
    return f"Overall {describe(o['degree'], o['gpa'])}. " + "; ".join(_module_line(m) for m in ms[:12])


PROMPT = """- Grades: uni / school modules with weighted assessments (the Grades page). "I got 68 in the ACP exam" ->
  add_grade(module="ACP", assessment="Exam", mark=68); a new assessment needs its weighting (% of the module).
  add_module(name, credits, year, target). grades_summary gives the overall mark (UK classification or US GPA,
  as set) and each module's average; needed_for_target(module, target) says what's needed on the rest."""

TOOLS = [
    ("grades_summary", "Overall mark (classification / GPA) and every module's average, what's marked and what's needed.",
     {"type": "object", "properties": {}, "required": []}, tool_summary),
    ("add_module", "Add a module: name, credits, year (e.g. 'Year 2'), target %, code.",
     {"type": "object", "properties": {"name": {"type": "string"}, "credits": {"type": "number"},
                                       "year": {"type": "string"}, "target": {"type": "number"},
                                       "code": {"type": "string"}}, "required": ["name"]}, tool_add_module),
    ("add_grade", "Record a mark (%) for a module's assessment, or add an assessment (with its weighting %).",
     {"type": "object", "properties": {"module": {"type": "string"}, "assessment": {"type": "string"},
                                       "mark": {"type": "number"}, "weight": {"type": "number"},
                                       "due": {"type": "string"}}, "required": ["module", "assessment"]}, tool_add_grade),
    ("needed_for_target", "What mark is needed on a module's remaining assessments to reach its target (optionally set a new target).",
     {"type": "object", "properties": {"module": {"type": "string"}, "target": {"type": "number"}},
      "required": ["module"]}, tool_needed),
]


def _page():
    from venato.ui import grades as ui
    ui.render_page()


def _home():
    from venato.ui import grades as ui
    ui.render_home()


def _modules_status():
    from venato import tile_status
    return tile_status.modules()


BLOCK = Block("grades", "Modules", ":material/school:",
              "Your modules: deadlines, study hours, weighted marks, what you need to hit your target, and your classification or GPA.",
              group="Study & work", page=_page, widgets=[Widget("modules", "Modules", _home, "small", ("small", "wide"), status=_modules_status, colour="#6B3FA0")], tools=TOOLS, prompt=PROMPT, context=_context,
              quick=[_quick], needs=_needs, schema=SCHEMA, migrate=_migrate, order=40, default=True, core=True)
