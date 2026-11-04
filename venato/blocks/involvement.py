"""
Involvement: the organisations you're part of (societies, clubs, church or faith community,
charities, volunteering, part-time work), your role in each and what you do for them, goals
per organisation, a log of what you did (volunteering hours, practice such as a service or
prayer, meetings, donations), and events with their tickets.
"""

import re
import uuid
from datetime import timedelta

from venato import store
from venato.blocks import Block

KINDS = ["Society", "Club", "Sports team", "Faith", "Charity", "Volunteering", "Work", "Other"]
ACTIVITIES = ["Volunteering", "Event", "Meeting", "Practice", "Donation", "Other"]
UNITS = ["hours", "times", "money"]
TICKETS = ["Not needed", "Need to buy", "Bought"]

SCHEMA = """
CREATE TABLE IF NOT EXISTS inv_orgs (
    id         TEXT PRIMARY KEY,
    name       TEXT NOT NULL UNIQUE COLLATE NOCASE,
    kind       TEXT NOT NULL DEFAULT 'Other',
    role       TEXT,                      -- e.g. Treasurer, Member, Volunteer
    duties     TEXT,                      -- what you do for them
    since      TEXT,
    active     INTEGER NOT NULL DEFAULT 1,
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS inv_goals (
    id         TEXT PRIMARY KEY,
    org_id     TEXT REFERENCES inv_orgs(id) ON DELETE CASCADE,
    text       TEXT NOT NULL,
    target     REAL,                      -- with unit: progress counts the log from 'start'
    unit       TEXT,                      -- hours / times / money
    start      TEXT NOT NULL,
    deadline   TEXT,
    done       INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS inv_log (
    id         TEXT PRIMARY KEY,
    org_id     TEXT REFERENCES inv_orgs(id) ON DELETE SET NULL,
    date       TEXT NOT NULL,
    kind       TEXT NOT NULL,             -- Volunteering / Event / Meeting / Practice / Donation / Other
    title      TEXT,
    hours      REAL,
    amount     REAL,                      -- donations
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS inv_events (
    id         TEXT PRIMARY KEY,
    org_id     TEXT REFERENCES inv_orgs(id) ON DELETE SET NULL,
    title      TEXT NOT NULL,
    date       TEXT NOT NULL,
    start      TEXT,
    location   TEXT,
    ticket     TEXT NOT NULL DEFAULT 'Not needed',
    price      REAL,
    url        TEXT,
    note       TEXT,
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS inv_log_date ON inv_log(date);
CREATE INDEX IF NOT EXISTS inv_events_date ON inv_events(date);
"""


class InvError(ValueError):
    pass


def _id():
    return uuid.uuid4().hex


def _num(v, what, allow_none=True):
    if v in (None, ""):
        if allow_none:
            return None
        raise InvError(f"The {what} is missing.")
    try:
        v = float(str(v).replace("£", "").replace("$", "").replace("€", "").replace(",", "").strip())
    except ValueError:
        raise InvError(f"'{v}' isn't a number for the {what}.")
    if v < 0 or v > 1_000_000:
        raise InvError(f"The {what} must be between 0 and 1,000,000.")
    return v


def _date(v):
    return str(store._as_date(v)) if v else None


def _time(v):
    if not v:
        return None
    v = str(v).strip()
    if not re.fullmatch(r"([01]?\d|2[0-3]):[0-5]\d", v):
        raise InvError(f"'{v}' isn't a time like 19:30.")
    return v.zfill(5)


def _url(v):
    v = str(v or "").strip()
    if v and not re.match(r"https?://", v, re.I):
        raise InvError("A link must start with http:// or https://.")
    return v or None


# --- Organisations ---

O_COLS = ("id", "name", "kind", "role", "duties", "since", "active")


def orgs(active_only=False):
    with store.db() as conn:
        rows = conn.execute(f"SELECT {', '.join(O_COLS)} FROM inv_orgs" + (" WHERE active = 1" if active_only else "")
                            + " ORDER BY active DESC, name").fetchall()
    return [dict(zip(O_COLS, r)) for r in rows]


def find_org(name):
    want = str(name or "").strip().lower()
    if not want:
        return None
    pool = orgs()
    hit = [o for o in pool if o["name"].lower() == want or o["id"] == name]
    if hit:
        return hit[0]
    part = [o for o in pool if want in o["name"].lower() or o["name"].lower() in want]
    return part[0] if len(part) == 1 else None


