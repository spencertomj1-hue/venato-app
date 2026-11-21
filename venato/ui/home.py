"""
Home: the whole app on one screen, and the only way round it. A grid of tiles (four columns; each tile
Small, Wide, Large, Tall or Column, 1 × 3, which the Timetable starts in): a card header with the module's coloured icon, its name and a short status
("1 of 4 done today", "2 behind"), then a live preview. Clicking a tile anywhere that isn't one of its own
controls opens its module's page (ticking a to-do or starting Focus works in place). Which tiles, in what
order and size is Home's layout (venato/home_layout.py, saved in settings.json "home").

On a laptop-sized window (over 1000px wide) Home is one screen: the rows share the height under the header
(home_flip.js measures it) and each tile shows a summary, clipping rather than growing; its page has the rest.
Needs you has no page: a tap on it opens everything in a dialog. Narrower windows scroll.

Above the grid: the date, the search / Ask bar, Edit Home, and the Settings gear (always there, so you can't
remove your way out of the app).

Edit Home: the tiles wobble; drag one and the others make room as you go, so it lands wherever you let go
(components/home_flip.js). − takes a tile off Home (its data stays), the size button steps through the sizes
it comes in, and the "Add a tile" panel lists what's hidden. Every change is saved straight away (no Undo bar;
Cmd/Ctrl+Z still undoes the last one); Reset goes back to the start. Moves glide, not with reduced motion.
"""

from html import escape
from pathlib import Path

import streamlit as st

from venato import home_layout as hl
from venato import store
from venato import undo
from venato.ui import nav

_flip = st.components.v2.component(
    "venato_home_flip",
    html="<span hidden></span>",
    js=(Path(__file__).parent / "components" / "home_flip.js").read_text(encoding="utf-8"),
)


def _ask():
    from venato.ui import chat
    chat.render(inline=True)


def _needs_you():
    from venato.ui import goal_time
    goal_time.needs_you(limit=goal_time.TILE_LIMIT)


@st.dialog("Needs you", width="large")
def _needs_you_all():
    from venato.ui import goal_time
    goal_time.needs_you(heading=False)                # the dialog's title says it


# Tiles without a page: what their header (and a tap anywhere on them) opens instead.
_OPENS = {"needs_you": _needs_you_all}


def _open(key):
    """Button callback: show the tile's dialog in this run (page_home opens it)."""
    st.session_state["home_dialog"] = key


def _needs_status():
    from venato import tile_status
    return tile_status.needs_you()


def catalog():
    """{tile key: blocks.Widget} for every tile on offer right now, in the order "Add a tile" lists them."""
    from venato import blocks
    out = {}
    for w in blocks.widgets():
        out.setdefault(w.key, w)
    out.setdefault("needs_you", blocks.Widget("needs_you", "Needs you", _needs_you, "wide", ("wide", "large", "tall"),
                                              page=None, status=_needs_status, icon=":material/notifications:",
                                              colour="#0B4F9C"))
    if store.ai_enabled():
        out.setdefault("ask", blocks.Widget("ask", "Ask Claude", _ask, "wide", ("wide", "large", "tall"), page=None,
                                            icon=":material/chat:", colour="#2B2B30"))
    return out


def _defaults(cat):
    return {k: w.size for k, w in cat.items()}


def _supported(cat):
    return {k: tuple(w.sizes) for k, w in cat.items()}


def _cells(cat):
    return hl.normalise(store.load_settings().get("home"), _defaults(cat), _supported(cat))


def _name(key, cat=None):
    w = (cat or catalog()).get(key)
    return w.name if w else key


# ---------------------------------------------------------------------------
# Editing (callbacks: each saves straight to settings.json; quiet, so no Undo bar, but Cmd/Ctrl+Z works)
# ---------------------------------------------------------------------------

def _save(label, change):
    cat = catalog()
    raw = store.load_settings().get("home")
    cells = hl.normalise(raw, _defaults(cat), _supported(cat))
    new = change(cells)
    if new != cells:
        undo.checkpoint_settings(label, quiet=True, home=hl.keep_unavailable(raw, new, _defaults(cat)))


