"""
Home's grid of tiles: which tiles are on Home, in what order and what size. No Streamlit here
(ui/home.py draws it).

The layout is one list of cells, saved in settings.json as "home":
    [{"w": "timetable_today", "size": "large", "at": [0, 0]}, {"w": "todos", "size": "wide", "at": [0, 2]}, ...]
Home is a grid four columns wide. A tile is Small (1 x 1), Wide (2 x 1), Large (2 x 2), Tall (1 x 2) or
Column (1 x 3: the height of the starting Home, for today's whole timetable).

"at" is the tile's top-left cell, [row, column] (0-based): Edit Home lets a tile go anywhere on the grid, gaps
and all. A tile without one (the starting Home, a layout from before tiles could be placed freely, a tile just
added) takes the first free place it fits, reading left to right, top to bottom; one whose place is off the grid
or already taken does the same. The first move or resize pins every tile where it was drawn (pin), so nothing
else jumps.

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
                out.append(_with_at({"w": k, "size": size_of(cell.get("size"), available.get(k), sizes.get(k))},
                                    cell.get("at")))
    return out


def _at(value):
    """A saved place as (row, column), or None when it isn't one."""
    if isinstance(value, (list, tuple)) and len(value) == 2 and all(type(v) is int and v >= 0 for v in value):
        return tuple(value)
    return None


def _with_at(cell, at):
    if _at(at):
        cell["at"] = list(_at(at))
    return cell


def keys(cells):
    """Every tile key in order."""
    return [c["w"] for c in cells]


def hidden(cells, available):
    """The tiles on offer that aren't on Home, in the order they're offered."""
    shown = set(keys(cells))
    return [k for k in available if k not in shown]


def span(size):
    return SPANS.get(size, SPANS["wide"])


def _area(row, col, size, columns=COLUMNS):
    w, h = span(size)
    w = min(w, columns)
    return {(row + dy, col + dx) for dy in range(h) for dx in range(w)}


def place(cells, columns=COLUMNS):
    """Where each tile lands: [(row, column)] (0-based). A tile with a place ("at") that's on the grid and free
    keeps it (first come, first served); the rest take the first free place they fit, reading left to right, top
    to bottom (so a small tile fills a gap left by a big one)."""
    taken, out = set(), [None] * len(cells)
    for i, c in enumerate(cells):
        at = _at(c.get("at"))
        if at and at[1] + min(span(c["size"])[0], columns) <= columns:
            area = _area(*at, c["size"], columns)
            if not area & taken:
                taken |= area
                out[i] = at
    for i, c in enumerate(cells):
        if out[i] is not None:
            continue
        w = min(span(c["size"])[0], columns)
        row = 0
        while True:
            spot = next((col for col in range(columns - w + 1) if not _area(row, col, c["size"], columns) & taken),
                        None)
            if spot is not None:
                break
            row += 1
        taken |= _area(row, spot, c["size"], columns)
        out[i] = (row, spot)
    return out


def pin(cells, columns=COLUMNS):
    """Every tile with its place written in ("at"), in reading order (top to bottom, left to right): how it's
    drawn now, so an edit moves only what it means to."""
    out = [dict(deepcopy(c), at=list(at)) for c, at in zip(cells, place(cells, columns))]
    return sorted(out, key=lambda c: tuple(c["at"]))


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
                out.append(_with_at({"w": k, "size": size_of(cell.get("size"))}, cell.get("at")))
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


def reorder(cells, order):
    """The tiles in this order (a drag ends with the order the grid showed). Keys not on Home are ignored;
    tiles the order leaves out keep their place after the rest. Sizes go with their tiles."""
    rank = {k: i for i, k in enumerate(k for k in order if isinstance(k, str))}
    return [deepcopy(c) for c in sorted(cells, key=lambda c: rank.get(c["w"], len(rank)))]


def step(cells, key, delta):
    """One place back (-1) or forward (+1)."""
    out = deepcopy(cells)
    i = find(cells, key)
    if i is not None and 0 <= i + delta < len(out):
        out[i], out[i + delta] = out[i + delta], out[i]
    return out


