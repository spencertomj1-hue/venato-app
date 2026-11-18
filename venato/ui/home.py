"""
Home ("Essentials"): today's timetable on the left; on the right the end-of-day prompt, the assistant box, then each
switched-on block's widget in the order of your priorities (Settings → Blocks), then search. A widget with nothing
to show draws nothing (no empty states on Home).
"""

import streamlit as st

from venato import store
from venato.ui import chat
from venato.ui import search
from venato.ui import timetable


# Home on one screen: the right-hand column tighter than the rest of the app (smaller gaps and card padding).
_COMPACT_CSS = """<style>
.st-key-home_rhs [data-testid="stVerticalBlock"] { gap: 0.45rem; }
.st-key-home_rhs [data-testid="stVerticalBlock"][class*="st-key-"]:not(.st-key-home_rhs):not(.st-key-home_habits) { padding: 0.55rem 0.8rem; }
.st-key-home_rhs [data-testid="stHorizontalBlock"] { gap: 0.5rem; }
.st-key-home_rhs .stButton button { min-height: 2rem; padding-top: 0.15rem; padding-bottom: 0.15rem; }
</style>"""


def page_home():
    """Today's Plan / Actual on the left (if the timetable is on); on the right the
    end-of-day prompt, the Ask box, then every switched-on block's widget in priority order, then search."""
    from venato import blocks
    # How many times Home has been drawn in full. Busy widgets are fragments that redraw on their own, so the
    # tests use this to check that ticking a to-do didn't redraw the whole page.
    st.session_state["home_draws"] = st.session_state.get("home_draws", 0) + 1
    widgets = [b.home for b in blocks.enabled() if b.home]
    if blocks.is_on("timetable"):
        left, right = st.columns([1, 2], gap="large")
        with left:
            timetable.render_today()
        st.html(_COMPACT_CSS)
        columns = [right.container(key="home_rhs")]
        with columns[0]:
            timetable.end_of_day_prompt()        # "Anything not go to plan today?"
    else:
        right = None
        columns = list(st.columns(2, gap="large"))
    if store.ai_enabled():
        with columns[0]:
            chat.render(inline=True)
    for i, widget in enumerate(widgets):
        with columns[i % len(columns)]:
            try:
                widget()
            except Exception as e:               # one broken widget mustn't take Home down with it
                st.caption(f":material/error: A Home widget couldn't load ({type(e).__name__}).")
    with columns[-1]:
        search.render_home()                     # search everything (bottom right)
