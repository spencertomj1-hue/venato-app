"""
Timetable categories (name, colour, group), the activity -> category defaults, and the
category calendar events get.

A label or an event's title means a category when it matches an activity's default or a category's
name, exactly or as whole words inside it ("Rugby training" -> Sports, from "Rugby"): match_category.
Saving a block with a category teaches its label (learn_label).
"""

import re
import sqlite3

from .database import _read, data_version, db, db_path
from .settings import load_settings


# Examples to suggest when someone adds their first categories. A new install starts with none.
# (id, name, colour, text colour, group) in key order.
EXAMPLE_CATEGORIES = [
    ("sleep", "Sleep", "#D0D0D0", None, "Life"),
    ("meals", "Meals", "#F7C7AC", None, "Life"),
    ("exercise", "Exercise", "#FFC000", None, "Life"),
    ("social", "Social", "#D86DCD", None, "Life"),
    ("rest", "Rest", "#E49EDD", None, "Life"),
    ("reading", "Reading", "#7030A0", "#FFFFFF", "Life"),
    ("commute", "Commute", "#FFF7B8", None, "Life"),
    ("chores", "Chores", "#92D050", None, "Life"),
    ("distracted", "Distracted", "#FF0000", None, "Life"),
    ("classes", "Classes", "#00B0F0", None, "Work"),
    ("study", "Study", "#00B050", None, "Work"),
    ("work", "Work", "#83CCEB", None, "Work"),
    ("projects", "Projects", "#DAF2D0", None, "Work"),
]


# Outlook events use this category when there is one, unless settings.json says otherwise ("outlook_category").
DEFAULT_OUTLOOK_CATEGORY = "classes"


# Activities that could default to one of the examples above (suggestions only; nothing is saved).
EXAMPLE_LABEL_MAP = {
    "Sleep": "sleep", "Breakfast": "meals", "Lunch": "meals", "Dinner": "meals",
    "Gym": "exercise", "Run": "exercise", "Lecture": "classes", "Seminar": "classes",
    "Homework": "study", "Revision": "study", "Commute": "commute",
}


def load_categories():
    return _read("SELECT * FROM tt_categories ORDER BY grp, ord")


def groups():
    """Category groups in the order they first appear in the key, e.g. ["Life", "Work"]."""
    with db() as conn:
        rows = conn.execute("SELECT grp FROM tt_categories ORDER BY rowid").fetchall()
    return list(dict.fromkeys(r[0] for r in rows))


def load_label_map():
    return _read("SELECT * FROM tt_label_map ORDER BY label")


def save_category(cid, name, colour, grp, text_colour=None):
    """Create or update one category (keeps its place in the key)."""
    with db() as conn:
        exists = conn.execute("SELECT ord FROM tt_categories WHERE id = ?", (cid,)).fetchone()
        if exists:
            conn.execute("UPDATE tt_categories SET name = ?, colour = ?, grp = ?, text_colour = ? WHERE id = ?",
                         (name, colour.upper(), grp, text_colour, cid))
        else:
            order = conn.execute("SELECT COALESCE(MAX(ord), -1) + 1 FROM tt_categories WHERE grp = ?", (grp,)).fetchone()[0]
            conn.execute("INSERT INTO tt_categories VALUES (?, ?, ?, ?, ?, ?)",
                         (cid, name, colour.upper(), text_colour, grp, order))


def set_label_default(label, category_id):
    """Make an activity label default to a category."""
    with db() as conn:
        conn.execute("DELETE FROM tt_label_map WHERE lower(label) = lower(?)", (label,))
        conn.execute("INSERT INTO tt_label_map VALUES (?, ?)", (label.strip(), category_id))


def remove_label_default(label):
    """Forget an activity label's default category."""
    with db() as conn:
        conn.execute("DELETE FROM tt_label_map WHERE lower(label) = lower(?)", (label,))


def match_category(label, label_map=None, categories=None):
    """
    The category a typed label (or an event's title) means, or None. First an exact match (any case)
    with an activity's default ('Boxing' -> Sports), then with a category's name ('Revision'); then the
    longest activity or category name found as whole words inside it ('Rugby training' -> Sports from
    'Rugby', 'Maths revision' -> Revision). Activities beat category names. timetable_component.js
    mirrors this (mapLabel).
    """
    want = str(label or "").strip().lower()
    if not want:
        return None
    lm = load_label_map() if label_map is None else label_map
    cats = load_categories() if categories is None else categories
    ids = set(cats["id"])
    defaults = [(str(l).strip().lower(), c) for l, c in zip(lm["label"], lm["category_id"]) if c in ids]
    names = [(str(n).strip().lower(), i) for n, i in zip(cats["name"], cats["id"])]
    for pool in (defaults, names):
        for phrase, cid in pool:
            if phrase == want:
                return cid
    for pool in (defaults, names):                   # an activity inside the label beats a category name
        best, best_len = None, 0
        for phrase, cid in pool:
            if phrase and len(phrase) > best_len and re.search(rf"(?<!\w){re.escape(phrase)}(?!\w)", want):
                best, best_len = cid, len(phrase)
        if best:
            return best
    return None


def learn_label(label, category_id):
    """Remember a label's category when someone saves a block with it, unless it already means that.
    Returns True when it learned something."""
    label = str(label or "").strip()
    if not label or not category_id:
        return False
    cats = load_categories()
    if category_id not in set(cats["id"]) or match_category(label, categories=cats) == category_id:
        return False
    set_label_default(label, category_id)
    return True