def _settle(cells, key, columns=COLUMNS):
    """cells all pinned, key just put down: each tile it now overlaps goes to the nearest free place it fits
    (the gap key left, usually), the ones nearer the top first. Back in reading order."""
    me = next(c for c in cells if c["w"] == key)
    mine = _area(*me["at"], me["size"], columns)
    hit = [c for c in cells if c is not me and _area(*c["at"], c["size"], columns) & mine]
    taken = set(mine)
    for c in cells:
        if c is not me and c not in hit:
            taken |= _area(*c["at"], c["size"], columns)
    bottom = max(r for r, _ in taken) + 1 if taken else 0
    for c in sorted(hit, key=lambda c: tuple(c["at"])):
        w, h = min(span(c["size"])[0], columns), span(c["size"])[1]
        r0, c0 = c["at"]
        spots = [(r, q) for r in range(bottom + h + 1) for q in range(columns - w + 1)
                 if not _area(r, q, c["size"], columns) & taken]
        r, q = min(spots, key=lambda s: (abs(s[0] - r0) + abs(s[1] - c0), s))
        c["at"] = [r, q]
        taken |= _area(r, q, c["size"], columns)
        bottom = max(bottom, r + h)
    return sorted(cells, key=lambda c: tuple(c["at"]))


def move_to(cells, key, row, col, columns=COLUMNS):
    """Put a tile with its top-left corner at (row, col), anywhere on the grid (a column that would push it off
    the right edge is pulled back). Where it lands on tiles that fit in the place it left, they swap; otherwise
    what it lands on goes to the nearest free place. Every tile is pinned (see the top)."""
    out = pin(cells, columns)
    i = find(out, key)
    if i is None or type(row) is not int or type(col) is not int:
        return deepcopy(cells)
    me = out[i]
    w = min(span(me["size"])[0], columns)
    row, col = max(0, row), min(max(0, col), columns - w)
    old = tuple(me["at"])
    if (row, col) == old:
        return out
    me["at"] = [row, col]
    mine = _area(row, col, me["size"], columns)
    hit = [c for c in out if c is not me and _area(*c["at"], c["size"], columns) & mine]
    # A swap: shift what it landed on by the way it moved, back into the place it left, if that's all clear.
    dy, dx = old[0] - row, old[1] - col
    moved = {c["w"]: (c["at"][0] + dy, c["at"][1] + dx) for c in hit}
    if hit and all(r >= 0 and 0 <= q <= columns - min(span(c["size"])[0], columns)
                   for c in hit for r, q in [moved[c["w"]]]):
        taken, ok = set(mine), True
        for c in out:
            if c is me:
                continue
            area = _area(*moved.get(c["w"], c["at"]), c["size"], columns)
            if area & taken:
                ok = False
                break
            taken |= area
        if ok:
            for c in hit:
                c["at"] = list(moved[c["w"]])
            return sorted(out, key=lambda c: tuple(c["at"]))
    return _settle(out, key, columns)


def resize(cells, key, size, columns=COLUMNS):
    """Give a tile one of the sizes. It keeps its top-left corner (pulled left if it would hang off the right
    edge); what it grows over goes to the nearest free place. Every tile is pinned (see the top)."""
    if size not in SPANS or find(cells, key) is None:
        return deepcopy(cells)
    out = pin(cells, columns)
    me = out[find(out, key)]
    me["size"] = size
    me["at"][1] = min(me["at"][1], columns - min(span(size)[0], columns))
    return _settle(out, key, columns)


def hide(cells, key):
    """Take a tile off Home (its data stays; it waits in "Add a tile")."""
    return [deepcopy(c) for c in cells if c["w"] != key]


def add(cells, key, size="wide"):
    """Put a hidden tile on Home: the first free place it fits."""
    out = deepcopy(cells)
    if find(cells, key) is None:
        out.append({"w": key, "size": size_of(size)})
    return out
