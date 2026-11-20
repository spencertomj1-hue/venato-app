"""
Home: a hidden grid of widgets, like a phone's home screen. Which widgets, in what order and how wide is
Home's layout (venato/home_layout.py, saved in settings.json "home"); this just draws it.

The widgets on offer: Ask (with the assistant on), Needs you, and whatever the switched-on blocks bring
(Block.widgets: today's timetable, to-dos, deadlines, goals, habits, the journal, focus, grades...).

Arrange (the button top right) lets you move them: tap a widget to pick it up and tap another to drop it
there, or use its slim bar (size − / +, ← / →, ✕ to hide). "Add widget" brings back a hidden one at the
end; Reset goes back to the default. Every change is saved straight away, with Undo. Moves and size
changes glide (components/home_flip.js).
"""

from pathlib import Path

import streamlit as st

from venato import home_layout as hl
from venato import store
from venato import undo

_flip = st.components.v2.component(
    "venato_home_flip",
    html="<span hidden></span>",
    js=(Path(__file__).parent / "components" / "home_flip.js").read_text(encoding="utf-8"),
)

# Home on one screen: tighter than the rest of the app (smaller gaps and card padding).
_COMPACT_CSS = """
.st-key-home_grid [data-testid="stVerticalBlock"] { gap: 0.45rem; }
.st-key-home_grid [data-testid="stVerticalBlock"][class*="st-key-"]:not([class*="st-key-hw"]):not(.st-key-home_habits) { padding: 0.55rem 0.8rem; }
.st-key-home_grid [class*="st-key-hwc_"] [data-testid="stHorizontalBlock"] { gap: 0.5rem; }
.st-key-home_grid .stButton button { min-height: 2rem; padding-top: 0.15rem; padding-bottom: 0.15rem; }
"""

# Out of arrange mode the Arrange button sits alone in the top-right corner: a slim row, pulled close to the
# widgets. (Not floated higher: Streamlit's own header covers the top of the page.)
_CORNER_CSS = """
.st-key-home_head { margin-top: -0.75rem; margin-bottom: -0.9rem; }
.st-key-home_head button { min-height: 2rem; padding: 0 0.25rem; }
"""


# Arrange mode: each widget gently wobbles (its content, so the box the glide measures stays still) inside a
# dashed outline; the one picked up is outlined in the accent colour. No wobble with reduced motion.
_ARRANGE_CSS = """
@keyframes venato-wobble { 0%, 100% { rotate: -0.3deg; } 50% { rotate: 0.3deg; } }
[class*="st-key-hwc_"] { animation: venato-wobble 0.45s ease-in-out infinite; transform-origin: 50% 50%; }
[data-testid="stColumn"]:nth-child(even) [class*="st-key-hwc_"] { animation-delay: -0.22s; }
@media (prefers-reduced-motion: reduce) { [class*="st-key-hwc_"] { animation: none; } }
.st-key-home_grid [class*="st-key-hw_"] { outline: 1.5px dashed rgba(128, 128, 128, 0.5); outline-offset: 4px;
    border-radius: 10px; cursor: pointer; }
.st-key-home_grid [class*="st-key-hwb_"] { gap: 0.15rem; }
.st-key-home_grid [class*="st-key-hwb_"] .stButton button { min-height: 1.9rem; padding: 0.1rem 0.45rem; }
.st-key-home_grid [class*="st-key-hwb_"] p { font-size: 0.85rem; }
"""


def _ask():
    from venato.ui import chat
    chat.render(inline=True)


def _needs_you():
    from venato.ui import goal_time
    goal_time.needs_you()


def catalog():
    """{widget key: blocks.Widget} for every widget on offer right now, in the order "Add widget" lists them."""
    from venato import blocks
    out = {}
    if store.ai_enabled():
        out["ask"] = blocks.Widget("ask", "Ask", _ask, "s")
    out["needs_you"] = blocks.Widget("needs_you", "Needs you", _needs_you, "s")
    for w in blocks.widgets():
        out.setdefault(w.key, w)
    return out


