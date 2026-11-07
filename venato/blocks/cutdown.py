"""
Cut down: track the things you want less of (caffeine, alcohol, smoking, screen time, or
anything you add) against a daily and weekly limit, or quit them altogether. Presets make
logging one tap ("Coffee" = 95 mg); streaks count days under the limit (or since the last
one); a cost per unit shows what it costs, or what quitting has saved.

Most trackers add up ("had a coffee"); screen time is a day's total ("screen time 4h").
The preset amounts are typical values (UK alcohol units, caffeine per drink) and can be changed.
"""

import re
import uuid
from datetime import timedelta

from venato import store
from venato.blocks import Block

STARTER = [   # name, unit, mode, daily, weekly, goal, presets
    ("Caffeine", "mg", "add", 400, None, "reduce",
     [("Coffee", 95), ("Espresso", 63), ("Tea", 47), ("Energy drink", 80), ("Cola", 34)]),
    ("Alcohol", "units", "add", None, 14, "reduce",
     [("Pint", 2.3), ("Glass of wine", 2.1), ("Single", 1), ("Can of beer", 1.8), ("Bottle of wine", 9)]),
    ("Smoking", "cigarettes", "add", 0, None, "quit", [("Cigarette", 1), ("Vape", 1)]),
    ("Screen time", "hours", "total", 3, None, "reduce", []),
]

SCHEMA = """
CREATE TABLE IF NOT EXISTS cd_trackers (
    id           TEXT PRIMARY KEY,
    name         TEXT NOT NULL UNIQUE COLLATE NOCASE,
    unit         TEXT NOT NULL,
    mode         TEXT NOT NULL DEFAULT 'add',    -- add: amounts add up; total: one total per day
    daily_limit  REAL,
    weekly_limit REAL,
    goal         TEXT NOT NULL DEFAULT 'reduce', -- reduce / quit
    quit_since   TEXT,                           -- YYYY-MM-DD
    cost         REAL,                           -- money per unit
    baseline     REAL,                           -- units a day before cutting down (for "saved")
    ord          INTEGER NOT NULL DEFAULT 0,
    created_at   TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS cd_presets (
    id         TEXT PRIMARY KEY,
    tracker_id TEXT NOT NULL REFERENCES cd_trackers(id) ON DELETE CASCADE,
    name       TEXT NOT NULL,
    amount     REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS cd_log (
    id         TEXT PRIMARY KEY,
    tracker_id TEXT NOT NULL REFERENCES cd_trackers(id) ON DELETE CASCADE,
    date       TEXT NOT NULL,
    time       TEXT,
    amount     REAL NOT NULL,
    what       TEXT,
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS cd_log_date ON cd_log(tracker_id, date);
"""

WORDS = {"a": 1, "an": 1, "one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "seven": 7,
         "eight": 8, "nine": 9, "ten": 10, "another": 1}


class CutError(ValueError):
    pass


def _id():
    return uuid.uuid4().hex


# --- Trackers and presets ---

T_COLS = ("id", "name", "unit", "mode", "daily_limit", "weekly_limit", "goal", "quit_since", "cost", "baseline", "ord")


def _seed(conn):
    if conn.execute("SELECT COUNT(*) FROM cd_trackers").fetchone()[0]:
        return
    for i, (name, unit, mode, daily, weekly, goal, presets) in enumerate(STARTER):
        tid = _id()
        conn.execute(f"INSERT INTO cd_trackers ({', '.join(T_COLS)}, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, NULL, NULL, NULL, ?, ?)",
                     (tid, name, unit, mode, daily, weekly, goal, i, store.stamp()))
        conn.executemany("INSERT INTO cd_presets VALUES (?, ?, ?, ?)", [(_id(), tid, n, a) for n, a in presets])


def trackers():
    with store.db() as conn:
        _seed(conn)
        rows = conn.execute(f"SELECT {', '.join(T_COLS)} FROM cd_trackers ORDER BY ord, name").fetchall()
    return [dict(zip(T_COLS, r)) for r in rows]


def find(name):
    want = str(name or "").strip().lower()
    pool = trackers()
    return next((t for t in pool if t["name"].lower() == want or t["id"] == name), None) or \
        next((t for t in pool if want and (t["name"].lower().startswith(want) or want in t["unit"].lower())), None)


def presets(tid):
    with store.db() as conn:
        rows = conn.execute("SELECT id, name, amount FROM cd_presets WHERE tracker_id = ? ORDER BY rowid", (tid,)).fetchall()
    return [dict(zip(("id", "name", "amount"), r)) for r in rows]


def find_preset(name):
    """(tracker, preset) for a preset name anywhere ('pints' -> Alcohol, Pint), or (None, None)."""
    want = str(name or "").strip().lower()
    for t in trackers():
        for p in presets(t["id"]):
            n = p["name"].lower()
            if want in (n, n + "s", n + "es") or (want.endswith("s") and want[:-1] == n):
                return t, p
    return None, None


