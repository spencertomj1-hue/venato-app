"""
Venato — a small local app for logging mood, sleep, energy and habits.

Run with:   streamlit run app.py
All data is stored in life.db (SQLite) next to this file.
"""

from pathlib import Path

import streamlit as st

from venato.ui import settings_ui
from venato.ui import home
from venato import blocks
from venato import store
from venato import notify
from venato.ui import chat
from venato.ui import review as review_ui
from venato.ui import timetable
from venato.store import init_db

# ---------------------------------------------------------------------------
# App entry point
# ---------------------------------------------------------------------------

st.set_page_config(page_title="Venato", page_icon=str(Path(__file__).parent / "assets" / "Logo.jpg"), layout="wide")

# All of the app's own CSS goes out first, so nothing jumps around as the page draws:
# the same top padding on every page, the sidebar nav restyled as large full-width
# items (radio circles hidden, current page with an accent bar), and no dimming of
# the previous page while a rerun is in progress.
st.html(f"""<style>
.stMainBlockContainer {{ padding-top: 2.5rem; padding-bottom: 1.5rem; padding-left: 2rem; padding-right: 2rem; }}
[data-stale="true"] {{ opacity: 1 !important; transition: none !important; }}
[data-testid="stElementContainer"]:has(#venato-ready) {{ display: none; }}   /* no stray gap */
[data-testid="stSidebar"] [data-testid="stElementContainer"]:has([data-testid="stRadio"]),
[data-testid="stSidebar"] [data-testid="stRadio"],
[data-testid="stSidebar"] [data-testid="stRadioGroup"] > div {{ width: 100% !important; }}
[data-testid="stSidebar"] [data-testid="stRadioGroup"] {{
    display: flex; flex-direction: column; align-items: stretch; gap: 6px; width: 100%;
}}
[data-testid="stSidebar"] [data-testid="stRadioOption"] {{
    box-sizing: border-box; align-self: stretch;
    width: 100%; margin: 0; padding: 14px 18px; border-radius: 10px;
    cursor: pointer; transition: background 0.12s;
}}
[data-testid="stSidebar"] [data-testid="stRadioOption"] > div {{ width: 100%; }}
[data-testid="stSidebar"] [data-testid="stRadioOption"] > div > div:first-child {{ display: none; }}
[data-testid="stSidebar"] [data-testid="stRadioOption"] p {{ font-size: 1.15rem; font-weight: 500; margin: 0; }}
[data-testid="stSidebar"] [data-testid="stRadioOption"]:hover {{ background: rgba(128, 128, 128, 0.10); }}
[data-testid="stSidebar"] [data-testid="stRadioOption"][data-selected="true"] {{
    background: rgba(128, 128, 128, 0.16);
    box-shadow: inset 3px 0 0 {st.get_option("theme.primaryColor") or "#ff4b4b"};
}}
[data-testid="stSidebar"] [data-testid="stRadioOption"][data-selected="true"] p {{ font-weight: 650; }}
</style>""")


from venato.ui import sidebar_theme          # the marble sidebar and its boxed menu
from venato.ui import appearance             # light / dark / system
appearance.sync()
appearance.apply_text_colours()
appearance.apply_text_size()
sidebar_theme.apply()


def ready_marker():
    """Tells the desktop launcher the page has finished drawing (it then swaps the splash for the app)."""
    st.html('<div id="venato-ready" style="display:none"></div>')


init_db()
notify.start()      # desktop reminders before blocks start (once per process)

# First run (or reopened from Settings): the setup wizard instead of the app.
if settings_ui.needs_wizard():
    settings_ui.wizard()
    ready_marker()
    st.stop()

# Home, then the switched-on blocks (Settings → Blocks), then Settings.
PAGES = {"Home": home.page_home, **blocks.pages(), "Settings": settings_ui.page_settings}
if st.session_state.get("page") not in PAGES:
    st.session_state["page"] = "Home"            # its block was switched off

st.sidebar.title("Venato")
# Keyed so Home's goals "See all" can switch to the Goals page.
choice = st.sidebar.radio("Go to", list(PAGES), label_visibility="collapsed", key="page")


def update_banner():
    """'Venato X is available' with a download link, when a newer release is out (venato/updates.py)."""
    from venato import updates
    new = updates.available()
    if not new:
        return
    with st.container(key="update_banner", horizontal=True, vertical_alignment="center", gap="small"):
        st.markdown(f":material/system_update: **Venato {new['version']} is available** "
                    f"(you have {updates.current_version()}).")
        st.link_button("Download", new["url"], icon=":material/download:", type="primary")
        st.button("Not now", key="update_dismiss", on_click=updates.dismiss, args=(new["version"],),
                  help="Hide this until the next version comes out")


update_banner()
review_ui.maybe_show()                         # Sunday from 7pm: the week's review pops up once
PAGES[choice]()

# The Claude chat bar, pinned to the bottom of every page (Home has it inline).
if choice != "Home" and store.ai_enabled():
    chat.render()

from venato.ui import undo_bar                # "Deleted X · Undo", after a delete or overwrite
undo_bar.render()


@st.fragment(run_every=15 * 60)
def _outlook_autosync():
    """Sync the Outlook calendar when the app opens and every 15 minutes after.
    It runs last, so the page shows the cached events straight away; the app
    reruns only if the sync actually brought new events."""
    if timetable.sync_outlook():
        st.rerun()


# The page is drawn (with the cached Outlook events), so the launcher can show it;
# the sync then runs, and only redraws if it brought something new.
ready_marker()
_outlook_autosync()