def _edit(on):
    st.session_state["home_arranging"] = on


def _on_drag():
    """A tile dragged to a new place (home_flip.js sends the order the grid showed when it was let go)."""
    order = (st.session_state.get("home_flip") or {}).get("drop") or {}
    order = order.get("order") if isinstance(order, dict) else None
    if isinstance(order, list):
        _save("Moved a tile", lambda c: hl.reorder(c, order))


def _cycle(key):
    """The size button: the next size this tile comes in."""
    cat = catalog()
    sizes = [s for s in hl.ORDER if s in (cat[key].sizes if key in cat else hl.ORDER)]
    now = next((c["size"] for c in _cells(cat) if c["w"] == key), None)
    if len(sizes) > 1 and now:
        nxt = sizes[(sizes.index(now) + 1) % len(sizes)] if now in sizes else sizes[0]
        _save(f"Made {_name(key, cat)} {hl.SIZE_NAMES[nxt].lower()}", lambda c: hl.resize(c, key, nxt))


def _hide(key):
    _save(f"Removed {_name(key)} from Home", lambda c: hl.hide(c, key))


def _add(key):
    cat = catalog()
    _save(f"Added {_name(key, cat)}", lambda c: hl.add(c, key, cat[key].size if key in cat else "wide"))


def _reset():
    if store.load_settings().get("home") != hl.default():
        undo.checkpoint_settings("Reset Home", quiet=True, home=hl.reset())


# ---------------------------------------------------------------------------
# Look
# ---------------------------------------------------------------------------

# Room the page keeps below the grid (px): the pinned chat bar when it's on, else the page's own bottom padding.
CHAT_ROOM, PAGE_ROOM = 96, 20
GAP = 12               # px between tiles
MIN_ROW = 108          # px: rows never get shorter than this (a very short window scrolls instead); 108 fits
                       # a 4-row Home (a student's, with Modules) at 1280x720


