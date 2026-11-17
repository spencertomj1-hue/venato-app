"""
Network: the people the user knows, the groups that colour them (groups can sit inside groups),
who knows whom, and the times the user saw or spoke to someone. The page is venato/ui/network.py;
this file holds its tables, the store functions, Claude's tools, Home search and the weekly
review's "People you saw".

Links are undirected and stored once, with the smaller id first (net_links has CHECK (a < b)),
so "A knows B" and "B knows A" are the same row.
"""

import re
import uuid

from venato import store, tools
from venato.blocks import Block

# Network groups (they colour people in the Network web); editable on the Network page.
DEFAULT_NET_GROUPS = [
    ("family", "Family", "#E5484D"),
    ("friends", "Friends", "#F5A524"),
    ("uni", "Uni", "#3E8EF7"),
    ("work", "Work", "#30A46C"),
    ("mentors", "Mentors", "#8E4EC6"),
    ("other", "Other", "#8B8D98"),
]

SCHEMA = """
-- Network: people you know, the groups that colour them, and who knows whom
CREATE TABLE IF NOT EXISTS net_groups (
    id     TEXT PRIMARY KEY,
    name   TEXT NOT NULL UNIQUE COLLATE NOCASE,
    colour TEXT NOT NULL,                    -- "#RRGGBB"
    ord    INTEGER NOT NULL,
    parent_id TEXT                           -- the group it sits inside; NULL = top level
);
CREATE TABLE IF NOT EXISTS net_people (
    id          TEXT PRIMARY KEY,
    name        TEXT NOT NULL,
    description TEXT,                        -- who they are, how you know them
    works_for   TEXT,                        -- company, university, team...
    group_id    TEXT REFERENCES net_groups(id) ON DELETE SET NULL,
    created_at  TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS net_links (       -- undirected: always stored with a < b
    a      TEXT NOT NULL REFERENCES net_people(id) ON DELETE CASCADE,
    b      TEXT NOT NULL REFERENCES net_people(id) ON DELETE CASCADE,
    reason TEXT,                             -- how they know each other
    PRIMARY KEY (a, b),
    CHECK (a < b)
);
-- Times the user saw or spoke to someone ("had coffee, talked about X")
CREATE TABLE IF NOT EXISTS net_interactions (
    id         TEXT PRIMARY KEY,
    person_id  TEXT NOT NULL REFERENCES net_people(id) ON DELETE CASCADE,
    date       TEXT NOT NULL,                -- YYYY-MM-DD
    note       TEXT NOT NULL,
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS net_interactions_person ON net_interactions (person_id, date);
"""


def _migrate(conn):
    store._add_column(conn, "net_groups", "parent_id", "TEXT")       # sub-groups came later
    if conn.execute("SELECT COUNT(*) FROM net_groups").fetchone()[0] == 0:
        conn.executemany("INSERT INTO net_groups (id, name, colour, ord) VALUES (?, ?, ?, ?)",
                         [(gid, name, colour, i) for i, (gid, name, colour) in enumerate(DEFAULT_NET_GROUPS)])


# ---------------------------------------------------------------------------
# Store: people, groups, links, interactions
# ---------------------------------------------------------------------------

PERSON_COLS = ("id", "name", "description", "works_for", "group_id", "created_at")


def net_groups():
    """[{id, name, colour, parent_id}] in order: each group's sub-groups follow it."""
    with store.db() as conn:
        rows = conn.execute("SELECT id, name, colour, parent_id FROM net_groups ORDER BY ord, name").fetchall()
    groups = [dict(zip(("id", "name", "colour", "parent_id"), r)) for r in rows]
    ids = {g["id"] for g in groups}
    out = []

    def walk(parent):
        for g in groups:
            if g["parent_id"] == parent or (parent is None and g["parent_id"] not in ids):
                out.append(g)
                walk(g["id"])
    walk(None)
    return out


def group_path(group_id, groups=None):
    """"Northfield › Physics Society" for a sub-group, or just the name."""
    by_id = {g["id"]: g for g in (groups or net_groups())}
    names, gid = [], group_id
    while gid in by_id and len(names) < 10:
        names.append(by_id[gid]["name"])
        gid = by_id[gid]["parent_id"]
    return " › ".join(reversed(names))


