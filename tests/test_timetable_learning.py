"""
Timetable: labels and calendar events that mean a category (matched as words, learnt from what the user
picks), the Add event dialog, and done / not done marks. Uses the `store` fixture (the example categories).
"""

from datetime import timedelta
from pathlib import Path

from streamlit.testing.v1 import AppTest
from nav_helpers import goto

APP = str(Path(__file__).resolve().parents[1] / "app.py")


def test_labels_match_words_inside_and_learn(store):
    assert store.resolve_category(label="Rugby training") is None
    store.set_label_default("Rugby", "exercise")
    assert store.match_category("Rugby training") == "exercise"            # an activity, as a word
    assert store.match_category("rugby") == "exercise"
    assert store.match_category("Rugbyball") is None                       # not part of a word
    assert store.match_category("Maths revision") == "study"               # 'Revision' -> Study
    assert store.match_category("Lunch with Sam") == "meals"
    assert store.match_category("Lecture: Study skills") == "classes"      # an activity beats a category name
    assert store.match_category("Commute to classes") == "commute"         # ... even a longer one
    assert store.resolve_category(label="Rugby training") == "exercise"
    # Saving a block teaches its label; one that already means its category isn't stored again.
    assert store.learn_label("Football", "exercise") is True
    assert store.match_category("Football practice") == "exercise"
    assert store.learn_label("Rugby training", "exercise") is False
    assert store.learn_label("Lunch", "social") is True                    # a correction wins
    assert store.match_category("Lunch") == "social"
    assert store.learn_label("", "exercise") is False and store.learn_label("X", "nope") is False


def test_calendar_events_get_the_category_their_title_means(store):
    store.set_label_default("Boxing", "exercise")
    assert store.event_category({"title": "Boxing"}) == "exercise"
    assert store.event_category({"title": "Boxing club"}, "classes") == "exercise"
    assert store.event_category({"title": "Chemistry 101"}, "classes") == "classes"     # nothing in it: the default
    assert store.event_category({"title": "Boxing", "module_category": "m1"}) == "m1"   # a module's wins
    store.learn_label("Chemistry", "study")                                             # learnt later: seen at once
    assert store.event_category({"title": "Chemistry 101"}, "classes") == "study"


def test_old_word_rules_become_activities(store):
    with store.db() as conn:
        conn.execute("CREATE TABLE category_rules (id INTEGER PRIMARY KEY, word TEXT, category_id TEXT)")
        conn.executemany("INSERT INTO category_rules (word, category_id) VALUES (?, ?)",
                         [("Squash", "exercise"), ("lunch", "social")])
    store.init_db()
    assert store.match_category("Squash with Tom") == "exercise"
    assert store.match_category("Lunch") == "meals"                        # one already set is kept


def test_block_done_or_missed(store):
    from venato.ui import timetable
    day = store.local_today().isoformat()
    op = {"kind": "set_status", "id": "b1", "status": "done", "date": day, "start": "09:00", "end": "10:00",
          "label": "Boxing", "categoryId": "exercise"}
    timetable.apply_grid_op(op)
    timetable.apply_grid_op({**op, "id": "outlook:abc", "status": "missed", "label": "Lecture"})
    assert store.block_statuses(day, day) == {"b1": "done", "outlook:abc": "missed"}
    log = store.status_log()
    assert [(r["label"], r["status"], r["start"]) for r in log] == [("Boxing", "done", "09:00"),
                                                                     ("Lecture", "missed", "09:00")]
    timetable.apply_grid_op({**op, "status": None})        # pressed again: cleared
    assert store.block_statuses(day, day) == {"outlook:abc": "missed"}


def test_add_event_dialog(store):
    from venato import tools
    tomorrow = store.local_today() + timedelta(days=1)
    at = AppTest.from_file(APP, default_timeout=60).run()
    goto(at, "Timetable")
    assert not at.exception, at.exception
    at.button(key="tt_btn_add").click().run()
    assert not at.exception, at.exception
    assert [t.label for t in at.text_input if t.label == "What"] == ["What"]       # the dialog is open
    assert {"Starts", "Ends", "Category"} <= {s.label for s in at.selectbox}
    # What its Add button does (AppTest closes a dialog on the run after a click, so call it here):
    r = tools.add_block(tomorrow.isoformat(), "plan", "18:00", "19:30", "Gym session", confirmed=True)
    assert r.changed
    got = [(b["start"], b["end"], b["category_id"]) for b in store.blocks_between(tomorrow.isoformat(), tomorrow.isoformat(), "plan")
           if b["label"] == "Gym session"]
    assert got == [("18:00", "19:30", "exercise")]                       # 'Gym' inside the name -> its category
    tools.add_block(tomorrow.isoformat(), "plan", "20:00", "21:00", "Pottery", category="Social", confirmed=True)
    assert store.match_category("Pottery") == "social"                    # picked by hand: learnt
