"""
The "Undo" bar: after a delete or overwrite, a small bar at the bottom of every
page says what happened, with Undo (arete/undo.py does the work).
"""

import streamlit as st

from arete import undo


def _undo():
    label = undo.restore()
    if label:
        st.toast(f"Undone: {label}", icon=":material/undo:")
    else:
        st.toast("Can't undo that any more: something else has changed since.", icon=":material/info:")


# Cmd+Z / Ctrl+Z presses Undo, but only while there's something to undo, and never while typing in a box
# or with a dialog open (then the browser's own undo, e.g. for text, works as normal).
_shortcut = st.components.v2.component(
    "arete_undo_shortcut",
    html="<span hidden></span>",
    js="""
export default function () {
  if (window.__areteUndoKey) return;
  window.__areteUndoKey = true;
  const mac = /Mac|iPhone|iPad/.test(navigator.platform || navigator.userAgent);
  window.addEventListener("keydown", (e) => {
    if (!(mac ? e.metaKey : e.ctrlKey) || e.shiftKey || e.altKey || e.key.toLowerCase() !== "z") return;
    const el = e.composedPath()[0];
    const typing = el && el.closest && (el.closest("textarea, select, [contenteditable=''], [contenteditable='true']") ||
      (el.tagName === "INPUT" && /^(text|search|email|number|password|url|tel|date|time|datetime-local|month|week)$/.test(el.type || "text")));
    if (typing) return;                        // a box you type in (not a radio button or checkbox)
    if (document.querySelector("[role=dialog]")) return;
    const button = document.querySelector(".st-key-undo_btn button");
    if (!button) return;                       // nothing to undo: leave the key alone
    e.preventDefault();
    button.click();
  });
}
""",
)


def render():
    label = undo.pending()
    if not label:
        return
    _shortcut(key="undo_shortcut")
    hidden = undo.is_quiet()       # e.g. a paste: no bar, but Cmd/Ctrl+Z still presses the (hidden) Undo
    from arete import store
    bottom = 96 if store.ai_enabled() else 24          # above the chat bar when there is one
    st.html(f"""<style>
      {".st-key-undo_bar { display: none !important; }" if hidden else ""}
      .st-key-undo_bar {{ position: fixed; left: 50%; transform: translateX(-50%); bottom: {bottom}px; z-index: 999;
        width: auto !important; max-width: min(560px, 92vw); padding: 6px 8px 6px 16px; border-radius: 12px;
        background: #26272f; box-shadow: 0 6px 24px rgba(0, 0, 0, 0.25); }}
      .st-key-undo_bar p {{ color: #f4f4f6 !important; margin: 0; }}
      .st-key-undo_bar button {{ min-height: 2rem; background: transparent !important;
        border: 1px solid rgba(255, 255, 255, 0.35) !important; color: #fff !important; }}
      .st-key-undo_bar button:hover {{ background: rgba(255, 255, 255, 0.12) !important; }}
      .st-key-undo_bar button:focus-visible {{ outline: 2px solid #fff; outline-offset: 2px; }}
      .st-key-undo_bar button * {{ color: #fff !important; }}
    </style>""")
    with st.container(key="undo_bar", horizontal=True, vertical_alignment="center", gap="small"):
        st.markdown(label)
        from arete import system
        st.button("Undo", key="undo_btn", icon=":material/undo:", on_click=_undo,
                  help=f"Or press {'⌘Z' if system.IS_MAC else 'Ctrl+Z'}")
        st.button("", key="undo_dismiss", icon=":material/close:", on_click=undo.dismiss, help="Dismiss")