def _css(t, cells, cat, editing, room=PAGE_ROOM):
    rows = max(1, hl.rows(cells))
    out = [f"""
    .st-key-home_head h1 {{ font-size: 2.1rem; margin: 0; padding: 0; line-height: 1.2; }}
    .st-key-home_head h1:focus, .st-key-home_head h1:focus-visible {{ outline: none !important; }}
    .st-key-home_head [data-testid="stHeading"] [data-testid="stMarkdownContainer"] {{ margin-bottom: 2px; }}
    .st-key-home_head button, .st-key-home_head input {{ min-height: 44px; }}
    .st-key-home_head [data-testid="stTextInputRootElement"] {{ border-radius: 12px; min-height: 44px; }}
    .st-key-home_settings button {{ width: 44px; padding: 0; }}
    /* On a laptop-sized window Home is one screen: the rows share the height left under the header (home_flip.js
       measures it into --home-grid-h; the calc is the first guess) and tiles clip instead of growing. Narrower
       windows (two columns, or one on a phone) scroll, each tile as tall as its summary. */
    .st-key-home_grid {{ display: grid !important; grid-template-columns: repeat({hl.COLUMNS}, minmax(0, 1fr));
        grid-auto-rows: minmax(150px, auto); grid-auto-flow: dense; gap: {GAP}px; }}
    @media (min-width: 1001px) {{
        .stMain .stMainBlockContainer:has(.st-key-home_grid) {{ padding-bottom: {room}px; }}
        .stMain .st-key-home_grid {{
            --home-row: calc((max({rows * MIN_ROW + (rows - 1) * GAP}px, var(--home-grid-h, calc(100dvh - 140px - {room}px)))
                - {(rows - 1) * GAP}px) / {rows});
            grid-template-rows: repeat({rows}, var(--home-row)); flex: none; }}
        .st-key-home_grid [class*="st-key-hw_"] {{ overflow: hidden; }}
        .st-key-home_grid [class*="st-key-hw_"] > [data-testid="stLayoutWrapper"]:has(> [class*="st-key-hwc_"]) {{
            flex: 1 1 0; min-height: 0; overflow: hidden; }} }}
    .st-key-home_grid > div {{ height: 100%; min-width: 0; min-height: 0; }}
    .st-key-home_grid [class*="st-key-hw_"] {{ height: 100%; box-sizing: border-box;
        background: {t['card']}; border: 1px solid {t['border']}; border-radius: 20px; padding: 4px 16px 12px;
        position: relative; gap: 0.35rem; min-width: 0; flex-wrap: nowrap; }}
    .st-key-home_grid [class*="st-key-hw_"]:has([class*="st-key-go_tile_"], [class*="st-key-open_tile_"]) {{ cursor: pointer; }}
    .st-key-home_grid [class*="st-key-hwc_"] {{ min-height: 0; overflow: hidden; gap: 0.4rem; }}
    /* A tile's own title is its header: the preview doesn't repeat it, and its card-in-a-card goes. */
    [class*="st-key-hwc_"] [data-testid="stElementContainer"]:has(.vn-subhead) {{ display: none; }}
    [class*="st-key-hwc_"] [data-testid="stVerticalBlock"][class*="st-key-"] {{ border: 0 !important; padding: 0 !important;
        background: transparent !important; box-shadow: none !important; }}
    [class*="st-key-hwh_"], [class*="st-key-hwbar_"] {{ gap: 0.5rem; flex-wrap: nowrap; }}
    [class*="st-key-hwt_"] {{ min-width: 0; overflow: hidden; }}
    [class*="st-key-hwt_"] p {{ white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }}
    [class*="st-key-hwh_"] [data-testid="stCaptionContainer"] p {{ text-align: right; white-space: nowrap; }}
    [class*="st-key-hwh_"] [data-testid="stCaptionContainer"] {{ overflow: hidden; text-overflow: ellipsis; }}
    /* The timetable's sync and Outlook buttons sit at the right of its title line (timetable_component.css). */
    .st-key-hwh_timetable_today {{ padding-right: 66px; box-sizing: border-box; }}
    .st-key-hwh_timetable_today [data-testid="stElementContainer"]:has([data-testid="stCaptionContainer"]) {{ min-width: 0; flex-shrink: 1; }}
    .st-key-hwh_timetable_today [data-testid="stCaptionContainer"] p {{ overflow: hidden; text-overflow: ellipsis; }}
    .st-key-hwc_timetable_today .st-key-timetable_today {{ position: static; }}    /* so they place by the tile */
    .st-key-hwh_timetable_today [class*="st-key-hwt_"], .st-key-hwh_timetable_today [class*="st-key-go_tile_"],
    .st-key-hwh_timetable_today [class*="st-key-open_tile_"] {{ min-width: max-content; }}   /* the status gives way, not the name */
    [class*="st-key-go_tile_"] button, [class*="st-key-open_tile_"] button, [class*="st-key-hwt_"] p {{ min-height: 44px;
        padding: 0 !important; justify-content: flex-start; gap: 10px; }}
    [class*="st-key-go_tile_"] button > div, [class*="st-key-open_tile_"] button > div {{ justify-content: flex-start !important; gap: 10px; }}
    /* The tile's header already opens the page: the preview's own "See all" / "Manage" go. */
    [class*="st-key-hwc_"] .st-key-home_goals_all, [class*="st-key-hwc_"] .st-key-home_habits_manage,
    [class*="st-key-hwc_"] .st-key-home_journal_write, [class*="st-key-hwc_"] .st-key-home_deadlines_all {{ display: none; }}
    [class*="st-key-go_tile_"] button p, [class*="st-key-open_tile_"] button p, [class*="st-key-hwt_"] p {{
        font-size: 1.1rem; font-weight: 600 !important; color: {t['ink']} !important; white-space: nowrap; }}
    [class*="st-key-go_tile_"] button:hover p, [class*="st-key-open_tile_"] button:hover p {{ text-decoration: underline; }}
    [class*="st-key-go_tile_"] [data-testid="stIconMaterial"], [class*="st-key-open_tile_"] [data-testid="stIconMaterial"] {{
        color: #fff !important; border-radius: 8px;
        width: 30px; height: 30px; display: inline-flex; align-items: center; justify-content: center; font-size: 19px; }}
    .vn-tile-icon {{ display: inline-flex; width: 30px; height: 30px; border-radius: 8px; vertical-align: middle;
        margin-right: 10px; align-items: center; justify-content: center; color: #fff; font-size: 19px; }}
    .vn-tile-icon span {{ color: #fff !important; }}
    /* Needs you's summary: its lines close together. */
    .st-key-home_needs_you, .st-key-home_needs_you [data-testid="stVerticalBlock"] {{ gap: 0.3rem; }}
    .st-key-home_needs_you [data-testid="stMarkdownContainer"] p {{ white-space: nowrap; overflow: hidden;
        text-overflow: ellipsis; }}
    @media (max-width: 1000px) {{ .st-key-home_grid {{ grid-template-columns: repeat(2, minmax(0, 1fr)); }} }}
    @media (max-width: 640px) {{
        .st-key-home_grid {{ grid-template-columns: minmax(0, 1fr); }}
        .st-key-home_grid > div {{ grid-column: 1 / -1 !important; grid-row: auto !important; }}
        .st-key-home_head h1 {{ font-size: 1.6rem; }} }}
    .st-key-home_hidden {{ display: none !important; }}
    .st-key-home_add_panel {{ background: {t['card']}; border: 1px solid {t['border']}; border-radius: 20px;
        padding: 20px 18px; gap: 0.75rem; }}
    [class*="st-key-hadd_"] {{ flex-wrap: nowrap !important; border: 1px solid {t['border']}; border-radius: 16px; padding: 10px 12px; }}
    [class*="st-key-home_add_"]:not(.st-key-home_add_panel):not(.st-key-home_add_prompt) button {{
        width: 44px; height: 44px; border-radius: 22px; padding: 0; }}
    .st-key-home_add_note {{ background: {t['paper']}; border-radius: 14px; padding: 12px 14px; }}
    .st-key-home_empty {{ background: {t['card']}; border: 1px dashed {t['border']}; border-radius: 24px; padding: 28px; }}
    """]
    for c in cells:
        k, (w, h) = c["w"], hl.span(c["size"])
        out.append(f".st-key-home_grid > div:has(> .st-key-hw_{k}) {{ grid-column: span {w}; grid-row: span {h}; }}")
        colour = getattr(cat.get(k), "colour", "") or "#5F6170"
        out.append(f".st-key-go_tile_{k} [data-testid='stIconMaterial'], .st-key-open_tile_{k} [data-testid='stIconMaterial'] "
                   f"{{ background: {colour}; }}")
    if editing:
        out.append(f"""
        @keyframes venato-wobble {{ 0%, 100% {{ rotate: -0.3deg; }} 50% {{ rotate: 0.3deg; }} }}
        [class*="st-key-hwc_"] {{ animation: venato-wobble 0.45s ease-in-out infinite; transform-origin: 50% 50%; }}
        .st-key-home_grid > div:nth-child(even) [class*="st-key-hwc_"] {{ animation-delay: -0.22s; }}
        @media (prefers-reduced-motion: reduce) {{ [class*="st-key-hwc_"] {{ animation: none; }} }}
        .st-key-home_grid [class*="st-key-hw_"] {{ border: 1.5px dashed {t['muted']}; cursor: grab;
            touch-action: none; user-select: none; -webkit-user-select: none; }}
        .st-key-home_grid [class*="st-key-hw_"][class] {{ overflow: visible; }}
        .st-key-home_grid [class*="st-key-hwc_"] {{ pointer-events: none; }}
        [class*="st-key-hwx_"] {{ position: absolute !important; top: -14px; left: -14px; z-index: 4; width: auto !important; }}
        .stApp [class*="st-key-hwx_"] button {{ width: 44px; height: 44px; border-radius: 22px; padding: 0;
            background: #5F6170 !important; border: 2px solid {t['card']} !important; }}
        [class*="st-key-hwx_"] button * {{ color: #fff !important; }}
        [class*="st-key-hwbar_"] button {{ min-height: 44px; min-width: 44px; padding: 0; }}
        [class*="st-key-hwbar_"] {{ padding-left: 22px; }}           /* clear of the − in the corner */
        /* the tile in your hand: lifted, over the rest, following the pointer (no wobble, no glide) */
        .st-key-home_grid .vn-dragging {{ z-index: 30; cursor: grabbing; animation: none;
            box-shadow: 0 22px 48px rgba(0, 0, 0, 0.22); border-style: solid; border-color: {t['accent']}; }}
        .st-key-home_grid .vn-dragging [class*="st-key-hwc_"] {{ animation: none; }}
        html.vn-drag-on, html.vn-drag-on * {{ cursor: grabbing !important; }}
        """)
    return "".join(out)