def _module_codes():
    """{normalised module code: its category id} (SQL only: the store never imports the blocks; no Modules
    tables = no codes)."""
    from venato import feeds
    try:
        with db() as conn:
            rows = conn.execute("SELECT code, category_id FROM gr_modules WHERE code IS NOT NULL "
                                "AND category_id IS NOT NULL ORDER BY created_at").fetchall()
    except sqlite3.OperationalError:
        return {}
    out = {}
    for code, cid in rows:
        if feeds.norm_code(code):
            out.setdefault(feeds.norm_code(code), cid)
    return out


def _code_category(text, ids):
    """The category of the module whose code is the whole text, a word in it, or a code inside it
    ('chem 50001 revision'), any case; or None."""
    from venato import feeds
    codes = {k: v for k, v in _module_codes().items() if v in ids}
    if not codes:
        return None
    text = str(text or "")
    found = [feeds.norm_code(text), *map(feeds.norm_code, text.split()), feeds.find_code(text.upper())]
    return next((codes[c] for c in found if c in codes), None)


def resolve_category(label=None, category=None):
    """
    Pick a category id. `category` may be an id, a name (any case) or a module's code; otherwise the label is
    matched: an exact activity or category name first, then a module code in it ('CHEM50001 problem sheet'),
    then match_category's words inside it. Returns None when nothing matches.
    """
    cats = load_categories()
    ids = set(cats["id"])
    by_name = {n.lower(): i for i, n in zip(cats["id"], cats["name"])}
    if category:
        key = category.strip()
        if key in ids:
            return key
        return by_name.get(key.lower()) or _code_category(key, ids)
    if label:
        lm = load_label_map()
        want = str(label).strip().lower()
        exact = {str(l).strip().lower() for l in lm["label"]} | set(by_name)
        if want in exact:
            return match_category(label, lm, cats)
        return _code_category(label, ids) or match_category(label, lm, cats)
    return None


_titles = {}    # (data version, database) -> {title: category or None}: events repeat, so match each title once


def _title_category(title):
    """match_category for an event's title, remembered until the data changes."""
    version = (data_version(), str(db_path()))
    if _titles.get("version") != version:
        _titles.clear()
        _titles.update(version=version, labels=load_label_map(), cats=load_categories(), seen={})
    seen = _titles["seen"]
    if title not in seen:
        seen[title] = match_category(title, _titles["labels"], _titles["cats"])
    return seen[title]


def outlook_category(title, module_id=None):
    """
    Category for Outlook events: the module's category for an event tagged with a module (module_id),
    else settings.json "outlook_category" (set by asking Claude), else the default, else the first
    category. With no categories at all: None (the event shows grey). (The title is kept for future rules.)
    """
    if module_id:
        with db() as conn:
            row = conn.execute("SELECT c.id FROM gr_modules m JOIN tt_categories c ON c.id = m.category_id "
                               "WHERE m.id = ?", (module_id,)).fetchone()
        if row:
            return row[0]
    wanted = load_settings().get("outlook_category") or DEFAULT_OUTLOOK_CATEGORY
    ids = list(load_categories()["id"])
    return wanted if wanted in ids else (ids[0] if ids else None)


_LOOK_UP = object()


def event_category(event, default=_LOOK_UP):
    """The category an imported event counts under: its module's (the module_category that
    outlook_between & co. read), else what its title means ("Boxing" -> Sports, like a typed label:
    match_category), else `default` (outlook_category(), looked up once by loops; None when there are
    no categories), else, with no default given, outlook_category(). Each event has exactly one, so
    its hours are counted once."""
    if event.get("module_category"):
        return event["module_category"]
    matched = _title_category(event.get("title") or "")
    if matched:
        return matched
    return outlook_category(event.get("title")) if default is _LOOK_UP else default


# Modules (Grades) each get a category in this group, coloured with the first of these no category uses yet.
MODULES_GROUP = "Modules"
MODULE_COLOURS = ["#4E79A7", "#F28E2B", "#59A14F", "#B07AA1", "#76B7B2", "#EDC948", "#FF9DA7", "#9C755F",
                  "#E15759", "#8CD17D", "#86BCB6", "#D4A6C8", "#A0CBE8", "#FFBE7D", "#BAB0AC", "#D37295"]


def next_free_colour(conn=None):
    """The first module colour no category uses (then round again)."""
    if conn is None:
        with db() as conn:
            return next_free_colour(conn)
    used = [r[0].upper() for r in conn.execute("SELECT colour FROM tt_categories")]
    free = [c for c in MODULE_COLOURS if c not in used]
    return free[0] if free else MODULE_COLOURS[len(used) % len(MODULE_COLOURS)]


def add_module_category(conn, cid, name):
    """Make a module's category (group "Modules", the next free colour) inside the caller's transaction,
    so it's made only if the module is. A plain insert: an id already taken fails rather than renaming
    another category. Returns its id."""
    order = conn.execute("SELECT COALESCE(MAX(ord), -1) + 1 FROM tt_categories WHERE grp = ?",
                         (MODULES_GROUP,)).fetchone()[0]
    conn.execute("INSERT INTO tt_categories VALUES (?, ?, ?, ?, ?, ?)",
                 (cid, name, next_free_colour(conn), None, MODULES_GROUP, order))
    return cid


def rename_category(cid, name):
    """Rename a category (keeps its colour, group and place)."""
    with db() as conn:
        conn.execute("UPDATE tt_categories SET name = ? WHERE id = ?", (name, cid))