def _descendants(conn, group_id):
    """Ids of a group's sub-groups, their sub-groups, and so on."""
    found, todo = set(), [group_id]
    while todo:
        kids = [r[0] for r in conn.execute(
            f"SELECT id FROM net_groups WHERE parent_id IN ({','.join('?' * len(todo))})", todo)]
        todo = [k for k in kids if k not in found]
        found.update(todo)
    return found


def find_net_group(name):
    """A group's id by name (any case), or None. Group names are unique."""
    with store.db() as conn:
        row = conn.execute("SELECT id FROM net_groups WHERE name = ? COLLATE NOCASE", (str(name).strip(),)).fetchone()
    return row[0] if row else None


def add_net_group(name, colour=None, parent_id=None):
    """A new group (inside `parent_id`, if given). Sub-groups take their parent's colour unless given one."""
    name = str(name).strip()
    if not name:
        raise ValueError("A group needs a name.")
    gid = uuid.uuid4().hex[:8]
    with store.db() as conn:
        if not colour and parent_id:
            row = conn.execute("SELECT colour FROM net_groups WHERE id = ?", (parent_id,)).fetchone()
            colour = row[0] if row else None
        conn.execute("INSERT INTO net_groups (id, name, colour, ord, parent_id) "
                     "VALUES (?, ?, ?, (SELECT COALESCE(MAX(ord) + 1, 0) FROM net_groups), ?)",
                     (gid, name, (colour or "#8B8D98").upper(), parent_id))
    return gid


NO_CHANGE = object()   # update_net_group / update_person: leave this field as it is


def update_net_group(group_id, name=None, colour=None, parent_id=NO_CHANGE):
    """Rename, recolour or move a group (parent_id=None puts it at the top level)."""
    fields = {}
    if name is not None:
        fields["name"] = str(name).strip()
        if not fields["name"]:
            raise ValueError("A group needs a name.")
    if colour is not None:
        fields["colour"] = colour.upper()
    with store.db() as conn:
        if parent_id is not NO_CHANGE:
            if parent_id == group_id or parent_id in _descendants(conn, group_id):
                raise ValueError("A group can't sit inside itself or one of its own sub-groups.")
            fields["parent_id"] = parent_id
        if fields:
            conn.execute(f"UPDATE net_groups SET {', '.join(f'{k} = ?' for k in fields)} WHERE id = ?",
                         (*fields.values(), group_id))


def delete_net_group(group_id):
    """Remove a group. Its sub-groups and people move up to the group it was inside (or the top level)."""
    with store.db() as conn:
        row = conn.execute("SELECT parent_id FROM net_groups WHERE id = ?", (group_id,)).fetchone()
        if not row:
            return
        conn.execute("UPDATE net_groups SET parent_id = ? WHERE parent_id = ?", (row[0], group_id))
        conn.execute("UPDATE net_people SET group_id = ? WHERE group_id = ?", (row[0], group_id))
        conn.execute("DELETE FROM net_groups WHERE id = ?", (group_id,))


def net_people():
    """Everyone, by name."""
    with store.db() as conn:
        rows = conn.execute(f"SELECT {', '.join(PERSON_COLS)} FROM net_people ORDER BY name COLLATE NOCASE").fetchall()
    return [dict(zip(PERSON_COLS, r)) for r in rows]


def get_person(person_id):
    with store.db() as conn:
        row = conn.execute(f"SELECT {', '.join(PERSON_COLS)} FROM net_people WHERE id = ?", (person_id,)).fetchone()
    return dict(zip(PERSON_COLS, row)) if row else None


def find_people(name):
    """People whose name matches exactly (any case), else whose name contains `name`."""
    want = str(name).strip().lower()
    everyone = net_people()
    return [p for p in everyone if p["name"].lower() == want] or [p for p in everyone if want in p["name"].lower()]


