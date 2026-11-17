"""
Applications: jobs, internships, grad schemes, courses... one row each, with where it's up to.
The page is venato/ui/applications.py; this file holds its table, the store functions, Claude's
tools, its line in the [Now] snapshot and Home search.
"""

import uuid

from venato import store, tools
from venato.blocks import Block

SCHEMA = """
-- Applications: jobs, internships, courses... one row each, with where it's up to
CREATE TABLE IF NOT EXISTS applications (
    id          TEXT PRIMARY KEY,
    industry    TEXT,
    company     TEXT,
    route       TEXT,                        -- e.g. Graduate scheme, Internship, Spring week
    description TEXT,
    contact     TEXT,                        -- contact / lead
    deadline    TEXT,                        -- YYYY-MM-DD, or NULL
    status      TEXT NOT NULL,
    notes       TEXT,
    created_at  TEXT NOT NULL,
    updated_at  TEXT NOT NULL
);
"""


# ---------------------------------------------------------------------------
# Store
# ---------------------------------------------------------------------------

APP_STATUSES = ["To apply", "Applied", "Online test", "Interview", "Assessment centre",
                "Offer", "Accepted", "Rejected", "Withdrawn"]
APP_TEXT = ("industry", "company", "route", "description", "contact", "notes")
APP_COLS = "id, " + ", ".join(APP_TEXT[:5]) + ", deadline, status, notes, created_at, updated_at"


def _application_fields(fields):
    """Tidy user input: stripped text (blank -> None), a real date or None, a known status."""
    out = {}
    for k, v in fields.items():
        if k in APP_TEXT:
            out[k] = (str(v).strip() if v is not None and str(v) not in ("nan", "NaT", "None") else "") or None
        elif k == "deadline":
            out[k] = store._as_date(str(v)[:10]).isoformat() if v not in (None, "") and str(v) not in ("nan", "NaT", "None") else None
        elif k == "status":
            if v not in APP_STATUSES:
                raise ValueError(f"Status must be one of: {', '.join(APP_STATUSES)}.")
            out[k] = v
        else:
            raise ValueError(f"Unknown application field: {k}")
    return out


def add_application(status="To apply", **fields):
    """Add an application; returns its id. Fields: industry, company, route, description,
    contact, deadline, notes."""
    row = _application_fields({"status": status or "To apply", **fields})
    if not any(row.get(k) for k in ("company", "industry", "route", "description")):
        raise ValueError("Say at least the company (or what it's for).")
    aid, now = uuid.uuid4().hex, store.stamp()
    cols = ["id", *row, "created_at", "updated_at"]
    with store.db() as conn:
        conn.execute(f"INSERT INTO applications ({', '.join(cols)}) VALUES ({', '.join('?' * len(cols))})",
                     (aid, *row.values(), now, now))
    return aid


def applications():
    """Every application: soonest deadline first (no deadline last), then newest."""
    with store.db() as conn:
        rows = conn.execute(f"SELECT {APP_COLS} FROM applications "
                            "ORDER BY deadline IS NULL, deadline, created_at DESC").fetchall()
    return [dict(zip(APP_COLS.split(", "), r)) for r in rows]


def get_application(aid):
    with store.db() as conn:
        row = conn.execute(f"SELECT {APP_COLS} FROM applications WHERE id = ?", (aid,)).fetchone()
    return dict(zip(APP_COLS.split(", "), row)) if row else None


def update_application(aid, **fields):
    row = _application_fields(fields)
    if row:
        with store.db() as conn:
            conn.execute(f"UPDATE applications SET {', '.join(f'{k} = ?' for k in row)}, updated_at = ? WHERE id = ?",
                         (*row.values(), store.stamp(), aid))


def delete_application(aid):
    with store.db() as conn:
        conn.execute("DELETE FROM applications WHERE id = ?", (aid,))



# ---------------------------------------------------------------------------
# Claude's tools
# ---------------------------------------------------------------------------

APP_FIELDS = ("industry", "company", "route", "description", "contact", "deadline", "status", "notes")


