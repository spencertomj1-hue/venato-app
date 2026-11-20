"""Search everything: what it finds, and Open going to the right place (the search box at the top of the sidebar)."""

from pathlib import Path

from streamlit.testing.v1 import AppTest

APP = str(Path(__file__).resolve().parents[1] / "app.py")


def seed(store):
    from venato import tools
    import importlib
    tools = importlib.reload(tools)
    store.add_todo("Email Priya about the thesis", "weekly", "2026-10-28")
    store.save_journal("2026-10-22", "Long day. Priya fixed the 50% bug")
    store.add_deadline("Thesis draft", "2026-11-20")
    tools.add_block("2026-10-29", "plan", "14:00", "16:00", "Thesis writing", category="Study")
    store.add_habit("Read")


def test_search_everything(store):
    seed(store)
    kinds = lambda q: sorted(r["kind"] for r in store.search(q))
    assert kinds("priya") == ["Journal", "To-do"]
    assert kinds("THESIS") == ["Deadline", "Timetable", "To-do"]
    assert kinds("thesis priya") == ["To-do"]                         # every word must match
    assert kinds("50%") == ["Journal"] and store.search("5_%") == []  # wildcards are just characters
    assert store.search("  ") == [] and kinds("read") == ["Habit"]


def test_search_box_and_open(store):
    seed(store)
    at = AppTest.from_file(APP, default_timeout=60).run()
    assert at.sidebar.text_input(key="global_search")                 # in the sidebar, off Home
    at.sidebar.radio[0].set_value("Goals").run()                       # on every page
    at.text_input(key="global_search").set_value("thesis writing").run()
    assert not at.exception
    opens = [b for b in at.button if b.key and b.key.startswith("search_open_")]
    assert opens and all(b.label and b.label != "Open" for b in opens)  # the result itself is the button
    next(b for b in at.button if b.key and "Timetable" in b.key).click().run()
    assert at.sidebar.radio[0].value == "Timetable" and str(at.session_state["tt_day"]) == "2026-10-29"
    at.text_input(key="global_search").set_value("priya").run()
    next(b for b in at.button if b.key and "To-do" in b.key).click().run()
    assert not at.exception and at.sidebar.radio[0].value == "Home"     # to-dos live on Home