def _sizes(cat):
    return {k: w.size for k, w in cat.items()}


def _name(key, cat=None):
    w = (cat or catalog()).get(key)
    return w.name if w else key


# ---------------------------------------------------------------------------
# Arranging (button callbacks: each saves straight to settings.json, with Undo)
# ---------------------------------------------------------------------------

def _save(label, change):
    cat = catalog()
    raw = store.load_settings().get("home")
    cells = hl.normalise(raw, _sizes(cat))
    new = change(cells)
    if new != cells:
        undo.checkpoint_settings(label, home=hl.keep_unavailable(raw, new, _sizes(cat)))


def _arrange(on):
    st.session_state["home_arranging"] = on
    st.session_state["home_picked"] = None


def _pick(key):
    """Tap a widget: pick it up; tap it again: put it back; tap another: drop it there."""
    picked = st.session_state.get("home_picked")
    st.session_state["home_picked"] = None
    if picked is None:
        st.session_state["home_picked"] = key
    elif picked != key:
        _save(f"Moved {_name(picked)}", lambda c: hl.move(c, picked, key))


def _resize(key, delta):
    _save(f"Made {_name(key)} {'bigger' if delta > 0 else 'smaller'}", lambda c: hl.resize(c, key, delta))


def _step(key, delta):
    _save(f"Moved {_name(key)}", lambda c: hl.step(c, key, delta))


def _hide(key):
    if st.session_state.get("home_picked") == key:
        st.session_state["home_picked"] = None
    _save(f"Hid {_name(key)}", lambda c: hl.hide(c, key))


def _add(key):
    cat = catalog()
    _save(f"Added {_name(key, cat)}", lambda c: hl.add(c, key, cat[key].size if key in cat else "m"))


def _reset():
    if store.load_settings().get("home") != hl.default():
        undo.checkpoint_settings("Reset Home", home=hl.reset())
    st.session_state["home_picked"] = None


# ---------------------------------------------------------------------------
# Drawing
# ---------------------------------------------------------------------------

def _add_menu(cat, cells):
    """'Add widget': the hidden widgets, each put at the end."""
    hidden = hl.hidden(cells, _sizes(cat))
    with st.popover("Add widget", icon=":material/add:", disabled=not hidden,
                    help="Everything's on Home already" if not hidden else "Put a hidden widget back on Home"):
        for k in hidden:
            st.button(cat[k].name, key=f"home_add_{k}", on_click=_add, args=(k,), width="stretch")


def _header(arranging, cat, cells, labels):
    if not arranging:
        with st.container(key="home_head", horizontal=True, horizontal_alignment="right"):
            st.button("", key="home_arrange", icon=":material/dashboard_customize:", type="tertiary",
                      on_click=_arrange, args=(True,), help="Arrange Home")
        labels["home_arrange"] = "Arrange Home"
        return
    picked = st.session_state.get("home_picked")
    with st.container(key="home_head", horizontal=True, vertical_alignment="center", gap="small"):
        if picked in hl.keys(cells):
            st.markdown(f"**{cat[picked].name}** picked up. Tap where it goes, or tap it again to put it back.",
                        width="stretch")
        else:
            st.markdown("Tap a widget to pick it up, then tap where it goes.", width="stretch")
        _add_menu(cat, cells)
        st.button("Reset", key="home_reset", type="tertiary", icon=":material/restart_alt:", on_click=_reset,
                  help="Back to the starting layout")
        st.button("Done", key="home_done", type="primary", on_click=_arrange, args=(False,))


