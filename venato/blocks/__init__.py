"""
Blocks: the parts of Venato you can switch on and off, like Lego.

Each block is a module in this package with a module-level BLOCK (or BLOCKS) describing it:
its sidebar page, its Home widget, its database tables, and what it gives the Claude
assistant (tools, a paragraph of instructions, a line in the [Now] snapshot, quick
commands). The setup wizard shows them as cards to tick; Settings → Blocks changes them
later and sets their order, which is also the order of the widgets on Home.

Adding a block = adding a file here; nothing else needs to know about it. (That's also how
the private copy adds its own pages without touching the shared code.)
"""

import importlib
import pkgutil
from dataclasses import dataclass, field
from typing import Callable


@dataclass
class Block:
    key: str                         # stable id, saved in settings.json
    name: str                        # its page in the sidebar
    icon: str                        # a Material icon, e.g. ":material/timer:"
    blurb: str                       # one line for the card in setup / Settings
    group: str = "Other"             # how the cards are grouped
    page: Callable | None = None     # draws its page (None: no page of its own)
    home: Callable | None = None     # draws its Home widget
    tools: list = field(default_factory=list)      # assistant tools, as in assistant.TOOL_SPECS
    prompt: str = ""                 # a paragraph for the assistant about this block
    context: Callable | None = None  # -> text for the assistant's [Now] snapshot
    quick: list = field(default_factory=list)      # quick commands: (text, day) -> tools.Result | None
    schema: str = ""                 # SQL for its tables (CREATE TABLE IF NOT EXISTS ...)
    migrate: Callable | None = None  # conn -> None: later changes to its tables
    order: int = 100                 # where its page goes in the sidebar
    default: bool = False            # on for someone who never chose (existing installs: the original pages)
    core: bool = False               # one of the built-in blocks: on for new installs and offered in setup. Extras
                                     # a copy adds stay False: they sit under "More blocks" and setup never offers them
    page_name: str = ""              # the sidebar page it shares, when not its own name (two blocks can share one page)
    search: dict = field(default_factory=dict)      # Home search: kind -> (select, haystack[, order]), as in store._SEARCH
    search_icons: dict = field(default_factory=dict)  # kind -> Material icon name for its search results
    search_open: Callable | None = None             # (result, session_state) -> None: routes a click on a result
    review: Callable | None = None   # (first, last) -> {"title": str, "lines": [str]} for the weekly review; no lines = nothing
    status: dict = field(default_factory=dict)      # word in its tools' names -> what the chat shows while one runs


GROUPS = ["Plan", "Health & body", "Study & work", "Other"]

# The blocks a new setup starts with: the core ones, bar Grades (setup adds that for students).
STARTER = ["timetable", "goals", "stats", "focus", "log"]

# What was always on before every block could be switched off. Settings saved back then keep these on.
_ONCE_ALWAYS_ON = ["timetable", "goals", "focus", "grades", "stats"]

_all = None


def all_blocks():
    """Every block, in sidebar order."""
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
    """{sidebar name: page function} for the switched-on blocks, in sidebar order. Blocks that share a
    page (page_name) give one sidebar entry, drawn by the first of them."""
    on = set(chosen_keys())
    out = {}
    for b in all_blocks():
        if b.page and b.key in on:
            out.setdefault(b.page_name or b.name, b.page)
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