def add_tracker(name, unit, daily_limit=None, weekly_limit=None, goal="reduce", mode="add", cost=None):
    name, unit = str(name or "").strip(), str(unit or "").strip()
    if not name or not unit:
        raise CutError("Give the tracker a name and a unit (e.g. 'Sugar', 'g').")
    if goal not in ("reduce", "quit") or mode not in ("add", "total"):
        raise CutError("goal is reduce or quit; mode is add or total.")
    if find(name) and find(name)["name"].lower() == name.lower():
        raise CutError(f"There's already a tracker called {name}.")
    tid = _id()
    with store.db() as conn:
        conn.execute(f"INSERT INTO cd_trackers ({', '.join(T_COLS)}, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, NULL, ?, NULL, ?, ?)",
                     (tid, name, unit, mode, daily_limit, weekly_limit, goal, cost, len(trackers()), store.stamp()))
    return tid


def update_tracker(tid, **fields):
    allowed = {k: v for k, v in fields.items() if k in T_COLS[1:]}
    if "goal" in allowed and allowed["goal"] not in ("reduce", "quit"):
        raise CutError("goal is reduce or quit.")
    if allowed.get("goal") == "quit" and "quit_since" not in allowed:
        allowed["quit_since"] = store.local_today().isoformat()
    for k in ("daily_limit", "weekly_limit", "cost", "baseline"):
        if k in allowed and allowed[k] not in (None, "") and float(allowed[k]) < 0:
            raise CutError(f"{k.replace('_', ' ')} can't be negative.")
    if allowed:
        with store.db() as conn:
            conn.execute(f"UPDATE cd_trackers SET {', '.join(f'{k} = ?' for k in allowed)} WHERE id = ?",
                         (*allowed.values(), tid))


def delete_tracker(tid):
    with store.db() as conn:
        conn.execute("DELETE FROM cd_log WHERE tracker_id = ?", (tid,))
        conn.execute("DELETE FROM cd_presets WHERE tracker_id = ?", (tid,))
        conn.execute("DELETE FROM cd_trackers WHERE id = ?", (tid,))


def save_preset(tid, name, amount):
    name = str(name or "").strip()
    if not name or float(amount) <= 0:
        raise CutError("A preset needs a name and an amount above 0.")
    with store.db() as conn:
        conn.execute("INSERT INTO cd_presets VALUES (?, ?, ?, ?)", (_id(), tid, name, float(amount)))


def delete_preset(pid):
    with store.db() as conn:
        conn.execute("DELETE FROM cd_presets WHERE id = ?", (pid,))


# --- Logging ---

L_COLS = ("id", "tracker_id", "date", "time", "amount", "what")


def log(tid, amount, day=None, what=None, at=None):
    """Add an amount (mode 'add'), or set the day's total (mode 'total')."""
    t = next((x for x in trackers() if x["id"] == tid), None)
    if not t:
        raise CutError("No such tracker.")
    amount = float(amount)
    if not 0 <= amount <= 100000:
        raise CutError("That amount looks wrong.")
    day = store._as_date(day) if day else store.local_today()
    at = at or (store.local_now().strftime("%H:%M") if day == store.local_today() else None)
    with store.db() as conn:
        if t["mode"] == "total":
            conn.execute("DELETE FROM cd_log WHERE tracker_id = ? AND date = ?", (tid, day.isoformat()))
        conn.execute(f"INSERT INTO cd_log ({', '.join(L_COLS)}, created_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
                     (_id(), tid, day.isoformat(), at, amount, what, store.stamp()))
    return day_total(tid, day)


def entries(tid, day):
    with store.db() as conn:
        rows = conn.execute(f"SELECT {', '.join(L_COLS)} FROM cd_log WHERE tracker_id = ? AND date = ? ORDER BY time, created_at",
                            (tid, str(day))).fetchall()
    return [dict(zip(L_COLS, r)) for r in rows]


def delete_entry(eid):
    with store.db() as conn:
        conn.execute("DELETE FROM cd_log WHERE id = ?", (eid,))


def daily(tid, first, last):
    with store.db() as conn:
        rows = conn.execute("SELECT date, SUM(amount) FROM cd_log WHERE tracker_id = ? AND date BETWEEN ? AND ? "
                            "GROUP BY date", (tid, str(first), str(last))).fetchall()
    return dict(rows)


def day_total(tid, day):
    return daily(tid, day, day).get(str(day), 0.0)


def first_logged(tid):
    with store.db() as conn:
        row = conn.execute("SELECT MIN(date), MIN(substr(created_at, 1, 10)) FROM cd_log WHERE tracker_id = ?", (tid,)).fetchone()
    return row[0]