# ---------------------------------------------------------------------------
# Drawing
# ---------------------------------------------------------------------------

def _icon_html(w):
    """The tile's coloured icon square, for st.markdown (which turns :material/x: into the icon)."""
    return nav.icon_md(w.icon, w.colour)


def _status(w):
    if not w.status:
        return ""
    try:
        return w.status() or ""
    except Exception:                       # a status is a nicety: never take the tile down with it
        return ""


def _header(editing, cells, labels):
    """The date (or "Edit Home"), the search / Ask bar, Edit Home or Reset / Done, and the Settings gear."""
    from venato import regional
    with st.container(key="home_head", horizontal=True, vertical_alignment="center", gap="small"):
        with st.container(gap=None, width="stretch"):
            if editing:
                st.title("Edit Home", anchor=False)
                st.caption("Drag a tile to move it · ⤢ changes its size · − removes it. Saved as you go.")
            else:
                st.title(regional.long_date(store.local_today()), anchor=False)
        if not editing:
            from venato.ui import search
            search.box()
            st.button("Edit Home", key="home_arrange", icon=":material/dashboard_customize:", on_click=_edit,
                      args=(True,), help="Move, resize, remove and add tiles")
        else:
            st.button("Reset", key="home_reset", icon=":material/restart_alt:", on_click=_reset,
                      help="Back to the starting layout")
            st.button("Done", key="home_done", type="primary", on_click=_edit, args=(False,))
        st.button("", key="home_settings", icon=":material/settings:", type="tertiary", on_click=nav.go,
                  args=(nav.SETTINGS,), help="Settings")
        labels["home_settings"] = "Settings"


