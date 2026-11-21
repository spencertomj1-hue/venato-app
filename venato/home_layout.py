"""
Home's grid of tiles: which tiles are on Home, in what order and what size. No Streamlit here
(ui/home.py draws it).

The layout is one ordered list of cells, saved in settings.json as "home":
    [{"w": "timetable_today", "size": "large"}, {"w": "todos", "size": "wide"}, ...]
Home is a grid four columns wide. A tile is Small (1 x 1), Wide (2 x 1), Large (2 x 2), Tall (1 x 2) or
Column (1 x 3: the height of the starting Home, for today's whole timetable), and
the tiles fill the grid left to right, top to bottom, each taking the first place it fits (so a small tile
can fill a gap left by a big one).

Older layouts are converted as they're read (normalise): the old 12-column sizes (s / m / l / full) become
Small / Wide / Large / Wide, and a stack of widgets in one column becomes its widgets one after another.
Nothing is lost: the next change saves the new form.

Every change below returns a new list (the one given is left alone). They work on a normalised list:
only tiles that are on offer right now, each once.
"""

from copy import deepcopy

COLUMNS = 4
# size -> (columns, rows) it spans
SPANS = {"small": (1, 1), "wide": (2, 1), "large": (2, 2), "tall": (1, 2), "column": (1, 3)}
ORDER = list(SPANS)                    # how the size picker lists them
SIZE_NAMES = {"small": "Small", "wide": "Wide", "large": "Large", "tall": "Tall", "column": "Column"}
_OLD = {"s": "small", "m": "wide", "l": "large", "full": "wide"}     # the 12-column sizes before tiles

# The starting Home, on one screen (three rows): today's whole timetable down the left (Column); To-dos and Focus,
# Goals and Review, then Daily log and Needs you beside it. Modules (students) comes last, so it starts a fourth
# row: Home's rows then share the screen four ways rather than a tile being left off.
_DEFAULT = [{"w": "timetable_today", "size": "column"}, {"w": "todos", "size": "wide"}, {"w": "focus", "size": "small"},
            {"w": "goals", "size": "wide"}, {"w": "review", "size": "small"}, {"w": "habits", "size": "small"},
            {"w": "needs_you", "size": "wide"}, {"w": "modules", "size": "small"}]


def default():
    return deepcopy(_DEFAULT)


def reset():
    return default()


def size_of(value, fallback="wide", allowed=None):
    """A saved size as one of today's: an old 12-column size is converted; anything else, or a size this tile
    doesn't come in (allowed), gives the fallback."""
    value = _OLD.get(value, value)
    ok = allowed or ORDER
    if value in SPANS and value in ok:
        return value
    fallback = _OLD.get(fallback, fallback)
    return fallback if fallback in SPANS else (ok[0] if ok else "wide")


def _members(cell):
    """The widget keys in a saved cell (an old stack: top to bottom)."""
    if isinstance(cell.get("stack"), list):
        return list(cell["stack"])
    return [cell["w"]] if isinstance(cell.get("w"), str) else []


def _readable(layout):
    return [c for c in layout if isinstance(c, dict) and (isinstance(c.get("stack"), list) or isinstance(c.get("w"), str))] \
        if isinstance(layout, list) else []


def normalise(layout, available, sizes=None):
    """The saved layout as it can be drawn now. available: {tile key: its default size} for the tiles on offer
    (their block is on, and so on); sizes: {tile key: the sizes it comes in} (missing: all of them).
    No saved list, or one with nothing that reads as a cell, gives the default (a deliberately empty list stays
    empty); unknown, switched-off and repeated tiles are skipped; old layouts are converted (see the top)."""
    sizes = sizes or {}
    cells = _readable(layout)
    if not cells and layout != []:
        cells = _DEFAULT
    out, seen = [], set()
    for cell in cells:
        for k in _members(cell):
            if isinstance(k, str) and k in available and k not in seen:
                seen.add(k)
                out.append({"w": k, "size": size_of(cell.get("size"), available.get(k), sizes.get(k))})
    return out


def keys(cells):
    """Every tile key in order."""
    return [c["w"] for c in cells]


def hidden(cells, available):
    """The tiles on offer that aren't on Home, in the order they're offered."""
    shown = set(keys(cells))
    return [k for k in available if k not in shown]


def span(size):
    return SPANS.get(size, SPANS["wide"])


def place(cells, columns=COLUMNS):
    """Where each tile lands: [(row, column)] (0-based), each tile in the first free place it fits, reading left
    to right, top to bottom (the browser's dense grid does the same)."""
    taken, out = set(), []
    for c in cells:
        w, h = span(c["size"])
        w = min(w, columns)
        row = 0
        while True:
            spot = next((col for col in range(columns - w + 1)
                         if all((row + dy, col + dx) not in taken for dy in range(h) for dx in range(w))), None)
            if spot is not None:
                break
            row += 1
        taken |= {(row + dy, spot + dx) for dy in range(h) for dx in range(w)}
        out.append((row, spot))
    return out


def rows(cells, columns=COLUMNS):
    """How many grid rows the tiles take (0 for none): Home sizes its rows so this many fit on one screen."""
    return max((r + span(c["size"])[1] for c, (r, _) in zip(cells, place(cells, columns))), default=0)


def keep_unavailable(raw, new, available):
    """What to save: the new layout, plus the tiles of the saved one that aren't on offer right now (a block
    switched off for a while) at the end, so they come back when it's on again."""
    out = deepcopy(new)
    have = set(keys(new))
    for cell in _readable(raw):
        for k in _members(cell):
            if isinstance(k, str) and k not in available and k not in have:
                out.append({"w": k, "size": size_of(cell.get("size"))})
                have.add(k)
    return out


# ---------------------------------------------------------------------------
# Editing: each returns a new list
# ---------------------------------------------------------------------------

def find(cells, key):
    """The tile's place in the list, or None when it isn't on Home."""
    return next((i for i, c in enumerate(cells) if c["w"] == key), None)


def move(cells, a, b):
    """Pick up a and drop it on b: a takes b's place and the rest flow round it (moving forward it lands
    after b, back it lands before). b None: to the end."""
    out = deepcopy(cells)
    i = find(cells, a)
    if i is None or a == b:
        return out
    cell = out.pop(i)
    if b is None:
        out.append(cell)
        return out
    j = find(out, b)
    if j is None:
        return deepcopy(cells)
    out.insert(j + (j >= i), cell)
    return out


def step(cells, key, delta):
    """One place back (-1) or forward (+1)."""
    out = deepcopy(cells)
    i = find(cells, key)
    if i is not None and 0 <= i + delta < len(out):
        out[i], out[i + delta] = out[i + delta], out[i]
    return out


def resize(cells, key, size):
    """Give a tile one of the sizes."""
    out = deepcopy(cells)
    i = find(cells, key)
    if i is not None and size in SPANS:
        out[i]["size"] = size
    return out


def hide(cells, key):
    """Take a tile off Home (its data stays; it waits in "Add a tile")."""
    return [deepcopy(c) for c in cells if c["w"] != key]


def add(cells, key, size="wide"):
    """Put a hidden tile on Home, at the end."""
    out = deepcopy(cells)
    if find(cells, key) is None:
        out.append({"w": key, "size": size_of(size)})
    return out