def _person_fields(name=None, description=None, works_for=None):
    out = {}
    if name is not None:
        out["name"] = str(name).strip()
        if not out["name"]:
            raise ValueError("A person needs a name.")
    if description is not None:
        out["description"] = str(description).strip() or None
    if works_for is not None:
        out["works_for"] = str(works_for).strip() or None
    return out


def add_person(name, description=None, works_for=None, group_id=None, person_id=None):
    """Add someone to the network; returns them."""
    fields = _person_fields(name, description, works_for)
    person_id = person_id or uuid.uuid4().hex
    with store.db() as conn:
        conn.execute(f"INSERT INTO net_people ({', '.join(PERSON_COLS)}) VALUES (?, ?, ?, ?, ?, ?)",
                     (person_id, fields["name"], fields.get("description"), fields.get("works_for"), group_id,
                      store.stamp()))
    return get_person(person_id)


KEEP_GROUP = NO_CHANGE


def update_person(person_id, name=None, description=None, works_for=None, group_id=KEEP_GROUP):
    """Change any of name, description, works_for (None = leave as is; "" = clear) and group (None = no group)."""
    fields = _person_fields(name, description, works_for)
    if group_id is not KEEP_GROUP:
        fields["group_id"] = group_id
    if fields:
        with store.db() as conn:
            conn.execute(f"UPDATE net_people SET {', '.join(f'{k} = ?' for k in fields)} WHERE id = ?",
                         (*fields.values(), person_id))


def delete_person(person_id):
    """Remove someone (and their connections)."""
    with store.db() as conn:
        conn.execute("DELETE FROM net_people WHERE id = ?", (person_id,))


def _pair(a, b):
    if a == b:
        raise ValueError("Someone can't be connected to themselves.")
    return (a, b) if a < b else (b, a)


def link_people(a, b, reason=None):
    """Connect two people (or update why they're connected)."""
    a, b = _pair(a, b)
    with store.db() as conn:
        conn.execute("INSERT INTO net_links VALUES (?, ?, ?) ON CONFLICT(a, b) DO UPDATE SET reason = excluded.reason",
                     (a, b, (str(reason).strip() or None) if reason else None))


def unlink_people(a, b):
    a, b = _pair(a, b)
    with store.db() as conn:
        conn.execute("DELETE FROM net_links WHERE a = ? AND b = ?", (a, b))


def net_links():
    """[{a, b, reason}] for every connection."""
    with store.db() as conn:
        rows = conn.execute("SELECT a, b, reason FROM net_links").fetchall()
    return [{"a": a, "b": b, "reason": r} for a, b, r in rows]


def add_interaction(person_id, note, day):
    """Log a time the user saw or spoke to someone; returns its id."""
    note = str(note).strip()
    if not note:
        raise ValueError("Say what happened.")
    iid = uuid.uuid4().hex
    with store.db() as conn:
        conn.execute("INSERT INTO net_interactions VALUES (?, ?, ?, ?, ?)",
                     (iid, person_id, store._as_date(day).isoformat(), note, store.stamp()))
    return iid


def interactions_of(person_id, limit=None):
    """[{id, date, note}] for one person, newest first."""
    with store.db() as conn:
        rows = conn.execute("SELECT id, date, note FROM net_interactions WHERE person_id = ? "
                            "ORDER BY date DESC, created_at DESC" + (f" LIMIT {int(limit)}" if limit else ""),
                            (person_id,)).fetchall()
    return [{"id": i, "date": d, "note": n} for i, d, n in rows]


def interactions_between(first, last):
    """[{date, note, person}] logged between two dates (inclusive), oldest first."""
    with store.db() as conn:
        rows = conn.execute(
            "SELECT i.date, i.note, p.name FROM net_interactions i JOIN net_people p ON p.id = i.person_id "
            "WHERE i.date BETWEEN ? AND ? ORDER BY i.date, i.created_at",
            (store._as_date(first).isoformat(), store._as_date(last).isoformat())).fetchall()
    return [{"date": d, "note": n, "person": p} for d, n, p in rows]

def last_interactions():
    """{person_id: date of the latest interaction}."""
    with store.db() as conn:
        return dict(conn.execute("SELECT person_id, MAX(date) FROM net_interactions GROUP BY person_id").fetchall())