def add_org(name, kind="Other", role=None, duties=None, since=None):
    name = str(name or "").strip()
    if not name:
        raise InvError("The organisation needs a name.")
    if kind not in KINDS:
        kind = "Other"
    oid = _id()
    with store.db() as conn:
        if conn.execute("SELECT 1 FROM inv_orgs WHERE name = ? COLLATE NOCASE", (name,)).fetchone():
            raise InvError(f"There's already {name}.")
        conn.execute(f"INSERT INTO inv_orgs ({', '.join(O_COLS)}, created_at) VALUES (?, ?, ?, ?, ?, ?, 1, ?)",
                     (oid, name, kind, (role or "").strip() or None, (duties or "").strip() or None, _date(since),
                      store.stamp()))
    return oid


def update_org(oid, **fields):
    f = {k: v for k, v in fields.items() if k in O_COLS[1:]}
    if "name" in f and not str(f["name"]).strip():
        raise InvError("The organisation needs a name.")
    if "kind" in f and f["kind"] not in KINDS:
        f["kind"] = "Other"
    if "since" in f:
        f["since"] = _date(f["since"])
    if "active" in f:
        f["active"] = int(bool(f["active"]))
    if f:
        with store.db() as conn:
            conn.execute(f"UPDATE inv_orgs SET {', '.join(f'{k} = ?' for k in f)} WHERE id = ?", (*f.values(), oid))


def delete_org(oid):
    with store.db() as conn:
        conn.execute("DELETE FROM inv_goals WHERE org_id = ?", (oid,))
        conn.execute("UPDATE inv_log SET org_id = NULL WHERE org_id = ?", (oid,))
        conn.execute("UPDATE inv_events SET org_id = NULL WHERE org_id = ?", (oid,))
        conn.execute("DELETE FROM inv_orgs WHERE id = ?", (oid,))


def _org_id(org):
    if not org:
        return None
    o = find_org(org)
    if not o:
        raise InvError(f"No organisation called '{org}'. There's: {', '.join(x['name'] for x in orgs()) or 'none yet'}.")
    return o["id"]


# --- The log ---

L_COLS = ("id", "org_id", "date", "kind", "title", "hours", "amount")


def log(kind, org=None, hours=None, amount=None, title=None, day=None):
    if kind not in ACTIVITIES:
        raise InvError(f"The kind is one of {', '.join(ACTIVITIES)}.")
    hours, amount = _num(hours, "hours"), _num(amount, "amount")
    if hours is not None and hours > 24:
        raise InvError("That's more than 24 hours in a day.")
    if kind == "Donation" and not amount:
        raise InvError("A donation needs an amount.")
    lid = _id()
    with store.db() as conn:
        conn.execute(f"INSERT INTO inv_log ({', '.join(L_COLS)}, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                     (lid, _org_id(org), _date(day) or store.local_today().isoformat(), kind,
                      (str(title).strip() or None) if title else None, hours, amount, store.stamp()))
    return lid


def entries(first=None, last=None, org_id=None):
    q = (f"SELECT {', '.join('l.' + c for c in L_COLS)}, o.name FROM inv_log l LEFT JOIN inv_orgs o ON o.id = l.org_id "
         "WHERE l.date BETWEEN ? AND ?")
    args = [str(first or "0000-01-01"), str(last or "9999-12-31")]
    if org_id:
        q += " AND l.org_id = ?"
        args.append(org_id)
    with store.db() as conn:
        rows = conn.execute(q + " ORDER BY l.date DESC, l.created_at DESC", args).fetchall()
    return [dict(zip(L_COLS + ("org",), r)) for r in rows]


def delete_entry(lid):
    with store.db() as conn:
        conn.execute("DELETE FROM inv_log WHERE id = ?", (lid,))


def totals(first=None, last=None, org_id=None):
    rows = entries(first, last, org_id)
    return {"hours": sum(r["hours"] or 0 for r in rows), "donated": sum(r["amount"] or 0 for r in rows),
            "volunteering": sum(r["hours"] or 0 for r in rows if r["kind"] == "Volunteering"),
            "practice": sum(1 for r in rows if r["kind"] == "Practice"),
            "events": sum(1 for r in rows if r["kind"] == "Event"), "count": len(rows)}


# --- Goals ---

G_COLS = ("id", "org_id", "text", "target", "unit", "start", "deadline", "done")


