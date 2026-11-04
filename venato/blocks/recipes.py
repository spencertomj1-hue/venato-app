"""
Recipes and the shopping list: recipes with ingredients (typed naturally, "200 g pasta"),
method, tags and nutrition per serving, scaled to any number of servings; a shopping list
grouped by aisle, filled by hand, from a recipe, or from the week's meal plan (Food block),
with the same items merged.
"""

import re
import uuid
from datetime import timedelta
from fractions import Fraction

from venato import store
from venato.blocks import Block

PER_SERVING = ("kcal", "protein", "carbs", "fat", "fibre")
UNITS = {"g": "g", "gram": "g", "grams": "g", "kg": "kg", "ml": "ml", "l": "l", "litre": "l", "litres": "l",
         "liter": "l", "tsp": "tsp", "teaspoon": "tsp", "teaspoons": "tsp", "tbsp": "tbsp", "tablespoon": "tbsp",
         "tablespoons": "tbsp", "cup": "cup", "cups": "cup", "oz": "oz", "lb": "lb", "lbs": "lb",
         "clove": "clove", "cloves": "clove", "can": "can", "cans": "can", "tin": "tin", "tins": "tin",
         "pack": "pack", "packs": "pack", "packet": "pack", "slice": "slice", "slices": "slice",
         "pinch": "pinch", "handful": "handful", "bunch": "bunch", "jar": "jar", "jars": "jar"}
AISLES = [   # (aisle, words that put an item there); first match wins
    ("Fruit & veg", "apple banana orange lemon lime berries grape pear onion garlic potato carrot tomato pepper "
                    "lettuce spinach kale cucumber courgette zucchini aubergine broccoli cauliflower mushroom "
                    "avocado ginger chilli herb basil coriander parsley mint celery leek peas sweetcorn"),
    ("Meat & fish", "chicken beef pork lamb mince bacon sausage ham turkey salmon tuna cod prawn fish steak"),
    ("Dairy & eggs", "milk cheese butter yoghurt yogurt cream egg eggs feta mozzarella parmesan cheddar"),
    ("Bakery", "bread bagel wrap tortilla pitta roll croissant bun"),
    ("Tins, jars & dry", "pasta rice noodle flour sugar oats cereal lentil chickpea beans stock tin can jar sauce "
                         "oil vinegar salt spice cumin paprika oregano honey jam peanut nut seed"),
    ("Frozen", "frozen ice"),
    ("Drinks", "juice water coffee tea cola wine beer"),
    ("Household", "soap toilet tissue detergent washing bin foil cling sponge"),
]

SCHEMA = """
CREATE TABLE IF NOT EXISTS recipes (
    id         TEXT PRIMARY KEY,
    name       TEXT NOT NULL UNIQUE COLLATE NOCASE,
    servings   REAL NOT NULL DEFAULT 2,
    prep_min   INTEGER, cook_min INTEGER,
    method     TEXT, tags TEXT, url TEXT, notes TEXT,
    kcal REAL, protein REAL, carbs REAL, fat REAL, fibre REAL,    -- per serving
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS recipe_ingredients (
    id        TEXT PRIMARY KEY,
    recipe_id TEXT NOT NULL REFERENCES recipes(id) ON DELETE CASCADE,
    ord       INTEGER NOT NULL,
    qty       REAL,
    unit      TEXT,
    item      TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS shopping (
    id         TEXT PRIMARY KEY,
    item       TEXT NOT NULL,
    qty        REAL,
    unit       TEXT,
    aisle      TEXT NOT NULL,
    done       INTEGER NOT NULL DEFAULT 0,
    source     TEXT,                       -- which recipe it came from, if any
    created_at TEXT NOT NULL
);
"""


class RecipeError(ValueError):
    pass


def _id():
    return uuid.uuid4().hex


# --- Ingredient lines ---