def delete_interaction(interaction_id):
    with store.db() as conn:
        conn.execute("DELETE FROM net_interactions WHERE id = ?", (interaction_id,))


def connections_of(person_id):
    """[(other person, reason)] for one person, by name."""
    people = {p["id"]: p for p in net_people()}
    out = [(people[l["b"] if l["a"] == person_id else l["a"]], l["reason"])
           for l in net_links() if person_id in (l["a"], l["b"])]
    return sorted(out, key=lambda x: x[0]["name"].lower())


# ---------------------------------------------------------------------------
# Claude's tools
# ---------------------------------------------------------------------------

def _group_names():
    """"Family, Friends, Northfield (Physics Society, Robotics Lab), ..." - top-level groups with their sub-groups."""
    groups = net_groups()

    def named(gid):
        g = next(x for x in groups if x["id"] == gid)
        kids = [named(k["id"]) for k in groups if k["parent_id"] == g["id"]]
        return g["name"] + (f" ({', '.join(kids)})" if kids else "")
    ids = {g["id"] for g in groups}
    return ", ".join(named(g["id"]) for g in groups if g["parent_id"] not in ids) or "none"


def _group_id(name):
    if not name:
        return None
    gid = find_net_group(name)
    if gid is None:
        raise tools.ToolError(f"There's no group called '{name}'. Groups: {_group_names()}. "
                              "Use one of those, or add_group if the user wants a new one.")
    return gid


def describe_person(p):
    bits = [group_path(p["group_id"]) if p["group_id"] else None,
            f"works for {p['works_for']}" if p["works_for"] else None]
    bits = [b for b in bits if b]
    return p["name"] + (f" ({', '.join(bits)})" if bits else "")


def _find_person(person):
    """Someone by id, or by name (exact, then part of a name)."""
    found = get_person(str(person).strip())
    if found:
        return found
    matches = find_people(person)
    if len(matches) == 1:
        return matches[0]
    if matches:
        options = "; ".join(f"id {p['id']}: {describe_person(p)}" for p in matches)
        raise tools.ToolError(f"More than one person matches '{person}': {options}. Ask the user which one, or pass the id.")
    raise tools.ToolError(f"There's no one called '{person}' in the network. Add them with add_person first.")


def tool_add_person(name, description=None, works_for=None, group=None):
    name = str(name).strip()
    if not name:
        raise tools.ToolError("The person needs a name.")
    gid = _group_id(group)
    same = [p for p in find_people(name) if p["name"].lower() == name.lower()]
    if same:
        return tools.Result(f"There's already someone called {same[0]['name']}: {describe_person(same[0])} (id {same[0]['id']}). "
                            "If this is a different person, ask the user how to tell them apart (e.g. a surname); "
                            "otherwise use update_person.")
    p = add_person(name, description, works_for, gid)
    return tools.Result(f"Added {describe_person(p)} to the network (id {p['id']}).", changed=True)


def tool_update_person(person, name=None, description=None, works_for=None, group=None, clear_group=False):
    p = _find_person(person)
    gid = None if clear_group else _group_id(group) if group else KEEP_GROUP
    if name is None and description is None and works_for is None and gid is KEEP_GROUP:
        raise tools.ToolError("Say what to change: name, description, works_for or group.")
    update_person(p["id"], name, description, works_for, gid)
    return tools.Result(f"Updated {describe_person(get_person(p['id']))}.", changed=True)


def tool_connect_people(person, other, reason=None):
    a, b = _find_person(person), _find_person(other)
    if a["id"] == b["id"]:
        raise tools.ToolError("Someone can't be connected to themselves.")
    link_people(a["id"], b["id"], reason)
    why = f" ({reason})" if reason else ""
    return tools.Result(f"Connected {a['name']} and {b['name']}{why}.", changed=True)


def tool_disconnect_people(person, other, confirmed=False):
    a, b = _find_person(person), _find_person(other)
    if not any(o["id"] == b["id"] for o, _ in connections_of(a["id"])):
        return tools.Result(f"{a['name']} and {b['name']} aren't connected.")
    summary = f"Remove the connection between {a['name']} and {b['name']}"
    if not confirmed:
        return tools.Result("", pending=tools.Pending(summary, lambda: tool_disconnect_people(a["id"], b["id"], True)))
    unlink_people(a["id"], b["id"])
    return tools.Result(f"Done: {summary}.", changed=True)