def goals(org_id=None, open_only=False):
    q = f"SELECT {', '.join('g.' + c for c in G_COLS)}, o.name FROM inv_goals g LEFT JOIN inv_orgs o ON o.id = g.org_id WHERE 1"
    args = []
    if org_id:
        q += " AND g.org_id = ?"
        args.append(org_id)
    if open_only:
        q += " AND g.done = 0"
    with store.db() as conn:
        rows = conn.execute(q + " ORDER BY g.done, g.deadline IS NULL, g.deadline, g.created_at", args).fetchall()
    return [dict(zip(G_COLS + ("org",), r)) for r in rows]


def add_goal(org, text, target=None, unit=None, deadline=None, start=None):
    text = str(text or "").strip()
    if not text:
        raise InvError("What's the goal?")
    target = _num(target, "target")
    if target is not None and unit not in UNITS:
        raise InvError(f"A target needs a unit: {', '.join(UNITS)}.")
    gid = _id()
    with store.db() as conn:
        conn.execute(f"INSERT INTO inv_goals ({', '.join(G_COLS)}, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, 0, ?)",
                     (gid, _org_id(org), text, target, unit if target is not None else None,
                      _date(start) or store.local_today().isoformat(), _date(deadline), store.stamp()))
    return gid


def set_goal_done(gid, done=True):
    with store.db() as conn:
        conn.execute("UPDATE inv_goals SET done = ? WHERE id = ?", (int(bool(done)), gid))


def delete_goal(gid):
    with store.db() as conn:
        conn.execute("DELETE FROM inv_goals WHERE id = ?", (gid,))


def goal_progress(g):
    """How far a goal with a target has got: the log for its organisation (or everything, for a
    goal with none) from its start up to its deadline."""
    if g["target"] is None:
        return None
    rows = entries(g["start"], g["deadline"], g["org_id"])
    have = {"hours": sum(r["hours"] or 0 for r in rows), "money": sum(r["amount"] or 0 for r in rows),
            "times": len(rows)}[g["unit"]]
    return {"have": have, "pct": min(100.0, 100 * have / g["target"]) if g["target"] else 100.0}


# --- Events ---

E_COLS = ("id", "org_id", "title", "date", "start", "location", "ticket", "price", "url", "note")


def add_event(title, day, org=None, start=None, location=None, ticket="Not needed", price=None, url=None, note=None):
    title = str(title or "").strip()
    if not title or not day:
        raise InvError("An event needs a title and a date.")
    if ticket not in TICKETS:
        raise InvError(f"The ticket is one of: {', '.join(TICKETS)}.")
    eid = _id()
    with store.db() as conn:
        conn.execute(f"INSERT INTO inv_events ({', '.join(E_COLS)}, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                     (eid, _org_id(org), title, _date(day), _time(start), (location or "").strip() or None, ticket,
                      _num(price, "price"), _url(url), (note or "").strip() or None, store.stamp()))
    return eid


def events(first=None, last=None):
    with store.db() as conn:
        rows = conn.execute(f"SELECT {', '.join('e.' + c for c in E_COLS)}, o.name FROM inv_events e "
                            "LEFT JOIN inv_orgs o ON o.id = e.org_id WHERE e.date BETWEEN ? AND ? "
                            "ORDER BY e.date, e.start IS NULL, e.start",
                            (str(first or "0000-01-01"), str(last or "9999-12-31"))).fetchall()
    return [dict(zip(E_COLS + ("org",), r)) for r in rows]


def upcoming(days=30):
    today = store.local_today()
    return events(today, today + timedelta(days=days))


def update_event(eid, **fields):
    f = {k: v for k, v in fields.items() if k in E_COLS[1:]}
    if "ticket" in f and f["ticket"] not in TICKETS:
        raise InvError(f"The ticket is one of: {', '.join(TICKETS)}.")
    if "date" in f:
        f["date"] = _date(f["date"])
    if "start" in f:
        f["start"] = _time(f["start"])
    if "url" in f:
        f["url"] = _url(f["url"])
    if "price" in f:
        f["price"] = _num(f["price"], "price")
    if f:
        with store.db() as conn:
            conn.execute(f"UPDATE inv_events SET {', '.join(f'{k} = ?' for k in f)} WHERE id = ?", (*f.values(), eid))