# --- Progress ---

def status(t, today=None):
    """Today, this week, the limits, the streak and money for one tracker."""
    today = today or store.local_today()
    week0 = store.week_start_of(today)
    days = daily(t["id"], today - timedelta(days=400), today)
    week = sum(v for d, v in days.items() if d >= week0.isoformat())
    out = {"today": days.get(today.isoformat(), 0.0), "week": week}
    if t["goal"] == "quit":
        # Days free: since the quit date, or since the day after the last one if that's later.
        since = store._as_date(t["quit_since"] or first_logged(t["id"]) or today)
        last = max((d for d, v in days.items() if v > 0), default=None)
        start = since if not last or store._as_date(last) < since else store._as_date(last) + timedelta(days=1)
        out["days_free"] = max(0, (today - start).days)
        if t["baseline"] and t["cost"]:
            had = sum(v for d, v in days.items() if d >= since.isoformat())
            out["saved"] = max(0.0, (t["baseline"] * (today - since).days - had) * t["cost"])
    else:
        # Days in a row (back from today) at or under the daily limit, since tracking began.
        limit, started, n = t["daily_limit"], first_logged(t["id"]), 0
        if limit is not None and started:
            d = today
            while d.isoformat() >= started and days.get(d.isoformat(), 0.0) <= limit:
                n += 1
                d -= timedelta(days=1)
        out["streak"] = n
    if t["cost"]:
        month0 = today.replace(day=1).isoformat()
        out["spent_month"] = sum(v for dd, v in days.items() if dd >= month0) * t["cost"]
    out["over_today"] = t["daily_limit"] is not None and out["today"] > t["daily_limit"]
    out["over_week"] = t["weekly_limit"] is not None and week > t["weekly_limit"]
    return out


def describe(t, today=None):
    s = status(t, today)
    parts = [f"{t['name']}: {s['today']:g} {t['unit']} today"]
    if t["daily_limit"] is not None:
        parts.append(f"limit {t['daily_limit']:g}/day")
    if t["weekly_limit"] is not None:
        parts.append(f"{s['week']:g}/{t['weekly_limit']:g} this week")
    if "days_free" in s:
        parts.append(f"{s['days_free']} days free")
    elif s.get("streak"):
        parts.append(f"{s['streak']} days under the limit")
    return ", ".join(parts)


# --- The assistant ---

def tool_log(tracker=None, amount=None, preset=None, count=1, date=None):
    from venato import tools
    t = find(tracker) if tracker else None
    p = None
    if preset:
        t2, p = find_preset(preset)
        t = t or t2
        if p and t2 and t and t2["id"] != t["id"]:
            p = next((x for x in presets(t["id"]) if x["name"].lower() == str(preset).lower()), None)
    if not t:
        names = ", ".join(x["name"] for x in trackers())
        raise tools.ToolError(f"Which tracker? There's: {names}.")
    if amount is None and not p:
        raise tools.ToolError("Give an amount (in " + t["unit"] + ") or a preset: "
                              + (", ".join(x["name"] for x in presets(t["id"])) or "none yet") + ".")
    total = float(amount) if amount is not None else p["amount"] * float(count or 1)
    try:
        log(t["id"], total, date, f"{count:g} × {p['name']}" if p and amount is None else None)
    except CutError as e:
        raise tools.ToolError(str(e))
    return tools.Result(f"Logged {total:g} {t['unit']} of {t['name'].lower()}. {describe(t)}.", changed=True)


def tool_status(tracker=None):
    from venato import tools
    pool = [find(tracker)] if tracker else trackers()
    pool = [t for t in pool if t]
    if not pool:
        raise tools.ToolError(f"No tracker called '{tracker}'.")
    return tools.Result("\n".join(f"- {describe(t)}" for t in pool))


def tool_limit(tracker, daily_limit=None, weekly_limit=None, goal=None, cost=None):
    from venato import tools
    t = find(tracker)
    if not t:
        raise tools.ToolError(f"No tracker called '{tracker}'.")
    fields = {k: v for k, v in (("daily_limit", daily_limit), ("weekly_limit", weekly_limit), ("goal", goal),
                                ("cost", cost)) if v is not None}
    try:
        update_tracker(t["id"], **fields)
    except CutError as e:
        raise tools.ToolError(str(e))
    return tools.Result(f"Updated {t['name']}: {describe(find(t['id']))}.", changed=True)


def tool_add(name, unit, daily_limit=None, weekly_limit=None, goal="reduce", total_per_day=False, cost=None):
    from venato import tools
    try:
        add_tracker(name, unit, daily_limit, weekly_limit, goal, "total" if total_per_day else "add", cost)
    except CutError as e:
        raise tools.ToolError(str(e))
    return tools.Result(f"Added the tracker {name} ({unit}).", changed=True)


