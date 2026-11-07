"""
Food: a diary of what you eat, meal by meal, with calories and macros against your daily
targets; your own library of foods (filled as you log); and a meal planner for the week.
Planned meals can be recipes from the Recipes block and are logged to the diary in one go.

Nutrition is stored per diary entry as totals (so editing a food later doesn't change past
days). Numbers are whatever you (or the assistant's estimate) put in: Venato has no food
database of its own and never looks anything up online.
"""

import re
import uuid
from datetime import timedelta

from venato import store
from venato.blocks import Block

MEALS = ("breakfast", "lunch", "dinner", "snacks")
NUTRIENTS = ("kcal", "protein", "carbs", "fat", "fibre")
DEFAULT_TARGETS = {"kcal": 2200, "protein": 120, "carbs": 250, "fat": 75, "fibre": 30}

SCHEMA = """
CREATE TABLE IF NOT EXISTS food_items (
    id         TEXT PRIMARY KEY,
    name       TEXT NOT NULL UNIQUE COLLATE NOCASE,
    serving    TEXT,                        -- e.g. "1 slice (30 g)"
    kcal REAL, protein REAL, carbs REAL, fat REAL, fibre REAL,   -- per serving
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS food_log (
    id         TEXT PRIMARY KEY,
    date       TEXT NOT NULL,
    meal       TEXT NOT NULL,
    name       TEXT NOT NULL,
    servings   REAL NOT NULL DEFAULT 1,
    kcal REAL, protein REAL, carbs REAL, fat REAL, fibre REAL,   -- totals for this entry
    food_id    TEXT,
    recipe_id  TEXT,
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS meal_plan (
    id         TEXT PRIMARY KEY,
    date       TEXT NOT NULL,
    meal       TEXT NOT NULL,
    name       TEXT NOT NULL,
    recipe_id  TEXT,
    servings   REAL NOT NULL DEFAULT 1,
    notes      TEXT,
    logged     INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS food_log_date ON food_log(date);
CREATE INDEX IF NOT EXISTS meal_plan_date ON meal_plan(date);
"""


class FoodError(ValueError):
    pass


def _id():
    return uuid.uuid4().hex


def _meal(meal):
    meal = str(meal or "").strip().lower()
    meal = {"snack": "snacks", "breakfast": "breakfast", "brunch": "breakfast", "tea": "dinner",
            "supper": "dinner"}.get(meal, meal)
    if meal not in MEALS:
        raise FoodError(f"meal must be one of {', '.join(MEALS)}.")
    return meal


def meal_now(now=None):
    """The meal for this time of day."""
    h = (now or store.local_now()).hour
    return "breakfast" if 4 <= h < 11 else "lunch" if h < 15 else "dinner" if 17 <= h < 22 else "snacks"


def _num(v, name, hi):
    if v in (None, ""):
        return None
    v = float(v)
    if not 0 <= v <= hi:
        raise FoodError(f"{name} looks wrong ({v:g}).")
    return v


LIMITS = {"kcal": 10000, "protein": 1000, "carbs": 2000, "fat": 1000, "fibre": 300}


# --- Targets ---

def targets():
    saved = store.load_settings().get("food_targets") or {}
    return {k: saved.get(k, v) for k, v in DEFAULT_TARGETS.items()}


def save_targets(**t):
    store.save_settings(food_targets={**targets(), **{k: (None if v in (None, "", 0) else float(v))
                                                       for k, v in t.items() if k in NUTRIENTS}})


# --- The library ---

ITEM_COLS = ("id", "name", "serving") + NUTRIENTS


def items():
    with store.db() as conn:
        rows = conn.execute(f"SELECT {', '.join(ITEM_COLS)} FROM food_items ORDER BY name COLLATE NOCASE").fetchall()
    return [dict(zip(ITEM_COLS, r)) for r in rows]


def find_item(name):
    want = str(name or "").strip().lower()
    if not want:
        return None
    pool = items()
    for cand in (want, want.rstrip("s"), want + "s"):
        hit = [i for i in pool if i["name"].lower() == cand]
        if hit:
            return hit[0]
    return None


