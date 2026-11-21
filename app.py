"""
Venato — a small local app for keeping a journal, habits, goals and a timetable.

Run with:   streamlit run app.py
All data is stored in life.db (SQLite) next to this file.
"""

from pathlib import Path

import streamlit as st

from venato.ui import settings_ui
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

st.set_page_config(page_title="Venato", page_icon=str(Path(__file__).parent / "assets" / "Logo.jpg"), layout="wide",
                   initial_sidebar_state="collapsed")

# All of the app's own CSS goes out first, so nothing jumps around as the page draws: the same top padding on
# every page, no sidebar (Home is the way round the app: venato/ui/nav.py), and no dimming of the previous
# page while a rerun is in progress.
st.html("""<style>
.stMainBlockContainer { padding-top: 2.5rem; padding-bottom: 1.5rem; padding-left: 2rem; padding-right: 2rem; }
@media (max-width: 640px) { .stMainBlockContainer { padding-left: 1rem; padding-right: 1rem; } }
[data-stale="true"] { opacity: 1 !important; transition: none !important; }
[data-testid="stElementContainer"]:has(#venato-ready) { display: none; }   /* no stray gap */
</style>""")


from venato.ui import appearance             # light / dark / system
appearance.sync()
appearance.apply_text_colours()
appearance.apply_text_size()
from venato.ui import paper                  # serif headings; in light mode the paper background and buttons
paper.apply()
from venato.ui import nav                    # Home, the top bar on every other page, ?page= and Esc
st.html(f"<style>{nav.css(appearance.tokens())}</style>")


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

# Home, then the switched-on blocks' pages, then Settings. Home's tiles open them; nav.go switches.
PAGES = nav.pages()
choice = nav.current(PAGES)
if st.session_state.get("last_page") == "Modules" and choice != "Modules":
    st.session_state.pop("gr_module", None)       # leaving Modules: coming back shows the list, not the last module
if choice != "Home":
    st.session_state["home_arranging"] = False
st.session_state["last_page"] = choice
from venato.ui import page_fade                   # fades between pages instead of swapping bits in front of you
page_fade.render()


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
labels = {} if choice == "Home" else nav.top_bar(choice, PAGES)
PAGES[choice]()

# The Claude chat bar, pinned to the bottom of every page (Home has it inline, when its Ask widget is on).
if store.ai_enabled() and not (choice == "Home" and st.session_state.get("home_ask")):
    chat.render()

from venato.ui import undo_bar                # "Deleted X · Undo", after a delete or overwrite
undo_bar.render()
nav.mount(choice, labels)


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