def tool_delete_person(person, confirmed=False):
    p = _find_person(person)
    n = len(connections_of(p["id"]))
    summary = f"Remove {describe_person(p)} from the network" + (f", with their {n} connection{'s' * (n != 1)}" if n else "")
    if not confirmed:
        return tools.Result("", pending=tools.Pending(summary, lambda: tool_delete_person(p["id"], True)))
    delete_person(p["id"])
    return tools.Result(f"Done: {summary}.", changed=True)


def _colour(colour):
    if colour and not re.fullmatch(r"#[0-9A-Fa-f]{6}", colour.strip()):
        raise tools.ToolError("colour must be a hex code like #3E8EF7.")
    return colour.strip() if colour else None


def _find_group(name):
    """A group's id, by name or id."""
    if any(g["id"] == name for g in net_groups()):
        return name
    gid = find_net_group(name)
    if gid is None:
        raise tools.ToolError(f"There's no group called '{name}'. Groups: {_group_names()}.")
    return gid


def tool_add_group(name, inside=None, colour=None):
    """A new group, optionally inside another (a sub-group, e.g. 'Physics Society' inside 'Northfield')."""
    if find_net_group(name):
        return tools.Result(f"There's already a group called '{name}' ({group_path(find_net_group(name))}).")
    gid = add_net_group(name, _colour(colour), _find_group(inside) if inside else None)
    return tools.Result(f"Added the group {group_path(gid)}.", changed=True)


def tool_edit_group(group, name=None, inside=None, top_level=False, colour=None):
    """Rename, recolour or move a group (inside another group, or to the top level)."""
    gid = _find_group(group)
    parent = None if top_level else _find_group(inside) if inside else NO_CHANGE
    if name is None and colour is None and parent is NO_CHANGE:
        raise tools.ToolError("Say what to change: name, inside, top_level or colour.")
    try:
        update_net_group(gid, name, _colour(colour), parent)
    except ValueError as e:
        raise tools.ToolError(str(e))
    return tools.Result(f"Updated the group {group_path(gid)}.", changed=True)


def tool_delete_group(group, confirmed=False):
    gid = _find_group(group)
    path = group_path(gid)
    parent = path.rsplit(" › ", 1)[0] if " › " in path else None
    summary = f"Delete the group {path}; its people and sub-groups move to " + (parent or "the top level")
    if not confirmed:
        return tools.Result("", pending=tools.Pending(summary, lambda: tool_delete_group(gid, True)))
    delete_net_group(gid)
    return tools.Result(f"Done: {summary}.", changed=True)


def tool_find_people(query=None):
    """Everyone (or those whose name, description or employer mentions `query`), with their connections."""
    people = net_people()
    if query:
        q = str(query).strip().lower()
        people = [p for p in people if q in " ".join(filter(None, (p["name"], p["description"], p["works_for"]))).lower()]
    lines = [f"Groups: {_group_names()}."]
    for p in people:
        line = f"- id {p['id']}: {describe_person(p)}"
        if p["description"]:
            line += f": {p['description']}"
        links = connections_of(p["id"])
        if links:
            line += ". Knows " + "; ".join(o["name"] + (f" ({r})" if r else "") for o, r in links)
        last = interactions_of(p["id"], limit=1)
        if last:
            line += f". Last interaction {tools.nice_day(last[0]['date'])}: {last[0]['note']}"
        lines.append(line)
    if len(lines) == 1:
        lines.append("No one matches." if query else "The network is empty.")
    return tools.Result("\n".join(lines))


def tool_log_interaction(person, note, date=None):
    """Note a time the user saw or spoke to someone, e.g. "Coffee; talked about her thesis"."""
    p = _find_person(person)
    day = tools._day(date) if date else store.local_today().isoformat()
    try:
        add_interaction(p["id"], note, day)
    except ValueError as e:
        raise tools.ToolError(str(e))
    return tools.Result(f"Logged for {p['name']} on {tools.nice_day(day)}: {str(note).strip()}", changed=True)