def _bar(w, cell, cells, picked, labels):
    """A widget's slim bar in arrange mode: its name and size, Move, size − / +, ← / → and ✕."""
    k, name = w.key, w.name
    size = hl.ORDER.index(cell["size"])
    with st.container(key=f"hwb_{k}", horizontal=True, vertical_alignment="center"):
        st.markdown(f"**{name}** :gray[· {hl.SIZE_NAMES[cell['size']]}]", width="stretch")
        if picked is None:
            text, icon, say = "Move", ":material/open_with:", f"Pick up {name} to move it"
        elif picked == k:
            text, icon, say = "Put back", ":material/undo:", f"Put {name} back where it was"
        else:
            text, icon, say = "Here", ":material/place_item:", f"Move {_name(picked)} here"
        st.button(text, key=f"hwpick_{k}", icon=icon, on_click=_pick, args=(k,), help=say,
                  type="primary" if picked == k else "secondary")
        labels[f"hwpick_{k}"] = say
        buttons = [("hwsm_", ":material/remove:", f"Make {name} smaller", _resize, (k, -1), size == 0),
                   ("hwbig_", ":material/add:", f"Make {name} bigger", _resize, (k, 1), size == len(hl.ORDER) - 1),
                   ("hwl_", ":material/arrow_back:", f"Move {name} back", _step, (k, -1), hl.step(cells, k, -1) == cells),
                   ("hwr_", ":material/arrow_forward:", f"Move {name} forward", _step, (k, 1), hl.step(cells, k, 1) == cells),
                   ("hwx_", ":material/close:", f"Hide {name}", _hide, (k,), False)]
        for prefix, icon, tip, fn, args, off in buttons:
            st.button("", key=prefix + k, icon=icon, on_click=fn, args=args, help=tip, type="tertiary", disabled=off)
            labels[prefix + k] = tip


def _widget(w, cell, cells, arranging, picked, labels):
    with st.container(key=f"hw_{w.key}"):            # what the glide follows (home_flip.js)
        if arranging:
            _bar(w, cell, cells, picked, labels)
        with st.container(key=f"hwc_{w.key}"):
            try:
                w.draw()
            except Exception as e:                 # one broken widget mustn't take Home down with it
                st.caption(f":material/error: {w.name} couldn't load ({type(e).__name__}).")


def _note_first_seen():
    """The day Venato was first used (existing installs: the first Home after this update). The assistant
    card in Needs you waits a week from it."""
    if not store.load_settings().get("first_seen"):
        store.save_settings(first_seen=store.local_today().isoformat())


def page_home():
    # How many times Home has been drawn in full. Busy widgets are fragments that redraw on their own, so the
    # tests use this to check that ticking a to-do didn't redraw the whole page.
    st.session_state["home_draws"] = st.session_state.get("home_draws", 0) + 1
    _note_first_seen()
    cat = catalog()
    cells = hl.normalise(store.load_settings().get("home"), _sizes(cat))
    arranging = bool(st.session_state.get("home_arranging"))
    picked = st.session_state.get("home_picked") if arranging else None
    if picked not in hl.keys(cells):              # e.g. it left Home by Undo
        picked = st.session_state["home_picked"] = None
    css = _COMPACT_CSS + ("" if arranging else _CORNER_CSS)
    if arranging:
        from venato.ui import appearance
        css += _ARRANGE_CSS
        if picked:
            css += (f".st-key-home_grid .st-key-hw_{picked} {{ outline: 2.5px solid {appearance.accent()}; "
                    "box-shadow: 0 8px 24px rgba(0, 0, 0, 0.18); }}"
                    f" .st-key-hwc_{picked} {{ animation: none; }}")
    st.html(f"<style>{css}</style>")
    labels = {}
    _header(arranging, cat, cells, labels)
    st.session_state["home_ask"] = "ask" in hl.keys(cells)       # else the chat bar is pinned below (app.py)
    if not cells:
        with st.container(border=True, key="home_empty"):
            st.markdown("**Your Home is empty.** Add a widget to start.")
            if not arranging:
                _add_menu(cat, cells)
    else:
        with st.container(key="home_grid"):
            for row in hl.pack(cells):
                for col, cell in zip(st.columns(hl.spec(row), gap="large"), row):
                    with col:
                        for k in hl.members(cell):
                            _widget(cat[k], cell, cells, arranging, picked, labels)
    with st.sidebar:
        _flip(key="home_flip", data={"arranging": arranging, "labels": labels})