def describe_application(a, today=None):
    name = a["company"] or a["industry"] or a["route"] or "Application"
    bits = [x for x in (a["route"], a["industry"]) if x and x != name]
    due = f", deadline {tools.nice_day(a['deadline'])} ({store.countdown(a['deadline'], today)})" if a["deadline"] else ""
    return f"{name}{' (' + ', '.join(bits) + ')' if bits else ''}: {a['status']}{due}"


def _find_application(application):
    found = get_application(str(application).strip())
    if found:
        return found
    pool = [{**a, "title": " ".join(x for x in (a["company"], a["route"], a["industry"]) if x)}
            for a in applications()]
    matches = tools._best_match(pool, application)
    if len(matches) == 1:
        return matches[0]
    if matches:
        options = "; ".join(f"id {a['id']}: {describe_application(a)}" for a in matches)
        raise tools.ToolError(f"More than one application matches '{application}': {options}. "
                              "Ask the user which one, or pass its id.")
    raise tools.ToolError(f"There's no application matching '{application}'. Use list_applications to see them.")


def _status(value):
    if value is None:
        return None
    want = str(value).strip().lower()
    for s in APP_STATUSES:
        if s.lower() == want:
            return s
    raise tools.ToolError(f"Status must be one of: {', '.join(APP_STATUSES)}.")


def tool_list_applications(status=None, query=None):
    rows = applications()
    if status:
        rows = [a for a in rows if a["status"] == _status(status)]
    if query:
        words = str(query).lower().split()
        rows = [a for a in rows if all(w in " ".join(str(a[k] or "") for k in APP_FIELDS).lower() for w in words)]
    if not rows:
        return tools.Result("No applications" + (" match." if status or query else " yet."))
    out = []
    for a in rows:
        extra = "; ".join(f"{k}: {a[k]}" for k in ("description", "contact", "notes") if a[k])
        out.append(f"- id {a['id']}: {describe_application(a)}" + (f" — {extra}" if extra else ""))
    return tools.Result("\n".join(out))


def tool_add_application(company=None, industry=None, route=None, description=None, contact=None,
                    deadline=None, status=None, notes=None):
    try:
        aid = add_application(status=_status(status) or "To apply", company=company, industry=industry,
                                    route=route, description=description, contact=contact,
                                    deadline=tools._day(deadline) if deadline else None, notes=notes)
    except ValueError as e:
        raise tools.ToolError(str(e))
    return tools.Result(f"Added the application {describe_application(get_application(aid))}.", changed=True)


def tool_edit_application(application, confirmed=False, append_notes=False, **changes):
    """Change any of an application's fields. Text that replaces something already written
    needs the user's confirmation; status changes and filling empty fields don't."""
    a = _find_application(application)
    fields = {k: v for k, v in changes.items() if k in APP_FIELDS and v is not None}
    if not fields:
        return tools.Result("Nothing to change: give the fields to update.")
    if "status" in fields:
        fields["status"] = _status(fields["status"])
    if "deadline" in fields:
        fields["deadline"] = tools._day(fields["deadline"]) if fields["deadline"] else None
    if append_notes and fields.get("notes") and a["notes"]:
        fields["notes"] = f"{a['notes']}\n{fields['notes']}"
    replaced = [k for k in ("description", "contact", "notes") if k in fields and a[k] and fields[k] != a[k]
                and not (k == "notes" and append_notes)]
    if replaced and not confirmed:
        return tools.Result("", pending=tools.Pending(f"Change {', '.join(replaced)} of {describe_application(a)}",
                                                      lambda: tool_edit_application(a["id"], True, False, **fields)))
    try:
        update_application(a["id"], **fields)
    except ValueError as e:
        raise tools.ToolError(str(e))
    return tools.Result(f"Updated: {describe_application(get_application(a['id']))}.", changed=True)