def tool_person_history(person, limit=20):
    """The times the user logged seeing or speaking to someone, newest first."""
    p = _find_person(person)
    rows = interactions_of(p["id"], limit=int(limit))
    if not rows:
        return tools.Result(f"Nothing logged with {p['name']} yet.")
    return tools.Result(f"{p['name']}:\n" + "\n".join(f"- id {r['id']}, {tools.nice_day(r['date'])} ({r['date']}): {r['note']}"
                                                      for r in rows))


def tool_delete_interaction(person, interaction, confirmed=False):
    """Remove a logged meeting: `interaction` is its id (from person_history) or words from its note."""
    p = _find_person(person)
    rows = interactions_of(p["id"])
    want = str(interaction).strip()
    match = [r for r in rows if str(r["id"]) == want] or [r for r in rows if want.lower() in r["note"].lower()]
    if not match:
        raise tools.ToolError(f"Nothing logged with {p['name']} matches '{interaction}'. Use person_history to see them.")
    if len(match) > 1:
        options = "; ".join(f"id {r['id']}: {r['date']} {r['note']}" for r in match)
        raise tools.ToolError(f"More than one matches: {options}. Ask the user which one, or pass its id.")
    r = match[0]
    if not confirmed:
        return tools.Result("", pending=tools.Pending(f"Remove '{r['note']}' with {p['name']} on {tools.nice_day(r['date'])}",
                                                      lambda: tool_delete_interaction(p["id"], r["id"], True)))
    delete_interaction(r["id"])
    return tools.Result(f"Removed it from {p['name']}'s history.", changed=True)


PROMPT = """
- Network: the people the user knows, shown as a web on the Network page, coloured by group.
  Each person has a name, an optional description (who they are / how the user knows them),
  works_for (company, university, team) and a group (see find_people for the list).
  Groups can have sub-groups, e.g. "Northfield" containing "Physics Society" and "Robotics Lab"; in the
  web the user sits in the middle, each group branches off them, sub-groups branch off their group,
  and people branch off the group they're in. Put people in the most specific group that fits.
  - "add Physics Society and Robotics Lab under Northfield" -> add_group("Physics Society", inside="Northfield") etc.
    (add Northfield first if it doesn't exist). edit_group renames, recolours or moves a group;
    delete_group needs the user's confirmation.
  - "Sam works at Google, a friend from uni" -> add_person(name="Sam", works_for="Google",
    group="Friends", description="Friend from uni"). Pick the group that fits best; if none does, ask.
  - Connections between people are separate: connect_people(person, other, reason), e.g. "Sam knows
    Alex from football" -> connect_people("Sam", "Alex", reason="Football"). Add anyone new first.
    Everyone is already linked to the user in the web, so never connect someone to the user.
  - Use find_people to look someone up or check who exists before adding (avoid duplicates).
  - disconnect_people and delete_person need the user's confirmation.
  - Times the user sees or speaks to someone go in their interaction log: "had coffee with Priya,
    talked about her thesis" -> log_interaction(person="Priya", note="Coffee; talked about her thesis")
    (date defaults to today; "yesterday" etc. -> pass the date). person_history lists them (with ids);
    delete_interaction removes one (needs confirmation). If the person isn't in the network yet, ask
    whether to add them first.
"""

DATE = {"type": "string", "description": "YYYY-MM-DD"}


def _schema(required, **props):
    return {"type": "object", "properties": props, "required": list(required)}


