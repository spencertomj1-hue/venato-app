"""Getting round the app without a sidebar (venato/ui/nav.py): Home's tiles, the top bar's ← Home and shortcut
tiles, ?page= deep links, Back / Esc; and the To-dos page's tabs."""

from pathlib import Path

from streamlit.testing.v1 import AppTest

import fragment_run
from nav_helpers import goto, page_names
from venato.ui import nav

APP = str(Path(__file__).resolve().parents[1] / "app.py")


def app(page=None):
    at = AppTest.from_file(APP, default_timeout=60)
    if page is not None:
        at.query_params["page"] = page
    return at.run()


def buttons(at):
    return {b.key for b in at.button if b.key}


def test_no_sidebar_and_home_first(store):
    at = app()
    assert not at.exception and not at.sidebar.children
    assert at.session_state["page"] == "Home"
    assert page_names()[0] == "Home" and page_names()[-1] == "Settings" and "To-dos" in page_names()


def test_deep_link(store):
    at = app("goals")
    assert not at.exception and at.session_state["page"] == "Goals"
    assert app("to-dos").session_state["page"] == "To-dos"
    assert app("daily-log").session_state["page"] == "Daily Log"
    assert app("nonsense").session_state["page"] == "Home"


def test_switched_off_page_goes_home(store):
    store.save_settings(blocks=["timetable"], blocks_optional=True)
    assert app("goals").session_state["page"] == "Home"


def test_top_bar_home_and_shortcuts(store):
    at = app()
    for page in page_names()[1:]:
        goto(at, page)
        assert not at.exception, (page, at.exception)
        keys = buttons(at)
        assert "go_home" in keys
        others = {f"go_{nav.slug(p).replace('-', '_')}" for p in page_names() if p not in ("Home", page)}
        assert others <= keys, page                                       # a small tile to every other page
        assert f"go_{nav.slug(page).replace('-', '_')}" not in keys       # not to itself
    at.button(key="go_timetable").click().run()
    assert at.session_state["page"] == "Timetable"
    at.button(key="go_home").click().run()
    assert at.session_state["page"] == "Home" and at.button(key="home_arrange")


def test_every_tile_opens_its_page(store):
    from venato.ui import home
    at = app()
    tiles = {k: w.page for k, w in home.catalog().items() if w.page}
    store.save_settings(home=[{"w": k, "size": "small" if "small" in home.catalog()[k].sizes else "wide"} for k in tiles])
    at.run()
    assert tiles and not at.exception
    for k, page in tiles.items():
        goto(at, "Home")
        at.button(key=f"go_tile_{k}").click().run()
        assert not at.exception and at.session_state["page"] == page, k


def test_back_and_esc(store):
    at = app()
    goto(at, "Goals")
    fragment_run.trigger(at, "venato_nav", "go", {"slug": "timetable", "esc": False, "nonce": "a"})   # Back / Forward
    assert at.session_state["page"] == "Timetable"
    fragment_run.trigger(at, "venato_nav", "go", {"slug": "", "esc": True, "nonce": "b"})            # Esc
    assert not at.exception and at.session_state["page"] == "Home"
    assert fragment_run.component_data(at, "venato_nav")["slug"] == ""
    goto(at, "To-dos")
    assert fragment_run.component_data(at, "venato_nav")["slug"] == "to-dos"   # the address bar follows


def test_todos_page_tabs(store):
    today = store.local_today()
    store.add_todo("Buy milk", "daily", today)
    store.add_todo("Finish essay", "weekly", today)
    store.add_todo("Book dentist", "monthly", today)
    at = app("to-dos")
    assert not at.exception
    assert list(at.segmented_control(key="todos_tab").options) == ["Today", "This week", "This month", "By due date"]
    titles = lambda key: [t["title"] for s in fragment_run.component_data(at, key)["sections"] for t in s["goals"]]
    assert titles("page_todos_daily") == ["Buy milk"]
    at.segmented_control(key="todos_tab").set_value("This week").run()
    assert not at.exception and titles("page_todos_weekly") == ["Finish essay"]
    at.segmented_control(key="todos_tab").set_value("This month").run()
    assert titles("page_todos_monthly") == ["Book dentist"]