COUNT = r"(\d+(?:\.\d+)?|a|an|one|two|three|four|five|six|seven|eight|nine|ten|another)"
QUICK_VERB = re.compile(rf"(?:i\s+)?(?:just\s+)?(?:had|drank|drunk|smoked|vaped)\s+(?:{COUNT}\s+)?(.+?)"
                        r"(?:\s+(?:today|tonight|this morning|earlier))?")
QUICK_COUNT = re.compile(rf"{COUNT}\s+(.+?)")
QUICK_TOTAL = re.compile(r"(.+?)\s+(?:was\s+|is\s+|=\s*|:\s*)?(\d+(?:\.\d+)?)\s*(?:h|hr|hrs|hours?)?(?:\s+today)?")


def _count(word):
    if word is None:
        return 1.0
    return float(word) if word[0].isdigit() else float(WORDS[word])


def _quick(text, day):
    """'had a coffee', 'drank 2 pints', '3 espressos', 'smoked 3', 'screen time 4h'."""
    from venato import tools
    m = re.fullmatch(r"(?:i\s+)?smoked\s+(\d+)(?:\s+cigarettes?)?", text)
    t = find("smoking") if m else None
    if t:
        log(t["id"], float(m.group(1)), day)
        return tools.Result(f"{describe(t)}.", changed=True)
    m = QUICK_TOTAL.fullmatch(text)
    if m:
        t = next((x for x in trackers() if x["mode"] == "total" and x["name"].lower() == m.group(1).strip()), None)
        if t:
            log(t["id"], float(m.group(2)), day)
            return tools.Result(f"{describe(t)}.", changed=True)
    for pattern in (QUICK_VERB, QUICK_COUNT):
        m = pattern.fullmatch(text)
        if m:
            t, p = find_preset(m.group(2))
            if p:
                n = _count(m.group(1))
                log(t["id"], p["amount"] * n, day, f"{n:g} × {p['name']}")
                return tools.Result(f"{n:g} × {p['name']}. {describe(t)}.", changed=True)
    return None


def _context():
    return "; ".join(describe(t) for t in trackers()) or "No trackers."


PROMPT = """- Cut down: trackers for things the user wants less of (caffeine, alcohol, smoking, screen time, or their own)
  with daily / weekly limits or a quit goal (the Cut down page). "had two pints" -> log_cutdown(preset="Pint",
  count=2); "had 200 mg of caffeine" -> log_cutdown(tracker="Caffeine", amount=200); screen time is a day's
  total: "screen time was 5 hours" -> log_cutdown(tracker="Screen time", amount=5). cutdown_status shows today,
  the week and streaks; set_cutdown_limit changes a limit or goal ("I want to quit smoking" -> goal="quit");
  add_cutdown_tracker adds a new one."""

TOOLS = [
    ("log_cutdown", "Log an amount on a cut-down tracker, by amount (in its unit) or by preset × count.",
     {"type": "object", "properties": {"tracker": {"type": "string"}, "amount": {"type": "number"},
                                       "preset": {"type": "string"}, "count": {"type": "number"},
                                       "date": {"type": "string"}}, "required": []}, tool_log),
    ("cutdown_status", "Today, this week, limits and streaks for one tracker or all of them.",
     {"type": "object", "properties": {"tracker": {"type": "string"}}, "required": []}, tool_status),
    ("set_cutdown_limit", "Change a tracker's daily / weekly limit, goal (reduce / quit) or cost per unit.",
     {"type": "object", "properties": {"tracker": {"type": "string"}, "daily_limit": {"type": "number"},
                                       "weekly_limit": {"type": "number"},
                                       "goal": {"type": "string", "enum": ["reduce", "quit"]},
                                       "cost": {"type": "number"}}, "required": ["tracker"]}, tool_limit),
    ("add_cutdown_tracker", "Add a tracker for something else to cut down on (name, unit, limits, goal).",
     {"type": "object", "properties": {"name": {"type": "string"}, "unit": {"type": "string"},
                                       "daily_limit": {"type": "number"}, "weekly_limit": {"type": "number"},
                                       "goal": {"type": "string", "enum": ["reduce", "quit"]},
                                       "total_per_day": {"type": "boolean", "description": "one total per day, like screen time"},
                                       "cost": {"type": "number"}}, "required": ["name", "unit"]}, tool_add),
]


def _page():
    from venato.ui import cutdown as ui
    ui.render_page()


def _home():
    from venato.ui import cutdown as ui
    ui.render_home()


BLOCK = Block("cutdown", "Cut down", ":material/smoke_free:",
              "Track caffeine, alcohol, smoking, screen time (or anything) against limits, or quit, with streaks.",
              group="Health & body", page=_page, home=_home, tools=TOOLS, prompt=PROMPT, context=_context,
              quick=[_quick], schema=SCHEMA, order=33)