def _tile_head(w, labels):
    status = _status(w)
    with st.container(key=f"hwh_{w.key}", horizontal=True, vertical_alignment="center"):
        if w.page:
            st.button(w.name, key=f"go_tile_{w.key}", icon=w.icon or None, type="tertiary", on_click=nav.go,
                      args=(w.page,), help=f"Open {w.page}", width="stretch")
            labels[f"go_tile_{w.key}"] = f"Open {w.page}" + (f": {status}" if status else "")
        elif w.key in _OPENS:                      # no page of its own: the tile opens everything in a dialog
            st.button(w.name, key=f"open_tile_{w.key}", icon=w.icon or None, type="tertiary", on_click=_open,
                      args=(w.key,), help=f"See all of {w.name}", width="stretch")
            labels[f"open_tile_{w.key}"] = f"See all of {w.name}" + (f": {status}" if status else "")
        else:
            with st.container(key=f"hwt_{w.key}", width="stretch"):
                st.markdown(f'{_icon_html(w)}**{escape(w.name)}**', unsafe_allow_html=True)
        if status:
            st.caption(escape(status), width="content")


def _edit_bar(w, cell, labels):
    """In Edit Home: − to remove, the title, and a size button (steps through the sizes the tile comes in)."""
    k, name = w.key, w.name
    st.button("", key=f"hwx_{k}", icon=":material/remove:", on_click=_hide, args=(k,), help=f"Remove {name}")
    labels[f"hwx_{k}"] = f"Remove {name} from Home"
    with st.container(key=f"hwbar_{k}", horizontal=True, vertical_alignment="center", gap="small"):
        with st.container(key=f"hwt_{k}", width="stretch"):              # the title, on the same line
            st.markdown(f'{_icon_html(w)}**{escape(name)}**', unsafe_allow_html=True)
        if len([s for s in hl.ORDER if s in w.sizes]) > 1:
            size = hl.SIZE_NAMES.get(cell["size"], cell["size"])
            st.button("", key=f"hwsz_{k}", icon=":material/aspect_ratio:", on_click=_cycle, args=(k,),
                      help=f"{name} is {size.lower()}: tap for the next size")
            labels[f"hwsz_{k}"] = f"{name} is {size.lower()}. Change size"