def _number(text):
    text = text.replace("½", " 1/2").replace("¼", " 1/4").replace("¾", " 3/4").replace("⅓", " 1/3").strip()
    total = 0.0
    for part in text.split():
        total += float(Fraction(part))
    return total


NUM = r"(\d+(?:\.\d+)?(?:\s+\d+/\d+)?|\d+/\d+|[½¼¾⅓]|\d+\s*[½¼¾⅓])"


def parse(line):
    """'200 g pasta' -> (200, 'g', 'pasta'); '2 onions' -> (2, '', 'onions'); 'salt' -> (None, '', 'salt')."""
    line = re.sub(r"\s+", " ", str(line or "").strip().lstrip("-•* ").strip())
    if not line:
        raise RecipeError("An ingredient line is empty.")
    m = re.match(rf"^{NUM}\s*([a-zA-Z]+)?\.?\s+(?:of\s+)?(.+)$", line) or re.match(rf"^{NUM}([a-zA-Z]+)\s+(.+)$", line)
    if m:
        qty = _number(m.group(1))
        unit = (m.group(2) or "").lower()
        if unit in UNITS:
            return qty, UNITS[unit], m.group(3).strip()
        return qty, "", f"{m.group(2) + ' ' if m.group(2) else ''}{m.group(3)}".strip()
    m = re.match(r"^(pinch|handful|bunch)\s+(?:of\s+)?(.+)$", line, re.I)
    if m:
        return None, m.group(1).lower(), m.group(2).strip()
    return None, "", line


def fmt_qty(qty, unit):
    if qty is None:
        return unit
    q = round(qty, 2)
    q = int(q) if q == int(q) else q
    return f"{q}{'' if unit in ('g', 'kg', 'ml', 'l') else ' ' if unit else ''}{unit}"


def line(qty, unit, item):
    return f"{fmt_qty(qty, unit)} {item}".strip()


def aisle_of(item):
    words = set(re.findall(r"[a-z]+", str(item).lower()))
    words |= {w.rstrip("s") for w in words}
    for aisle, keys in AISLES:
        if words & set(keys.split()):
            return aisle
    return "Other"


# --- Recipes ---

COLS = ("id", "name", "servings", "prep_min", "cook_min", "method", "tags", "url", "notes") + PER_SERVING


def save(name, ingredients=(), servings=2, method=None, tags=None, url=None, notes=None, prep_min=None,
         cook_min=None, recipe_id=None, **per_serving):
    """Add (or, with recipe_id, replace) a recipe. ingredients: lines like '200 g pasta'."""
    name = str(name or "").strip()
    if not name:
        raise RecipeError("The recipe needs a name.")
    servings = float(servings or 2)
    if not 0 < servings <= 100:
        raise RecipeError("Servings must be between 1 and 100.")
    if url and not re.match(r"^https?://", str(url).strip(), re.I):
        raise RecipeError("The link must start with http:// or https://.")
    parsed = [parse(l) for l in ingredients if str(l).strip()]
    nut = {k: None if per_serving.get(k) in (None, "") else float(per_serving[k]) for k in PER_SERVING}
    rid = recipe_id or _id()
    with store.db() as conn:
        clash = conn.execute("SELECT id FROM recipes WHERE name = ? COLLATE NOCASE AND id != ?", (name, rid)).fetchone()
        if clash:
            raise RecipeError(f"There's already a recipe called {name}.")
        if recipe_id:
            conn.execute(f"UPDATE recipes SET {', '.join(f'{c} = ?' for c in COLS[1:])} WHERE id = ?",
                         (name, servings, prep_min, cook_min, method, tags, url, notes, *nut.values(), rid))
            conn.execute("DELETE FROM recipe_ingredients WHERE recipe_id = ?", (rid,))
        else:
            conn.execute(f"INSERT INTO recipes ({', '.join(COLS)}, created_at) VALUES ({', '.join('?' * (len(COLS) + 1))})",
                         (rid, name, servings, prep_min, cook_min, method, tags, url, notes, *nut.values(), store.stamp()))
        conn.executemany("INSERT INTO recipe_ingredients VALUES (?, ?, ?, ?, ?, ?)",
                         [(_id(), rid, i, q, u, it) for i, (q, u, it) in enumerate(parsed)])
    return rid


