"""
Home's hidden grid: which widgets are on Home, in what order and how wide. No Streamlit here
(ui/home.py draws it).

The layout is one ordered list of cells, saved in settings.json as "home":
    [{"w": "timetable_today", "size": "l"}, {"stack": ["ask", "needs_you", "todos"], "size": "s"}, ...]
A cell is one widget, or a stack of widgets one above the other in one column. Sizes are parts of a
12-column row: S = 4 (a third), M = 6 (a half), L = 8 (two thirds), Full = 12. Cells flow left to right
into rows like the icons on a phone's home screen: one that doesn't fit starts a new row.

Every change below returns a new list (the one given is left alone). They work on a normalised list:
only widgets that are on offer right now, each once.
"""

from copy import deepcopy

COLUMNS = 12
SIZES = {"s": 4, "m": 6, "l": 8, "full": 12}
ORDER = list(SIZES)                    # small to big
SIZE_NAMES = {"s": "small", "m": "medium", "l": "large", "full": "full width"}

# Today's "Essentials" Home: the timetable, and beside it Ask, Needs you and To-dos stacked in one column.
_DEFAULT = [{"w": "timetable_today", "size": "l"}, {"stack": ["ask", "needs_you", "todos"], "size": "s"}]


def default():
    return deepcopy(_DEFAULT)


def reset():
    return default()


def _size(value, fallback):
    return value if value in SIZES else (fallback if fallback in SIZES else "m")


def _cell(keys, size):
    """A cell from its widgets: none -> None, one -> a widget, more -> a stack."""
    if not keys:
        return None
    return {"w": keys[0], "size": size} if len(keys) == 1 else {"stack": list(keys), "size": size}


def members(cell):
    """The widget keys in a cell, top to bottom."""
    return list(cell["stack"]) if "stack" in cell else [cell["w"]]


def normalise(layout, available):
    """The saved layout as it can be drawn now. available: {widget key: its default size} for the widgets
    on offer (their block is on, and so on). No saved list, or one with nothing that reads as a cell, gives the
    default (a deliberately empty list stays empty); unknown, switched-off and repeated widgets are skipped
    (a repeat inside a stack too); a stack keeps the widgets it still has."""
    cells = [c for c in layout if isinstance(c, dict) and (isinstance(c.get("stack"), list) or isinstance(c.get("w"), str))] \
        if isinstance(layout, list) else []
    if not cells and layout != []:
        cells = _DEFAULT
    out, seen = [], set()
    for cell in cells:
        raw = cell["stack"] if isinstance(cell.get("stack"), list) else [cell["w"]]
        keys = []
        for k in raw:
            if isinstance(k, str) and k in available and k not in seen:
                keys.append(k)
                seen.add(k)
        c = _cell(keys, _size(cell.get("size"), available.get(keys[0]) if keys else None))
        if c:
            out.append(c)
    return out


def keys(cells):
    """Every widget key in order (stacks top to bottom)."""
    return [k for c in cells for k in members(c)]


def hidden(cells, available):
    """The widgets on offer that aren't on Home, in the order they're offered."""
    shown = set(keys(cells))
    return [k for k in available if k not in shown]


def pack(cells):
    """The cells in rows, left to right: a cell that doesn't fit what's left of a row starts the next one."""
    rows, row, used = [], [], 0
    for c in cells:
        w = SIZES[c["size"]]
        if row and used + w > COLUMNS:
            rows.append(row)
            row, used = [], 0
        row.append(c)
        used += w
    if row:
        rows.append(row)
    return rows


def widths(row):
    return [SIZES[c["size"]] for c in row]


def spec(row):
    """Column widths for st.columns: the cells, plus a spacer filling a short row."""
    w = widths(row)
    return w + [COLUMNS - sum(w)] if sum(w) < COLUMNS else w