def delete_event(eid):
    with store.db() as conn:
        conn.execute("DELETE FROM inv_events WHERE id = ?", (eid,))


def attended(eid, hours=None):
    """Move a past event into the log (as an Event)."""
    e = next((x for x in events() if x["id"] == eid), None)
    if not e:
        raise InvError("No such event.")
    return log("Event", e["org_id"], hours, None, e["title"], e["date"])


# --- The assistant ---

def _money(v):
    try:
        from venato.blocks import money
        return money.fmt(v)
    except Exception:
        return f"£{v:,.2f}"


def _wrap(fn):
    from venato import tools
    try:
        return fn()
    except InvError as e:
        raise tools.ToolError(str(e))


def tool_org(name, kind="Other", role=None, duties=None):
    from venato import tools
    o = find_org(name)
    if o and o["name"].lower() == str(name).strip().lower():
        _wrap(lambda: update_org(o["id"], **{k: v for k, v in (("kind", kind if kind != "Other" else None),
                                                                 ("role", role), ("duties", duties)) if v}))
        return tools.Result(f"Updated {o['name']}.", changed=True)
    _wrap(lambda: add_org(name, kind, role, duties))
    return tools.Result(f"Added {name}" + (f" ({role})" if role else "") + ".", changed=True)


def tool_log(kind, organisation=None, hours=None, amount=None, title=None, date=None):
    from venato import tools
    _wrap(lambda: log(kind, organisation, hours, amount, title, date))
    bits = [kind.lower()] + ([f"{hours:g} h"] if hours else []) + ([_money(float(amount))] if amount else [])
    o = find_org(organisation) if organisation else None
    return tools.Result(f"Logged {' · '.join(bits)}" + (f" for {o['name']}" if o else "") + (f": {title}" if title else "")
                        + ".", changed=True)


def tool_event(title, date, organisation=None, start=None, location=None, ticket="Not needed", price=None, url=None):
    from venato import tools
    _wrap(lambda: add_event(title, date, organisation, start, location, ticket, price, url))
    return tools.Result(f"Added {title} on {store._as_date(date):%a %-d %b}" + (f" at {start}" if start else "")
                        + (" — ticket still to buy." if ticket == "Need to buy" else "."), changed=True)


def tool_goal(text, organisation=None, target=None, unit=None, deadline=None):
    from venato import tools
    _wrap(lambda: add_goal(organisation, text, target, unit, deadline))
    return tools.Result(f"Goal added: {text}.", changed=True)


def tool_summary(period_days=30):
    from venato import tools
    today = store.local_today()
    first = today - timedelta(days=int(period_days or 30) - 1)
    lines = []
    for o in orgs(active_only=True):
        t = totals(first, today, o["id"])
        lines.append(f"- {o['name']} ({o['kind']}{', ' + o['role'] if o['role'] else ''}): {t['count']} entries, "
                     f"{t['hours']:g} h" + (f", donated {_money(t['donated'])}" if t["donated"] else "")
                     + (f". Does: {o['duties']}" if o["duties"] else ""))
    t = totals(first, today)
    lines.insert(0, f"Last {period_days} days: {t['volunteering']:g} h volunteering, {t['practice']} practice, "
                    f"{t['events']} events, donated {_money(t['donated'])}.")
    for g in goals(open_only=True):
        p = goal_progress(g)
        lines.append(f"Goal{' (' + g['org'] + ')' if g['org'] else ''}: {g['text']}"
                     + (f" — {p['have']:g}/{g['target']:g} {g['unit']}" if p else "")
                     + (f", by {g['deadline']}" if g["deadline"] else ""))
    ev = upcoming(30)
    if ev:
        lines.append("Coming up: " + "; ".join(f"{e['title']} {e['date']}" + (" (ticket to buy)" if e["ticket"] == "Need to buy" else "")
                                               for e in ev[:6]))
    return tools.Result("\n".join(lines))


PROMPT = """- Involvement: organisations the user is part of (societies, clubs, faith community, charities,
  volunteering, work) with their role and duties, goals per organisation, a log (Volunteering hours,
  Practice such as a church service or prayer, Meetings, Events, Donations), and events with tickets.
  add_organisation(name, kind, role, duties); log_involvement(kind, organisation, hours, amount, title, date);
  add_event(title, date, organisation, start, location, ticket, price, url); add_involvement_goal(text,
  organisation, target, unit hours/times/money, deadline); involvement_summary(period_days)."""