def get(rid):
    with store.db() as conn:
        row = conn.execute(f"SELECT {', '.join(COLS)} FROM recipes WHERE id = ?", (rid,)).fetchone()
    return dict(zip(COLS, row)) if row else None


def all_recipes(query=None):
    with store.db() as conn:
        rows = conn.execute(f"SELECT {', '.join(COLS)} FROM recipes ORDER BY name COLLATE NOCASE").fetchall()
    out = [dict(zip(COLS, r)) for r in rows]
    if query:
        words = str(query).lower().split()
        out = [r for r in out if all(w in f"{r['name']} {r['tags'] or ''} "
                                         f"{' '.join(i['item'] for i in ingredients(r['id']))}".lower() for w in words)]
    return out


def find(name):
    want = str(name or "").strip().lower()
    pool = all_recipes()
    exact = [r for r in pool if r["name"].lower() == want]
    part = [r for r in pool if want and want in r["name"].lower()]
    return (exact or (part if len(part) == 1 else [None]))[0]


def ingredients(rid, servings=None):
    """[{qty, unit, item}] for a recipe, scaled to `servings` if given."""
    r = get(rid)
    scale = (float(servings) / r["servings"]) if (r and servings) else 1
    with store.db() as conn:
        rows = conn.execute("SELECT qty, unit, item FROM recipe_ingredients WHERE recipe_id = ? ORDER BY ord",
                            (rid,)).fetchall()
    return [{"qty": None if q is None else q * scale, "unit": u or "", "item": it} for q, u, it in rows]


def delete(rid):
    with store.db() as conn:
        conn.execute("DELETE FROM recipe_ingredients WHERE recipe_id = ?", (rid,))
        conn.execute("DELETE FROM recipes WHERE id = ?", (rid,))


# --- Shopping ---

SHOP_COLS = ("id", "item", "qty", "unit", "aisle", "done", "source")


def shopping(include_done=True):
    with store.db() as conn:
        rows = conn.execute(f"SELECT {', '.join(SHOP_COLS)} FROM shopping"
                            + ("" if include_done else " WHERE done = 0") + " ORDER BY done, aisle, item COLLATE NOCASE").fetchall()
    return [dict(zip(SHOP_COLS, r)) for r in rows]


def add_item(text_or_item, qty=None, unit="", source=None):
    """Add to the shopping list, merging with an unticked item of the same name and unit."""
    if qty is None and not unit:
        qty, unit, item = parse(text_or_item)
    else:
        item = str(text_or_item).strip()
    if not item:
        raise RecipeError("Say what to buy.")
    with store.db() as conn:
        row = conn.execute("SELECT id, qty FROM shopping WHERE item = ? COLLATE NOCASE AND COALESCE(unit, '') = ? "
                           "AND done = 0", (item, unit or "")).fetchone()
        if row:
            if qty is not None or row[1] is not None:
                conn.execute("UPDATE shopping SET qty = ? WHERE id = ?", ((row[1] or 0) + (qty or 0) or None, row[0]))
            return row[0]
        sid = _id()
        conn.execute(f"INSERT INTO shopping ({', '.join(SHOP_COLS)}, created_at) VALUES (?, ?, ?, ?, ?, 0, ?, ?)",
                     (sid, item, qty, unit or "", aisle_of(item), source, store.stamp()))
        return sid


def tick(sid, done=True):
    with store.db() as conn:
        conn.execute("UPDATE shopping SET done = ? WHERE id = ?", (int(bool(done)), sid))


