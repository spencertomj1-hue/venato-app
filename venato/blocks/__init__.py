"""
Blocks: the parts of Venato you can switch on and off, like Lego.

Each block is a module in this package with a module-level BLOCK (or BLOCKS) describing it:
its pages, its Home tiles, what it adds to Home's "Needs you", its database tables, and what it gives the Claude
assistant (tools, a paragraph of instructions, a line in the [Now] snapshot, quick
commands). The setup wizard shows them as cards to tick; Settings → Blocks changes them
later and sets their order. Where their widgets go on Home is Home's own layout (home_layout.py).

Adding a block = adding a file here; nothing else needs to know about it. (That's also how
the private copy adds its own pages without touching the shared code.)
"""

import importlib
import pkgutil
from dataclasses import dataclass, field
from typing import Callable


_OLD_SIZES = {"s": "small", "m": "wide", "l": "large", "full": "wide"}


@dataclass
class Widget:
    """A tile a block offers for Home. Its key is saved in Home's layout (settings.json "home"), so it
    stays the same; size is where it starts: "small", "wide", "large" or "tall" (the old "s" / "m" / "l" /
    "full" still work). The whole tile opens `page` (left empty: its block's page; None: no page)."""
    key: str
    name: str                        # its tile's title, and in Home's "Add a tile" list
    draw: Callable                   # the live preview under the title
    size: str = "wide"
    sizes: tuple = ("small", "wide", "large", "tall")    # the sizes it comes in
    page: str | None = ""            # the page the tile opens
    status: Callable | None = None   # -> a few words for the tile's header ("1 of 4 done today"), or ""
    icon: str = ""                   # a Material icon for its header (empty: its block's)
    colour: str = ""                 # its icon square (empty: grey)

    def __post_init__(self):
        self.size = _OLD_SIZES.get(self.size, self.size)
        if self.size not in self.sizes:
            self.sizes = (*self.sizes, self.size)


@dataclass
class Block:
    key: str                         # stable id, saved in settings.json
    name: str                        # its page's name (Home's tiles open it)
    icon: str                        # a Material icon, e.g. ":material/timer:"
    blurb: str                       # one line for the card in setup / Settings
    group: str = "Other"             # how the cards are grouped
    page: Callable | None = None     # draws its page (None: no page of its own)
    widgets: list = field(default_factory=list)    # its Home widgets: [Widget]
    home: Callable | None = None     # older blocks: one Home widget (keyed by the block, medium); use widgets
    needs: Callable | None = None    # -> items for Home's "Needs you": a str, or {"text", "icon"?, "page"?}
    tools: list = field(default_factory=list)      # assistant tools, as in assistant.TOOL_SPECS
    prompt: str = ""                 # a paragraph for the assistant about this block
    context: Callable | None = None  # -> text for the assistant's [Now] snapshot
    quick: list = field(default_factory=list)      # quick commands: (text, day) -> tools.Result | None
    schema: str = ""                 # SQL for its tables (CREATE TABLE IF NOT EXISTS ...)
    migrate: Callable | None = None  # conn -> None: later changes to its tables
    order: int = 100                 # where its page goes in lists of pages
    default: bool = False            # on for someone who never chose (existing installs: the original pages)
    core: bool = False               # one of the built-in blocks: on for new installs and offered in setup. Extras
                                     # a copy adds stay False: they sit under "More blocks" and setup never offers them
    page_name: str = ""              # the page it shares, when not its own name (two blocks can share one page)
    search: dict = field(default_factory=dict)      # Home search: kind -> (select, haystack[, order]), as in store._SEARCH
    search_icons: dict = field(default_factory=dict)  # kind -> Material icon name for its search results
    search_open: Callable | None = None             # (result, session_state) -> None: routes a click on a result
    review: Callable | None = None   # (first, last) -> {"title": str, "lines": [str]} for the weekly review; no lines = nothing
    status: dict = field(default_factory=dict)      # word in its tools' names -> what the chat shows while one runs
    pages: dict = field(default_factory=dict)       # more pages of its own: {name: draws it}, before its main one

    def home_widgets(self):
        """Its Home tiles. A block that still sets `home` (and no widgets) has one, keyed by the block. A tile
        with no page of its own opens its block's page, and takes its block's icon."""
        out = list(self.widgets) if self.widgets else ([Widget(self.key, self.name, self.home, "wide")] if self.home else [])
        for w in out:
            if w.page == "" and self.page:
                w.page = self.page_name or self.name
            if not w.icon:
                w.icon = self.icon
        return out


