"""
Getting round the app without a sidebar. Home is the only way in: each tile opens its page, and every page
has a top bar with "← Home" (Esc does the same) and small shortcut tiles to the other pages. Settings is the
gear on Home.

The router is st.session_state["page"] (a page name; "Home" when missing). It's mirrored in the address bar
as ?page=<slug>, so a link straight to a page works and the browser's back button goes back a page:
a hidden component (below) pushes a history entry when the page changes and, on back / forward or Esc,
sends the page it wants back to Python.
"""

import re
import uuid

import streamlit as st

HOME, SETTINGS = "Home", "Settings"
KEY = "page"

# Shortcut colours (the tiles' icon squares), by page.
COLOURS = {"Timetable": "#0B4F9C", "To-dos": "#C62828", "Goals": "#146C2E", "Focus": "#44444C", "Modules": "#6B3FA0",
           "Daily Log": "#B45309", "Review": "#8E1C1C", SETTINGS: "#5F6170"}
ICONS = {HOME: ":material/home:", SETTINGS: ":material/settings:", "To-dos": ":material/check:"}

_JS = """
export default function ({ data, setTriggerValue }) {
  const w = window;
  w.__venatoNav = data;
  w.__venatoNavSend = (slug, esc) => setTriggerValue("go", { slug, esc: !!esc, nonce: Math.random().toString(36).slice(2) });
  const here = () => new URLSearchParams(location.search).get("page") || "";
  // The address bar follows the page (a new history entry, so Back works), unless Back itself brought us here.
  if (here() !== data.slug) {
    const u = new URL(location.href);
    if (data.slug) u.searchParams.set("page", data.slug); else u.searchParams.delete("page");
    if (w.__venatoNavPopped) history.replaceState(history.state, "", u); else history.pushState({ venato: data.slug }, "", u);
  }
  w.__venatoNavPopped = false;
  if (w.__venatoFocusTop) { w.__venatoFocusTop = false; landWhenDrawn(); }
  // Spoken names for icon-only buttons ({button key: name}).
  for (const [k, name] of Object.entries(data.labels || {}))
    for (const b of document.querySelectorAll(`.st-key-${CSS.escape(k)} button`)) b.setAttribute("aria-label", name);
  if (w.__venatoNavInit) return;
  w.__venatoNavInit = true;
  addEventListener("popstate", () => {
    if (here() === (w.__venatoNav || {}).slug) return;
    w.__venatoNavPopped = true;
    leave(here());
  });
  // Esc: back to Home (or out of Edit Home), unless something else wants it (a dialog, a menu, typing).
  document.addEventListener("keydown", (e) => {
    if (e.key !== "Escape" || e.defaultPrevented || e.isComposing) return;
    const nav = w.__venatoNav || {};
    if (!nav.slug && !nav.editing) return;
    const t = e.composedPath()[0];
    if (t instanceof Element && t.closest('input, textarea, select, [contenteditable="true"]')) return;
    if (document.querySelector('[data-testid="stDialog"], [role="dialog"], [data-baseweb="popover"]')) return;
    leave("", true);
  });
}

// Esc and Back change page from the keyboard / browser, not a page button: fade like a button does
// (page_fade.py), and once the new page is drawn put focus on its heading. Otherwise focus stays on the
// element it was on (the page itself, or a button that's gone), and the key press just made that a
// keyboard focus, which Safari rings in grey. The heading takes focus without a ring; Tab goes on from there.
function leave(slug, esc) {
  const w = window;
  if (slug !== (w.__venatoNav || {}).slug && w.__venatoFadeShow) w.__venatoFadeShow();
  w.__venatoFocusTop = true;
  w.__venatoNavSend(slug, esc);
}

function landWhenDrawn() {
  const app = () => document.querySelector('[data-testid="stApp"]');
  const busy = () => { const s = app()?.getAttribute("data-test-script-state") || ""; return /running|rerun/i.test(s) && !/not/i.test(s); };
  let tries = 0;
  const go = () => {
    if (busy() && ++tries < 60) { setTimeout(go, 50); return; }
    const h = document.querySelector('[data-testid="stMain"] h1, [data-testid="stMain"] h2');
    const was = document.activeElement;
    if (h) {
      h.setAttribute("tabindex", "-1");
      h.classList.add("venato-landing");
      h.focus({ preventScroll: true });
    } else if (was && was !== document.body && was.blur) was.blur();
  };
  requestAnimationFrame(go);
}
"""

_nav = st.components.v2.component("venato_nav", html="<span hidden></span>", js=_JS)


def slug(name):
    return "" if name == HOME else re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")