def remove_item(sid):
    with store.db() as conn:
        conn.execute("DELETE FROM shopping WHERE id = ?", (sid,))


def clear_done():
    with store.db() as conn:
        return conn.execute("DELETE FROM shopping WHERE done = 1").rowcount


def recipe_to_shopping(rid, servings=None):
    r = get(rid)
    if not r:
        raise RecipeError("No such recipe.")
    items = ingredients(rid, servings)
    for i in items:
        add_item(i["item"], i["qty"], i["unit"], source=r["name"])
    return len(items)


def plan_to_shopping(first, last):
    """Everything needed for the recipes in the meal plan between two dates (Food block)."""
    from venato.blocks import food
    n = 0
    for p in food.planned(first, last):
        if p["recipe_id"] and get(p["recipe_id"]):
            n += recipe_to_shopping(p["recipe_id"], p["servings"])
    return n


# --- The assistant ---

def tool_add(name, ingredients=None, servings=2, method=None, tags=None, kcal=None, protein=None, carbs=None, fat=None):
    from venato import tools
    try:
        save(name, ingredients or [], servings, method, tags, kcal=kcal, protein=protein, carbs=carbs, fat=fat)
    except (RecipeError, ValueError, ZeroDivisionError) as e:
        raise tools.ToolError(str(e))
    return tools.Result(f"Saved the recipe {name} ({len(ingredients or [])} ingredients, serves {servings:g}).",
                        changed=True)


def tool_list(query=None):
    from venato import tools
    rows = all_recipes(query)
    if not rows:
        return tools.Result("No recipes" + (" match." if query else " yet."))
    return tools.Result("\n".join(f"- {r['name']} (serves {r['servings']:g})" + (f" [{r['tags']}]" if r["tags"] else "")
                                  for r in rows))


def tool_show(name, servings=None):
    from venato import tools
    r = find(name)
    if not r:
        raise tools.ToolError(f"No recipe called '{name}'.")
    ings = ingredients(r["id"], servings)
    text = f"{r['name']} (for {float(servings or r['servings']):g}):\n" + "\n".join(
        f"- {line(i['qty'], i['unit'], i['item'])}" for i in ings)
    if r["method"]:
        text += f"\nMethod:\n{r['method']}"
    return tools.Result(text)


def tool_shop_add(items):
    from venato import tools
    if isinstance(items, str):
        items = [items]
    try:
        for it in items:
            add_item(it)
    except RecipeError as e:
        raise tools.ToolError(str(e))
    return tools.Result(f"Added to the shopping list: {', '.join(items)}.", changed=True)


def tool_shop_list():
    from venato import tools
    rows = shopping(include_done=False)
    if not rows:
        return tools.Result("The shopping list is empty.")
    by = {}
    for r in rows:
        by.setdefault(r["aisle"], []).append(line(r["qty"], r["unit"], r["item"]))
    return tools.Result("\n".join(f"{a}: {', '.join(v)}" for a, v in by.items()))


def tool_shop_tick(item):
    from venato import tools
    want = str(item).strip().lower()
    hit = [r for r in shopping(False) if r["item"].lower() == want] or \
          [r for r in shopping(False) if want in r["item"].lower()]
    if not hit:
        raise tools.ToolError(f"'{item}' isn't on the shopping list.")
    tick(hit[0]["id"])
    return tools.Result(f"Ticked off {hit[0]['item']}.", changed=True)


def tool_from_recipe(name, servings=None):
    from venato import tools
    r = find(name)
    if not r:
        raise tools.ToolError(f"No recipe called '{name}'.")
    n = recipe_to_shopping(r["id"], servings)
    return tools.Result(f"Added {n} ingredients for {r['name']} to the shopping list.", changed=True)


def tool_from_plan(days=7):
    from venato import tools
    today = store.local_today()
    n = plan_to_shopping(today, today + timedelta(days=int(days) - 1))
    return tools.Result(f"Added {n} ingredients from the next {days} days' planned recipes." if n else
                        "No planned recipes in that time.", changed=bool(n))