_ORG = {"organisation": {"type": "string"}}
TOOLS = [
    ("add_organisation", "Add (or update) an organisation: name, kind, the user's role, what they do for it.",
     {"type": "object", "properties": {"name": {"type": "string"}, "kind": {"type": "string", "enum": KINDS},
                                       "role": {"type": "string"}, "duties": {"type": "string"}},
      "required": ["name"]}, tool_org),
    ("log_involvement", "Log volunteering hours, a practice (service, prayer), a meeting, an event or a donation.",
     {"type": "object", "properties": {"kind": {"type": "string", "enum": ACTIVITIES}, **_ORG,
                                       "hours": {"type": "number"}, "amount": {"type": "number"},
                                       "title": {"type": "string"}, "date": {"type": "string"}},
      "required": ["kind"]}, tool_log),
    ("add_event", "Add an event (with ticket status: Not needed / Need to buy / Bought).",
     {"type": "object", "properties": {"title": {"type": "string"}, "date": {"type": "string"}, **_ORG,
                                       "start": {"type": "string", "description": "HH:MM"}, "location": {"type": "string"},
                                       "ticket": {"type": "string", "enum": TICKETS}, "price": {"type": "number"},
                                       "url": {"type": "string"}}, "required": ["title", "date"]}, tool_event),
    ("add_involvement_goal", "A goal for an organisation (or overall), optionally with a target in hours / times / money.",
     {"type": "object", "properties": {"text": {"type": "string"}, **_ORG, "target": {"type": "number"},
                                       "unit": {"type": "string", "enum": UNITS}, "deadline": {"type": "string"}},
      "required": ["text"]}, tool_goal),
    ("involvement_summary", "Organisations, roles, recent hours / practice / donations, goals and upcoming events.",
     {"type": "object", "properties": {"period_days": {"type": "integer"}}, "required": []}, tool_summary),
]

Q_VOL = re.compile(r"(?:i\s+)?volunteered\s+(?:for\s+)?(\d+(?:\.\d+)?)\s*(?:h|hr|hrs|hours?)(?:\s+(?:at|with|for)\s+(.+))?")
Q_DON = re.compile(r"(?:i\s+)?donated\s+[£$€]?(\d+(?:\.\d{1,2})?)(?:\s+(?:to|for)\s+(.+))?")
Q_PRAC = re.compile(r"(?:i\s+)?(?:went to|been to|attended)\s+(church|mass|mosque|temple|synagogue|gurdwara|a service|service)")


def _quick(text, day):
    """'volunteered 3h at oxfam', 'donated £10 to shelter', 'went to church'."""
    from venato import tools
    for rx, kind in ((Q_VOL, "Volunteering"), (Q_DON, "Donation")):
        m = rx.fullmatch(text)
        if m:
            org = m.group(2)
            if org and not find_org(org):
                raise tools.ToolError("unknown organisation")      # let Claude handle (and maybe add it)
            n = float(m.group(1))
            return tool_log(kind, org, n if kind == "Volunteering" else None, n if kind == "Donation" else None,
                            None, day.isoformat())
    m = Q_PRAC.fullmatch(text)
    if m:
        faith = [o for o in orgs(True) if o["kind"] == "Faith"]
        return tool_log("Practice", faith[0]["name"] if len(faith) == 1 else None, None, None,
                        m.group(1).replace("a ", "").capitalize(), day.isoformat())
    return None


def _context():
    today = store.local_today()
    ev = upcoming(7)
    t = totals(today - timedelta(days=6), today)
    text = f"Involvement this week: {t['volunteering']:g} h volunteering, {t['practice']} practice."
    if ev:
        text += " Events this week: " + ", ".join(f"{e['title']} {e['date']}" + (f" {e['start']}" if e["start"] else "")
                                                  + (" (ticket to buy)" if e["ticket"] == "Need to buy" else "") for e in ev) + "."
    return text


def _page():
    from venato.ui import involvement as ui
    ui.render_page()


def _home():
    from venato.ui import involvement as ui
    ui.render_home()


BLOCK = Block("involvement", "Involvement", ":material/diversity_3:",
              "Societies, clubs, faith, volunteering and charities: your roles, goals, hours, donations and events.",
              group="People & life", page=_page, home=_home, tools=TOOLS, prompt=PROMPT, context=_context,
              quick=[_quick], schema=SCHEMA, order=75)