def from_slug(value, names):
    """The page a ?page= value means, or None."""
    value = (value or "").strip().lower()
    if not value:
        return HOME
    return next((n for n in names if slug(n) == value), None)


def pages():
    """{page name: draws it}: Home, the switched-on blocks' pages, Settings."""
    from venato import blocks
    from venato.ui import home, settings_ui
    return {HOME: home.page_home, **blocks.pages(), SETTINGS: settings_ui.page_settings}


def go(name):
    """Button callback: open a page."""
    st.session_state[KEY] = name
    st.session_state.pop("home_arranging", None)
    st.session_state.pop("home_picked", None)


def current(all_pages):
    """The page to draw: the session's, else (a fresh session) the address bar's, else Home; a page whose
    block was switched off goes Home."""
    ss = st.session_state
    if KEY not in ss:
        ss[KEY] = from_slug(st.query_params.get("page"), list(all_pages)) or HOME
    if ss[KEY] not in all_pages:
        ss[KEY] = HOME
    return ss[KEY]


def _on_go():
    value = (st.session_state.get("venato_nav") or {}).get("go") or {}
    ss = st.session_state
    if value.get("esc") and ss.get(KEY, HOME) == HOME:
        ss["home_arranging"] = False            # Esc on Home: out of Edit Home
        ss["home_picked"] = None
        return
    target = from_slug(value.get("slug"), list(pages()))
    if target:
        go(target)


def icon_md(icon, colour, cls="vn-tile-icon"):
    """A coloured square with a white icon in it, as markdown for st.markdown(..., unsafe_allow_html=True)
    (st.html strips SVG; markdown turns :material/x: into the icon, inside the span too)."""
    from html import escape
    return f'<span class="{cls}" style="background:{escape(colour or "#5F6170")}" aria-hidden="true">{icon or ""}</span>'


def mount(page, labels=None):
    """The hidden router component (address bar, Back, Esc). Drawn once per page, last."""
    with st.container(key="venato_hidden"):
        _nav(key="venato_nav", on_go_change=_on_go,
             data={"slug": slug(page), "editing": bool(st.session_state.get("home_arranging")),
                   "labels": labels or {}, "run": uuid.uuid4().hex[:6]})


def top_bar(page, all_pages):
    """A page's top bar: ← Home, the Esc hint, and small tiles to jump to the other pages. Returns
    {button key: spoken name} for the icon-only ones."""
    from venato import blocks
    labels, css = {}, []
    with st.container(key="nav_top", horizontal=True, vertical_alignment="center", gap="small"):
        st.button("Home", key="go_home", icon=":material/arrow_back:", on_click=go, args=(HOME,),
                  help="Back to Home (Esc)")
        st.caption("Esc also goes back", width="stretch")
        for name in all_pages:
            if name in (HOME, page):
                continue
            key = f"go_{slug(name).replace('-', '_')}"
            icon = ICONS.get(name) or blocks.page_icon(name) or ":material/apps:"
            st.button("", key=key, icon=icon, on_click=go, args=(name,), help=name, type="primary")
            labels[key] = f"Open {name}"
            css.append(f".stApp .st-key-{key} button {{ background: {COLOURS.get(name, '#5F6170')} !important; "
                       f"border-color: transparent !important; }}")
    st.html(f"<style>{''.join(css)}</style>")
    return labels


# The look of the top bar and of every page without the sidebar. Colours come from appearance.tokens().
def css(t):
    return f"""
    [data-testid="stSidebar"], [data-testid="stSidebarCollapsedControl"], [data-testid="stExpandSidebarButton"],
    [data-testid="stSidebarCollapseButton"] {{ display: none !important; }}
    .st-key-venato_hidden {{ display: none !important; }}
    .st-key-nav_top {{ margin: -0.75rem 0 0.75rem; }}
    .st-key-nav_top button {{ min-height: 44px; min-width: 44px; border-radius: 12px; }}
    .stApp .st-key-go_home button {{ background: {t['card']} !important; border: 1px solid {t['border']} !important;
        color: {t['ink']} !important; padding: 0 16px 0 10px; }}
    .st-key-nav_top [class*="st-key-go_"]:not(.st-key-go_home) button {{ width: 44px; padding: 0; }}
    .st-key-nav_top [class*="st-key-go_"]:not(.st-key-go_home) button * {{ color: #fff !important; }}
    .vn-page-icon {{ display: inline-flex; width: 64px; height: 64px; border-radius: 18px; align-items: center;
        justify-content: center; font-size: 36px; }}
    .vn-page-icon span {{ color: #fff !important; }}
    """