QUICK = re.compile(r"(?:add\s+(.+?)\s+to\s+(?:the\s+|my\s+)?shopping(?:\s+list)?|buy\s+(.+)|need\s+to\s+buy\s+(.+))")


def _quick(text, day):
    """'add milk and eggs to the shopping list', 'buy bread'."""
    m = QUICK.fullmatch(text)
    if not m:
        return None
    what = m.group(1) or m.group(2) or m.group(3)
    parts = [p.strip() for p in re.split(r",|\band\b", what) if p.strip()]
    return tool_shop_add(parts) if parts else None


def _context():
    rows = shopping(include_done=False)
    text = f"{len(all_recipes())} recipes saved. Shopping list: "
    return text + (", ".join(line(r["qty"], r["unit"], r["item"]) for r in rows[:20]) or "empty") + "."


PROMPT = """- Recipes and shopping list (the Recipes page). add_recipe(name, ingredients=["200 g pasta", "2 onions"],
  servings, method, tags, nutrition per serving); list_recipes(query) and show_recipe(name, servings) scale it.
  "add milk and eggs to the shopping list" -> add_to_shopping(items=["milk", "eggs"]); shopping_list;
  tick_shopping(item); recipe_to_shopping(name, servings); shopping_from_plan(days) adds everything the
  planned recipes (Food block) need."""

TOOLS = [
    ("add_recipe", "Save a recipe: ingredients as lines like '200 g pasta', servings, method, tags, nutrition per serving.",
     {"type": "object", "properties": {"name": {"type": "string"},
                                       "ingredients": {"type": "array", "items": {"type": "string"}},
                                       "servings": {"type": "number"}, "method": {"type": "string"},
                                       "tags": {"type": "string"}, **{k: {"type": "number"} for k in PER_SERVING[:4]}},
      "required": ["name"]}, tool_add),
    ("list_recipes", "The user's recipes, optionally matching words (name, tags or ingredients).",
     {"type": "object", "properties": {"query": {"type": "string"}}, "required": []}, tool_list),
    ("show_recipe", "A recipe's ingredients (scaled to servings) and method.",
     {"type": "object", "properties": {"name": {"type": "string"}, "servings": {"type": "number"}},
      "required": ["name"]}, tool_show),
    ("add_to_shopping", "Add items to the shopping list (each like '2 onions' or 'milk').",
     {"type": "object", "properties": {"items": {"type": "array", "items": {"type": "string"}}},
      "required": ["items"]}, tool_shop_add),
    ("shopping_list", "What's on the shopping list, by aisle.",
     {"type": "object", "properties": {}, "required": []}, tool_shop_list),
    ("tick_shopping", "Tick an item off the shopping list.",
     {"type": "object", "properties": {"item": {"type": "string"}}, "required": ["item"]}, tool_shop_tick),
    ("recipe_to_shopping", "Add a recipe's ingredients (scaled to servings) to the shopping list.",
     {"type": "object", "properties": {"name": {"type": "string"}, "servings": {"type": "number"}},
      "required": ["name"]}, tool_from_recipe),
    ("shopping_from_plan", "Add the ingredients of the recipes planned in the next N days (default 7).",
     {"type": "object", "properties": {"days": {"type": "integer"}}, "required": []}, tool_from_plan),
]


def _page():
    from venato.ui import recipes as ui
    ui.render_page()


def _home():
    from venato.ui import recipes as ui
    ui.render_home()


BLOCK = Block("recipes", "Recipes", ":material/menu_book:",
              "Your recipes, scaled to any number of servings, and a shopping list by aisle (filled from your meal plan).",
              group="Food", page=_page, home=_home, tools=TOOLS, prompt=PROMPT, context=_context,
              quick=[_quick], schema=SCHEMA, order=35)