def keep_unavailable(raw, new, available):
    """What to save: the new layout, plus the widgets of the saved one that aren't on offer right now (a block
    switched off for a while) at the end, so they come back when it's on again."""
    out = deepcopy(new)
    have = set(keys(new))
    if not isinstance(raw, list):
        return out
    for cell in raw:
        if not isinstance(cell, dict):
            continue
        group = cell.get("stack") if isinstance(cell.get("stack"), list) else [cell.get("w")]
        for k in group:
            if isinstance(k, str) and k not in available and k not in have:
                out.append({"w": k, "size": _size(cell.get("size"), "m")})
                have.add(k)
    return out


# ---------------------------------------------------------------------------
# Arranging: each returns a new list
# ---------------------------------------------------------------------------

def find(cells, key):
    """(cell index, place in its stack or None), or None when it isn't there."""
    for i, c in enumerate(cells):
        if "stack" in c and key in c["stack"]:
            return i, c["stack"].index(key)
        if c.get("w") == key:
            return i, None
    return None


def _without(cells, key):
    """(the cells without this widget, the size of the cell it was in). A stack left with one is a widget."""
    out, size = [], None
    for c in cells:
        ks = members(c)
        if key in ks:
            size = c["size"]
            ks.remove(key)
            c = _cell(ks, c["size"])
            if c is None:
                continue
        out.append(deepcopy(c))
    return out, size


def move(cells, a, b):
    """Pick up a and drop it on b: a takes b's place and the rest flow round it (moving forward it lands
    after b, back it lands before). Dropped on a stacked widget it joins that stack."""
    if a == b or find(cells, a) is None or find(cells, b) is None:
        return deepcopy(cells)
    flat = keys(cells)
    forward = flat.index(a) < flat.index(b)
    out, size = _without(cells, a)
    ci, si = find(out, b)
    if si is not None:
        out[ci]["stack"].insert(si + forward, a)
    else:
        out.insert(ci + forward, {"w": a, "size": size})
    return out


def swap(cells, a, b):
    """a and b change places (two widgets on their own take their sizes with them)."""
    pa, pb = find(cells, a), find(cells, b)
    out = deepcopy(cells)
    if a == b or pa is None or pb is None:
        return out
    if pa[1] is None and pb[1] is None:
        out[pa[0]], out[pb[0]] = out[pb[0]], out[pa[0]]
        return out
    for (ci, si), key in ((pa, b), (pb, a)):
        if si is None:
            out[ci]["w"] = key
        else:
            out[ci]["stack"][si] = key
    return out


def step(cells, key, delta):
    """One place back (-1) or forward (+1): within its stack, out of the stack at its top or bottom, or past
    the next cell."""
    pos = find(cells, key)
    out = deepcopy(cells)
    if pos is None:
        return out
    ci, si = pos
    if si is not None:
        stack = out[ci]["stack"]
        j = si + delta
        if 0 <= j < len(stack):
            stack[si], stack[j] = stack[j], stack[si]
            return out
        out, size = _without(cells, key)
        ci = find(out, next(k for k in members(cells[ci]) if k != key))[0]
        out.insert(ci + (delta > 0), {"w": key, "size": size})
        return out
    j = ci + delta
    if 0 <= j < len(out):
        out[ci], out[j] = out[j], out[ci]
    return out


def resize(cells, key, delta):
    """A size smaller (-1) or bigger (+1), from S to Full. A stack changes size as one."""
    pos = find(cells, key)
    out = deepcopy(cells)
    if pos is not None:
        c = out[pos[0]]
        c["size"] = ORDER[max(0, min(len(ORDER) - 1, ORDER.index(c["size"]) + delta))]
    return out


def hide(cells, key):
    return _without(cells, key)[0]


def add(cells, key, size="m"):
    """Put a hidden widget on Home, at the end."""
    out = deepcopy(cells)
    if find(cells, key) is None:
        out.append({"w": key, "size": _size(size, "m")})
    return out