def _tile(w, cell, editing, labels):
    with st.container(key=f"hw_{w.key}"):            # what the glide follows (home_flip.js)
        if editing:
            _edit_bar(w, cell, labels)                       # −, its title and its size
        else:
            _tile_head(w, labels)
        with st.container(key=f"hwc_{w.key}"):
            try:
                w.draw()
            except Exception as e:                 # one broken tile mustn't take Home down with it
                st.caption(f":material/error: {w.name} couldn't load ({type(e).__name__}).")


def _add_panel(cat, cells, labels):
    """Edit Home's side panel: the hidden tiles, each with the sizes it comes in and +."""
    hidden = hl.hidden(cells, _defaults(cat))
    with st.container(key="home_add_panel"):
        st.subheader("Add a tile", anchor=False)
        st.caption("Hidden modules stay one tap away. Removing a tile never deletes its data.")
        if not hidden:
            st.caption("Everything's on Home already.")
        for k in hidden:
            w = cat[k]
            with st.container(key=f"hadd_{k}", horizontal=True, vertical_alignment="center", gap="small"):
                st.markdown(_icon_html(w), unsafe_allow_html=True, width="content")
                with st.container(gap=None, width="stretch"):
                    st.markdown(f"**{escape(w.name)}**")
                    st.caption(" · ".join(hl.SIZE_NAMES[s] for s in hl.ORDER if s in w.sizes))
                st.button("", key=f"home_add_{k}", icon=":material/add:", type="primary", on_click=_add, args=(k,),
                          help=f"Add {w.name} to Home")
                labels[f"home_add_{k}"] = f"Add {w.name}"
        with st.container(key="home_add_note"):
            st.caption("Settings is always the gear top right, so you can't remove your way out of the app.")


def _empty():
    with st.container(key="home_empty"):
        st.markdown("**Your Home is empty.** Add a tile to start; everything you had is still there.")
        st.button("Add a tile", key="home_add_prompt", icon=":material/add:", type="primary", on_click=_edit,
                  args=(True,))


def _note_first_seen():
    """The day Venato was first used (existing installs: the first Home after this update). The assistant
    card in Needs you waits a week from it."""
    if not store.load_settings().get("first_seen"):
        store.save_settings(first_seen=store.local_today().isoformat())


def page_home():
    # How many times Home has been drawn in full. Busy tiles are fragments that redraw on their own, so the
    # tests use this to check that ticking a to-do didn't redraw the whole page.
    st.session_state["home_draws"] = st.session_state.get("home_draws", 0) + 1
    _note_first_seen()
    from venato.ui import appearance
    cat = catalog()
    cells = _cells(cat)
    editing = bool(st.session_state.get("home_arranging"))
    chat_bar = store.ai_enabled() and "ask" not in hl.keys(cells)      # app.py pins it to the bottom
    st.html(f"<style>{_css(appearance.tokens(), cells, cat, editing, CHAT_ROOM if chat_bar else PAGE_ROOM)}</style>")
    labels = {}
    _header(editing, cells, labels)
    if not editing:
        from venato.ui import search
        search.results()
    st.session_state["home_ask"] = "ask" in hl.keys(cells)       # else the chat bar is pinned below (app.py)
    main, side = st.columns([3, 1], gap="large") if editing else (st.container(), None)
    with main:
        if not cells:
            _empty()
        else:
            with st.container(key="home_grid"):
                for cell in cells:
                    _tile(cat[cell["w"]], cell, editing, labels)
    if side is not None:
        with side:
            _add_panel(cat, cells, labels)
    with st.container(key="home_hidden"):
        _flip(key="home_flip", data={"arranging": editing, "labels": labels,
                                     "room": CHAT_ROOM if chat_bar else PAGE_ROOM}, on_drop_change=_on_drag)
    dialog = st.session_state.pop("home_dialog", None)
    if dialog in _OPENS and not editing and dialog in hl.keys(cells):
        _OPENS[dialog]()