TOOLS = [
    ("add_person", "Add someone to the user's network.",
     _schema(["name"], name={"type": "string"}, description={"type": "string", "description": "who they are / how the user knows them"},
             works_for={"type": "string", "description": "company, university or team"},
             group={"type": "string", "description": "a network group, e.g. 'Friends'"}),
     tool_add_person),
    ("update_person", "Change a person's name, description, works_for or group (by name or id).",
     _schema(["person"], person={"type": "string"}, name={"type": "string"}, description={"type": "string"},
             works_for={"type": "string"}, group={"type": "string"}, clear_group={"type": "boolean"}),
     tool_update_person),
    ("connect_people", "Record that two people in the network know each other, and why.",
     _schema(["person", "other"], person={"type": "string"}, other={"type": "string"},
             reason={"type": "string", "description": "how they know each other, e.g. 'Work together at Google'"}),
     tool_connect_people),
    ("disconnect_people", "Remove the connection between two people.",
     _schema(["person", "other"], person={"type": "string"}, other={"type": "string"}), tool_disconnect_people),
    ("delete_person", "Remove someone from the network (and their connections).",
     _schema(["person"], person={"type": "string"}), tool_delete_person),
    ("add_group", "Add a network group, optionally inside another group as a sub-group (e.g. 'Physics Society' inside 'Northfield').",
     _schema(["name"], name={"type": "string"}, inside={"type": "string", "description": "the parent group's name"},
             colour={"type": "string", "description": "hex, e.g. #3E8EF7 (sub-groups default to their parent's)"}),
     tool_add_group),
    ("edit_group", "Rename, recolour or move a network group (inside another group, or top_level=true).",
     _schema(["group"], group={"type": "string"}, name={"type": "string"}, inside={"type": "string"},
             top_level={"type": "boolean"}, colour={"type": "string"}),
     tool_edit_group),
    ("delete_group", "Delete a network group; its people and sub-groups move up a level.",
     _schema(["group"], group={"type": "string"}), tool_delete_group),
    ("log_interaction", "Note a time the user saw or spoke to someone in their network (date defaults to today).",
     _schema(["person", "note"], person={"type": "string"},
             note={"type": "string", "description": "what happened, e.g. 'Coffee; talked about her thesis'"},
             date=DATE),
     tool_log_interaction),
    ("person_history", "List the interactions logged with someone, newest first.",
     _schema(["person"], person={"type": "string"}), tool_person_history),
    ("delete_interaction", "Remove a logged meeting with someone (id from person_history, or words from its note).",
     _schema(["person", "interaction"], person={"type": "string"}, interaction={"type": "string"}),
     tool_delete_interaction),
    ("find_people", "List people in the network (with ids, groups and connections), optionally filtered by a search.",
     _schema([], query={"type": "string"}), tool_find_people),
]

# What the chat shows while one of these tools runs (word in the tool's name -> label).
STATUS = {"person_history": "Looking that up", "person": "Updating your network", "people": "Updating your network",
          "group": "Updating your network", "interaction": "Updating your network"}


# ---------------------------------------------------------------------------
# Home search, and the weekly review
# ---------------------------------------------------------------------------

# kind -> (SQL giving (id, title, detail, date, extra), haystack, order); "Met" puts the note first, as shown.
SEARCH = {
    "Person": ("SELECT id, name, description, NULL, works_for FROM net_people",
               "name || ' ' || COALESCE(description, '') || ' ' || COALESCE(works_for, '')", "name"),
    "Group": ("SELECT id, name, NULL, NULL, NULL FROM net_groups", "name", "name"),
    "Met": ("SELECT i.person_id, i.note, p.name, i.date, NULL FROM net_interactions i "
            "JOIN net_people p ON p.id = i.person_id", "i.note || ' ' || p.name", "date"),
}
SEARCH_ICONS = {"Person": "person", "Group": "group", "Met": "forum"}


def _search_open(r, ss):
    ss["page"] = "Network"
    ss["net_edit"] = {"kind": "group" if r["kind"] == "Group" else "person", "id": r["id"]}


def _review(first, last):
    """The people the user saw that week."""
    return {"title": "People you saw", "lines": [f"{p['person']} · {p['note']}" for p in interactions_between(first, last)]}


def _page():
    from venato.ui import network as ui
    ui.render_page()


BLOCK = Block("network", "Network", ":material/hub:",
              "A map of the people you know, the groups they're in, and when you last met.",
              group="People & life", page=_page, tools=TOOLS, prompt=PROMPT, schema=SCHEMA, migrate=_migrate,
              order=170, search=SEARCH, search_icons=SEARCH_ICONS, search_open=_search_open,
              review=_review, status=STATUS)
