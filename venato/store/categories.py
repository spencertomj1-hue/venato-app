"""
Timetable categories (name, colour, group), the activity -> category defaults, and the
category calendar events get.
"""

from .database import _read, db
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


def resolve_category(label=None, category=None):
    """
    Pick a category id. `category` may be an id or a name (any case); otherwise
    the label is looked up in the label map, then against category names.
    Returns None when nothing matches.
    """
    cats = load_categories()
    by_name = {n.lower(): i for i, n in zip(cats["id"], cats["name"])}
    if category:
        key = category.strip()
        if key in set(cats["id"]):
            return key
        return by_name.get(key.lower())
    if label:
        lm = load_label_map()
        for lbl, cid in zip(lm["label"], lm["category_id"]):
            if lbl.lower() == label.strip().lower():
                return cid
        return by_name.get(label.strip().lower())
    return None


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


def event_category(event, default=None):
    """The category an imported event counts under: its module's (the module_category that
    outlook_between & co. read), else `default` (outlook_category(), looked up once by loops), else
    outlook_category(). Each event has exactly one, so its hours are counted once."""
    if event.get("module_category"):
        return event["module_category"]
    return default if default is not None else outlook_category(event.get("title"))


# Modules (Grades) each get a category in this group, coloured with the first of these no category uses yet.
MODULES_GROUP = "Modules"
MODULE_COLOURS = ["#4E79A7", "#F28E2B", "#59A14F", "#B07AA1", "#76B7B2", "#EDC948", "#FF9DA7", "#9C755F",
                  "#E15759", "#8CD17D", "#86BCB6", "#D4A6C8", "#A0CBE8", "#FFBE7D", "#BAB0AC", "#D37295"]


def next_free_colour():
    """The first module colour no category uses (then round again)."""
    with db() as conn:
        used = [r[0].upper() for r in conn.execute("SELECT colour FROM tt_categories")]
    free = [c for c in MODULE_COLOURS if c not in used]
    return free[0] if free else MODULE_COLOURS[len(used) % len(MODULE_COLOURS)]


def add_module_category(cid, name):
    """A module's category: group "Modules", the next free colour. Returns its id."""
    save_category(cid, name, next_free_colour(), MODULES_GROUP)
    return cid


def rename_category(cid, name):
    """Rename a category (keeps its colour, group and place)."""
    with db() as conn:
        conn.execute("UPDATE tt_categories SET name = ? WHERE id = ?", (name, cid))