def tool_delete_application(application, confirmed=False):
    a = _find_application(application)
    if not confirmed:
        return tools.Result("", pending=tools.Pending(f"Delete the application {describe_application(a)}",
                                                      lambda: tool_delete_application(a["id"], True)))
    delete_application(a["id"])
    return tools.Result(f"Deleted the application {a['company'] or 'entry'}.", changed=True)


PROMPT = f"""
- Applications: the Applications page is a table of things the user has applied for, or means to
  (jobs, internships, grad schemes, courses). Each has industry, company, route (e.g. "Graduate scheme",
  "Internship", "Spring week"), description, contact (contact / lead: who they know there or who to ask),
  deadline, status and notes. Status is one of: {", ".join(APP_STATUSES)}.
  - "I applied to Acme's internship, deadline 1 Dec" -> add_application(company="Acme", route="Internship",
    status="Applied", deadline=...). New ones default to "To apply".
  - "got an interview at Acme" -> edit_application(application="Acme", status="Interview"). Use
    append_notes=true to add to the notes rather than replace them. list_applications shows them
    (filter by status or words); delete_application needs confirmation.
  - Applying for something with a deadline doesn't also need add_deadline unless they ask: the table
    has its own countdown.
"""

DATE = {"type": "string", "description": "YYYY-MM-DD"}
APP_STATUS = {"type": "string", "enum": APP_STATUSES}
APP_PROPS = {"company": {"type": "string"}, "industry": {"type": "string"},
             "route": {"type": "string", "description": "e.g. Graduate scheme, Internship, Spring week"},
             "description": {"type": "string"},
             "contact": {"type": "string", "description": "contact / lead: who they know there, or who to ask"},
             "deadline": DATE, "status": APP_STATUS, "notes": {"type": "string"}}


def _schema(required, **props):
    return {"type": "object", "properties": props, "required": list(required)}


TOOLS = [
    ("list_applications", "List applications (with ids), optionally by status or matching words.",
     _schema([], status=APP_STATUS, query={"type": "string"}), tool_list_applications),
    ("add_application", "Add an application (a job, internship, course...). At least a company or what it's for.",
     _schema([], **APP_PROPS), tool_add_application),
    ("edit_application", "Change an application's fields, found by company (or id). Only pass what changes.",
     _schema(["application"], application={"type": "string", "description": "company / route words, or its id"},
             append_notes={"type": "boolean", "description": "add to the notes instead of replacing them"},
             **APP_PROPS), tool_edit_application),
    ("delete_application", "Delete an application (needs the user's confirmation).",
     _schema(["application"], application={"type": "string"}), tool_delete_application),
]

# What the chat shows while one of these tools runs (word in the tool's name -> label).
STATUS = {"application": "Updating your applications"}

DONE = ("Accepted", "Rejected", "Withdrawn")          # finished: left out of the [Now] snapshot


def _context():
    """The applications still in progress, with ids."""
    return "\n".join(l for l in tool_list_applications().text.splitlines() if not any(f": {s}" in l for s in DONE))


# kind -> (SQL giving (id, title, detail, date, extra), haystack)
SEARCH = {
    "Application": ("SELECT id, COALESCE(company, industry, route, 'Application'), "
                    "TRIM(COALESCE(route, '') || ' · ' || status, ' ·'), deadline, status FROM applications",
                    "COALESCE(industry, '') || ' ' || COALESCE(company, '') || ' ' || COALESCE(route, '') || ' ' || "
                    "COALESCE(description, '') || ' ' || COALESCE(contact, '') || ' ' || COALESCE(notes, '')"),
}


def _search_open(r, ss):
    ss["page"] = "Applications"
    ss.pop("apps_filter", None)


def _page():
    from venato.ui import applications as ui
    ui.render_page()


BLOCK = Block("applications", "Applications", ":material/work:",
              "A table of jobs, internships and courses you've applied for, with status and deadlines.",
              group="Study & work", page=_page, tools=TOOLS, prompt=PROMPT, context=_context, schema=SCHEMA,
              order=60, default=True, search=SEARCH, search_icons={"Application": "work"}, search_open=_search_open,
              status=STATUS)