GROUPS = ["Plan", "Health & body", "Study & work", "Other"]

# The blocks a new setup starts with: the core ones, bar Grades (setup adds that for students).
STARTER = ["timetable", "goals", "stats", "focus", "log"]

# What was always on before every block could be switched off. Settings saved back then keep these on.
_ONCE_ALWAYS_ON = ["timetable", "goals", "focus", "grades", "stats"]

_all = None


def all_blocks():
    """Every block, in page order."""
    global _all
    if _all is None:
        found = []
        for info in pkgutil.iter_modules(__path__):
            module = importlib.import_module(f"{__name__}.{info.name}")
            found += getattr(module, "BLOCKS", []) or ([module.BLOCK] if hasattr(module, "BLOCK") else [])
        keys = [b.key for b in found]
        dupes = {k for k in keys if keys.count(k) > 1}
        if dupes:
            raise RuntimeError(f"Two blocks share a key: {', '.join(sorted(dupes))}")
        _all = sorted(found, key=lambda b: (b.order, b.name))
    return _all


def get(key):
    return next((b for b in all_blocks() if b.key == key), None)


def chosen_keys():
    """The keys switched on, in priority order (the user's own order; Home follows it)."""
    from venato import store
    settings = store.load_settings()
    saved = settings.get("blocks")
    known = {b.key for b in all_blocks()}
    if saved is None:                      # never chose: the defaults
        return [b.key for b in all_blocks() if b.default]
    keys = [k for k in saved if k in known]
    if not settings.get("blocks_optional"):    # saved before every block could be switched off: the
        keys += [k for k in _ONCE_ALWAYS_ON if k not in keys and k in known]   # once always-on ones stay on
    return keys


def enabled():
    """The switched-on blocks, in priority order."""
    return [get(k) for k in chosen_keys()]


def is_on(key):
    return key in chosen_keys()


def save(keys):
    """Switch on exactly these blocks, in this priority order."""
    from venato import store
    known = {b.key for b in all_blocks()}
    store.save_settings(blocks=[k for k in dict.fromkeys(keys) if k in known], blocks_optional=True)


def pages():
    """{page name: page function} for the switched-on blocks, in order (their extra pages first). Blocks that
    share a page (page_name) give one entry, drawn by the first of them."""
    on = set(chosen_keys())
    out = {}
    for b in all_blocks():
        if b.key in on:
            for name, fn in b.pages.items():
                out.setdefault(name, fn)
            if b.page:
                out.setdefault(b.page_name or b.name, b.page)
    return out


def page_icon(name):
    """The Material icon of a page (its block's), or "" when no switched-on block has it."""
    for b in enabled():
        if name == (b.page_name or b.name) or name in b.pages:
            for w in b.home_widgets():
                if w.page == name and w.icon:
                    return w.icon
            return b.icon
    return ""


def widgets():
    """The Home widgets of the switched-on blocks, in priority order (a key offered twice: the first)."""
    out = {}
    for b in enabled():
        for w in b.home_widgets():
            out.setdefault(w.key, w)
    return list(out.values())


def needs():
    """Every switched-on block's "Needs you" items, as {"text", "icon", "page", "block"}."""
    out = []
    for b in enabled():
        if not b.needs:
            continue
        try:
            items = [{"text": i} if isinstance(i, str) else dict(i) for i in b.needs() or []]
        except Exception:                    # one broken block (or a malformed item) loses only its own items
            continue
        out += [{"icon": b.icon, "page": None, **i, "block": b.key} for i in items if i.get("text")]
    return out


def search_kinds():
    """{kind: (select, haystack[, order])} from the switched-on blocks."""
    out = {}
    for b in enabled():
        out.update(b.search)
    return out


def search_block(kind):
    """The switched-on block that owns this search kind, or None (a built-in kind)."""
    return next((b for b in enabled() if kind in b.search), None)


def review_sections(first, last):
    """[{key, title, lines}] from the switched-on blocks that have something to say about the week."""
    out = []
    for b in enabled():
        if b.review:
            r = b.review(first, last) or {}
            if r.get("lines"):
                out.append({"key": b.key, "title": r.get("title") or b.name, "lines": list(r["lines"])})
    return out


def schema_sql():
    return "\n".join(b.schema for b in all_blocks() if b.schema)


def migrations():
    return [b.migrate for b in all_blocks() if b.migrate]
