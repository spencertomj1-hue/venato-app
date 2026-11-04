"""
Grades: modules (credits, year, a target) with weighted assessments; the running average,
marks secured so far, what you need on the rest to hit your target, and an overall mark
for each year and the whole degree (credit-weighted, years weighted as you set) shown as a
UK classification or a US GPA. Marks are percentages.
"""

import re
import uuid

from venato import store
from venato.blocks import Block

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
"""


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

M_COLS = ("id", "name", "code", "credits", "year", "target", "final")
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


def add_module(name, credits=10, year=None, target=None, code=None):
    name = str(name or "").strip()
    if not name:
        raise GradeError("The module needs a name.")
    credits = float(credits or 10)
    if not 0 < credits <= 200:
        raise GradeError("Credits must be between 1 and 200.")
    if any(m["name"].lower() == name.lower() for m in modules()):
        raise GradeError(f"There's already a module called {name}.")
    mid = _id()
    with store.db() as conn:
        conn.execute(f"INSERT INTO gr_modules ({', '.join(M_COLS)}, created_at) VALUES (?, ?, ?, ?, ?, ?, NULL, ?)",
                     (mid, name, code, credits, year, _pct(target, "target"), store.stamp()))
    return mid


def update_module(mid, **fields):
    f = {k: v for k, v in fields.items() if k in M_COLS[1:]}
    for k in ("target", "final"):
        if k in f:
            f[k] = _pct(f[k], k)
    if f:
        with store.db() as conn:
            conn.execute(f"UPDATE gr_modules SET {', '.join(f'{k} = ?' for k in f)} WHERE id = ?", (*f.values(), mid))


def delete_module(mid):
    with store.db() as conn:
        conn.execute("DELETE FROM gr_assessments WHERE module_id = ?", (mid,))
        conn.execute("DELETE FROM gr_modules WHERE id = ?", (mid,))


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


BLOCK = Block("grades", "Grades", ":material/grade:",
              "Modules and weighted marks: averages, what you need to hit your target, and your classification or GPA.",
              group="Study & work", page=_page, home=_home, tools=TOOLS, prompt=PROMPT, context=_context,
              quick=[_quick], schema=SCHEMA, order=55)