def save_item(name, serving=None, **nutrition):
    """Add a food to the library (or update it, by name). Nutrition is per serving."""
    name = str(name or "").strip()
    if not name:
        raise FoodError("The food needs a name.")
    vals = {k: _num(nutrition.get(k), k, LIMITS[k]) for k in NUTRIENTS}
    old = find_item(name)
    with store.db() as conn:
        if old:
            conn.execute(f"UPDATE food_items SET serving = COALESCE(?, serving), "
                         f"{', '.join(f'{k} = COALESCE(?, {k})' for k in NUTRIENTS)} WHERE id = ?",
                         (serving, *vals.values(), old["id"]))
            return old["id"]
        fid = _id()
        conn.execute(f"INSERT INTO food_items ({', '.join(ITEM_COLS)}, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                     (fid, name, serving, *vals.values(), store.stamp()))
        return fid


def delete_item(fid):
    with store.db() as conn:
        conn.execute("DELETE FROM food_items WHERE id = ?", (fid,))


# --- The diary ---

LOG_COLS = ("id", "date", "meal", "name", "servings") + NUTRIENTS + ("food_id", "recipe_id")


def log(name, meal=None, servings=1, date=None, remember=True, food_id=None, recipe_id=None, **nutrition):
    """Log something eaten. Nutrition given is for the whole entry; without it, a library food's
    per-serving values × servings are used. remember=True puts new foods (with numbers) in the library."""
    name = str(name or "").strip()
    if not name:
        raise FoodError("Say what you ate.")
    servings = _num(servings if servings not in (None, "") else 1, "servings", 100) or 1
    meal = _meal(meal) if meal else meal_now()
    day = store._as_date(date) if date else store.local_today()
    vals = {k: _num(nutrition.get(k), k, LIMITS[k] * 5) for k in NUTRIENTS}
    item = find_item(name) if not food_id else next((i for i in items() if i["id"] == food_id), None)
    if item and all(v is None for v in vals.values()):
        vals = {k: None if item[k] is None else round(item[k] * servings, 1) for k in NUTRIENTS}
        food_id = item["id"]
    elif remember and not item and not recipe_id and any(v is not None for v in vals.values()):
        food_id = save_item(name, None, **{k: None if v is None else v / servings for k, v in vals.items()})
    eid = _id()
    with store.db() as conn:
        conn.execute(f"INSERT INTO food_log ({', '.join(LOG_COLS)}, created_at) VALUES ({', '.join('?' * (len(LOG_COLS) + 1))})",
                     (eid, day.isoformat(), meal, name, servings, *vals.values(), food_id, recipe_id, store.stamp()))
    return get_entry(eid)


def get_entry(eid):
    with store.db() as conn:
        row = conn.execute(f"SELECT {', '.join(LOG_COLS)} FROM food_log WHERE id = ?", (eid,)).fetchone()
    return dict(zip(LOG_COLS, row)) if row else None


def entries(day):
    with store.db() as conn:
        rows = conn.execute(f"SELECT {', '.join(LOG_COLS)} FROM food_log WHERE date = ? ORDER BY created_at",
                            (str(day),)).fetchall()
    return [dict(zip(LOG_COLS, r)) for r in rows]


def update_entry(eid, **fields):
    e = get_entry(eid)
    if not e:
        return
    f = {k: v for k, v in fields.items() if k in ("name", "meal", "servings") + NUTRIENTS}
    if "meal" in f:
        f["meal"] = _meal(f["meal"])
    if "servings" in f and not any(k in f for k in NUTRIENTS) and e["servings"]:
        ratio = float(f["servings"]) / e["servings"]          # more servings: scale the numbers too
        f.update({k: None if e[k] is None else round(e[k] * ratio, 1) for k in NUTRIENTS})
    if f:
        with store.db() as conn:
            conn.execute(f"UPDATE food_log SET {', '.join(f'{k} = ?' for k in f)} WHERE id = ?", (*f.values(), eid))


def delete_entry(eid):
    with store.db() as conn:
        conn.execute("DELETE FROM food_log WHERE id = ?", (eid,))


def totals(day):
    out = {k: 0.0 for k in NUTRIENTS}
    for e in entries(day):
        for k in NUTRIENTS:
            out[k] += e[k] or 0
    return out


def daily_totals(first, last):
    """{date: {kcal, protein, ...}} for days with entries."""
    with store.db() as conn:
        rows = conn.execute(f"SELECT date, {', '.join(f'SUM(COALESCE({k}, 0))' for k in NUTRIENTS)} FROM food_log "
                            "WHERE date BETWEEN ? AND ? GROUP BY date ORDER BY date", (str(first), str(last))).fetchall()
    return {r[0]: dict(zip(NUTRIENTS, r[1:])) for r in rows}


def copy_meal(from_day, to_day, meal):
    """Copy one meal's entries from a day to another (e.g. yesterday's breakfast)."""
    n = 0
    for e in entries(from_day):
        if e["meal"] == meal:
            log(e["name"], meal, e["servings"], to_day, remember=False, food_id=e["food_id"], recipe_id=e["recipe_id"],
                **{k: e[k] for k in NUTRIENTS})
            n += 1
    return n


def recent_names(limit=30):
    with store.db() as conn:
        rows = conn.execute("SELECT name FROM food_log GROUP BY name COLLATE NOCASE ORDER BY MAX(created_at) DESC LIMIT ?",
                            (limit,)).fetchall()
    return [r[0] for r in rows]


# --- The meal plan ---

PLAN_COLS = ("id", "date", "meal", "name", "recipe_id", "servings", "notes", "logged")


def plan(name, date, meal, servings=1, recipe_id=None, notes=None):
    name = str(name or "").strip()
    if not name:
        raise FoodError("Say what the meal is.")
    pid = _id()
    with store.db() as conn:
        conn.execute(f"INSERT INTO meal_plan ({', '.join(PLAN_COLS)}, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, 0, ?)",
                     (pid, store._as_date(date).isoformat(), _meal(meal), name, recipe_id,
                      _num(servings, "servings", 100) or 1, notes, store.stamp()))
    return pid


def planned(first, last):
    with store.db() as conn:
        rows = conn.execute(f"SELECT {', '.join(PLAN_COLS)} FROM meal_plan WHERE date BETWEEN ? AND ? "
                            "ORDER BY date, CASE meal WHEN 'breakfast' THEN 0 WHEN 'lunch' THEN 1 WHEN 'dinner' THEN 2 ELSE 3 END",
                            (str(first), str(last))).fetchall()
    return [dict(zip(PLAN_COLS, r)) for r in rows]


def unplan(pid):
    with store.db() as conn:
        conn.execute("DELETE FROM meal_plan WHERE id = ?", (pid,))


def log_planned(pid):
    """Put a planned meal in the diary (a recipe brings its per-serving nutrition × servings)."""
    with store.db() as conn:
        row = conn.execute(f"SELECT {', '.join(PLAN_COLS)} FROM meal_plan WHERE id = ?", (pid,)).fetchone()
    if not row:
        raise FoodError("That planned meal has gone.")
    p = dict(zip(PLAN_COLS, row))
    nutrition = {}
    if p["recipe_id"]:
        from venato.blocks import recipes
        r = recipes.get(p["recipe_id"])
        if r:
            nutrition = {k: None if r[k] is None else round(r[k] * p["servings"], 1) for k in recipes.PER_SERVING}
    entry = log(p["name"], p["meal"], p["servings"], p["date"], remember=not p["recipe_id"],
                recipe_id=p["recipe_id"], **nutrition)
    with store.db() as conn:
        conn.execute("UPDATE meal_plan SET logged = 1 WHERE id = ?", (pid,))
    return entry


# --- The assistant ---

def _fmt(t):
    return (f"{t['kcal'] or 0:.0f} kcal, {t['protein'] or 0:.0f} g protein, {t['carbs'] or 0:.0f} g carbs, "
            f"{t['fat'] or 0:.0f} g fat")


def tool_log(name, meal=None, servings=1, date=None, kcal=None, protein=None, carbs=None, fat=None, fibre=None,
             estimated=False):
    from venato import tools
    try:
        e = log(name, meal, servings, date, kcal=kcal, protein=protein, carbs=carbs, fat=fat, fibre=fibre)
    except FoodError as err:
        raise tools.ToolError(str(err))
    t = totals(e["date"])
    note = " (estimated)" if estimated else ""
    return tools.Result(f"Logged {e['name']} for {e['meal']}: {_fmt(e)}{note}. Day so far: {_fmt(t)}.", changed=True)


def tool_day(date=None):
    from venato import tools
    day = store._as_date(date) if date else store.local_today()
    rows = entries(day)
    if not rows:
        return tools.Result(f"Nothing logged for {day.isoformat()}.")
    lines = [f"- {e['meal']}: {e['name']} ×{e['servings']:g} ({e['kcal'] or 0:.0f} kcal)" for e in rows]
    tg = targets()
    return tools.Result(f"{day.isoformat()}: {_fmt(totals(day))} (target {tg['kcal'] or '-'} kcal, "
                        f"{tg['protein'] or '-'} g protein).\n" + "\n".join(lines))


def tool_plan(name, date, meal, servings=1, recipe=None):
    from venato import tools
    rid = None
    if recipe:
        from venato.blocks import recipes
        r = recipes.find(recipe)
        if not r:
            raise tools.ToolError(f"No recipe called '{recipe}'.")
        rid, name = r["id"], name or r["name"]
    try:
        plan(name or recipe, date, meal, servings, rid)
    except FoodError as err:
        raise tools.ToolError(str(err))
    return tools.Result(f"Planned {name or recipe} for {meal} on {date}.", changed=True)


def tool_week(date=None):
    from venato import tools
    day = store._as_date(date) if date else store.local_today()
    first = store.week_start_of(day)
    rows = planned(first, first + timedelta(days=6))
    if not rows:
        return tools.Result("Nothing planned this week.")
    return tools.Result("\n".join(f"- {p['date']} {p['meal']}: {p['name']} ×{p['servings']:g}"
                                  + (" [logged]" if p["logged"] else "") for p in rows))


QUICK = re.compile(r"(?:i\s+)?(?:ate|had|eaten|eating)\s+(?:an?\s+|(\d+(?:\.\d+)?)\s+|some\s+)?(.+?)"
                   r"(?:\s+for\s+(breakfast|lunch|dinner|snacks?|tea|supper))?")


def _quick(text, day):
    """'ate a banana', 'had 2 eggs for breakfast': only foods already in your library."""
    m = QUICK.fullmatch(text)
    if not m:
        return None
    item = find_item(m.group(2))
    if not item or item["kcal"] is None:
        return None                              # unknown food: Claude can estimate it
    return tool_log(item["name"], m.group(3), float(m.group(1) or 1), day.isoformat())


def _context():
    today = store.local_today()
    t, tg = totals(today), targets()
    plans = planned(today, today)
    text = f"Eaten today: {_fmt(t)} (targets {tg['kcal'] or '-'} kcal, {tg['protein'] or '-'} g protein)."
    if plans:
        text += " Planned today: " + "; ".join(f"{p['meal']} {p['name']}" for p in plans) + "."
    return text


PROMPT = """- Food: a diary of meals with calories and macros (the Food page), and a weekly meal plan.
  "had a chicken caesar salad for lunch" -> log_food(name="Chicken caesar salad", meal="lunch", kcal, protein,
  carbs, fat): if the user didn't give numbers and it isn't in their foods, estimate typical values for a normal
  portion, pass estimated=true and say they're estimates. meal is breakfast / lunch / dinner / snacks (default:
  the time of day). food_day(date) shows a day's total vs targets. plan_meal(name, date, meal, servings,
  recipe=...) plans a meal; meal_plan_week shows the week."""

TOOLS = [
    ("log_food", "Log something eaten: name, meal, servings, and nutrition for the whole entry (kcal, protein, "
                 "carbs, fat, fibre in g). Leave nutrition out for foods already in the user's library.",
     {"type": "object", "properties": {
         "name": {"type": "string"}, "meal": {"type": "string", "enum": list(MEALS)},
         "servings": {"type": "number"}, "date": {"type": "string"},
         **{k: {"type": "number"} for k in NUTRIENTS}, "estimated": {"type": "boolean"}},
      "required": ["name"]}, tool_log),
    ("food_day", "What was eaten on a day (default today), with totals vs targets.",
     {"type": "object", "properties": {"date": {"type": "string"}}, "required": []}, tool_day),
    ("plan_meal", "Plan a meal on a date (optionally one of the user's recipes).",
     {"type": "object", "properties": {"name": {"type": "string"}, "date": {"type": "string"},
                                       "meal": {"type": "string", "enum": list(MEALS)},
                                       "servings": {"type": "number"}, "recipe": {"type": "string"}},
      "required": ["date", "meal"]}, tool_plan),
    ("meal_plan_week", "The meals planned for the week containing a date (default this week).",
     {"type": "object", "properties": {"date": {"type": "string"}}, "required": []}, tool_week),
]


def _page():
    from venato.ui import food as ui
    ui.render_page()


def _home():
    from venato.ui import food as ui
    ui.render_home()


BLOCK = Block("food", "Food", ":material/restaurant:",
              "A food diary with calories and macros against your targets, and a weekly meal planner.",
              group="Food", page=_page, home=_home, tools=TOOLS, prompt=PROMPT, context=_context,
              quick=[_quick], schema=SCHEMA, order=34)
