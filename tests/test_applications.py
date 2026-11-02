from datetime import date

from pathlib import Path

import pytest
from streamlit.testing.v1 import AppTest

APP = str(Path(__file__).resolve().parents[1] / "app.py")


def test_add_list_update_delete(store):
    a = store.add_application(company="  Acme  ", industry="Finance", route="Internship",
                              deadline="2026-12-01", contact="Priya")
    b = store.add_application(company="Beta", status="Applied")
    store.add_application(company="Gamma", deadline=date(2026, 11, 20))
    rows = store.applications()
    assert [r["company"] for r in rows] == ["Gamma", "Acme", "Beta"]       # soonest deadline first, none last
    assert rows[1]["status"] == "To apply" and rows[1]["contact"] == "Priya"
    store.update_application(a, status="Interview", notes="Round 2 on Friday", deadline=None)
    got = store.get_application(a)
    assert got["status"] == "Interview" and got["deadline"] is None and got["notes"] == "Round 2 on Friday"
    store.update_application(b, deadline="2026-11-05T00:00:00", company="")   # table dates come back as timestamps
    assert store.get_application(b)["deadline"] == "2026-11-05" and store.get_application(b)["company"] is None
    store.delete_application(a)
    assert store.get_application(a) is None and len(store.applications()) == 2


def test_rules(store):
    with pytest.raises(ValueError):
        store.add_application(notes="just notes")              # nothing saying what it is
    with pytest.raises(ValueError):
        store.add_application(company="Acme", status="Maybe")
    aid = store.add_application(company="Acme", notes="nan")   # pandas' empty cell
    assert store.get_application(aid)["notes"] is None


def test_search_finds_applications(store):
    store.add_application(company="Acme Bank", route="Graduate scheme", contact="Sam Lee", status="Applied")
    hits = [h for h in store.search("sam") if h["kind"] == "Application"]
    assert hits and hits[0]["title"] == "Acme Bank" and hits[0]["detail"] == "Graduate scheme · Applied"


def test_page_and_table_edits(store):
    store.add_application(company="Acme", status="Applied", deadline="2099-01-01")
    at = AppTest.from_file(APP, default_timeout=60).run()
    at.sidebar.radio[0].set_value("Applications").run()
    assert not at.exception
    assert list(at.sidebar.radio[0].options).index("Applications") == list(at.sidebar.radio[0].options).index("Network") - 1
    assert list(at.sidebar.radio[0].options).index("Network") < list(at.sidebar.radio[0].options).index("Stats")
    assert any("1 in total" in c.value for c in at.caption)

    # What the table's on_change gets: edits by row number, deleted row numbers.
    from venato.ui import applications as ui
    from venato import undo
    store.add_application(company="Beta")
    ids = [r["id"] for r in store.applications()]                 # Acme (has a deadline), Beta
    ui.apply_edits({"edited_rows": {0: {"Status": "Interview", "Deadline": "2099-02-01"}, 1: {"Route": "Spring week"}},
                    "added_rows": [], "deleted_rows": []}, ids)
    rows = {r["company"]: r for r in store.applications()}
    assert rows["Acme"]["status"] == "Interview" and rows["Acme"]["deadline"] == "2099-02-01"
    assert rows["Beta"]["route"] == "Spring week"
    ui.apply_edits({"edited_rows": {}, "added_rows": [], "deleted_rows": [0]}, ids)
    assert [r["company"] for r in store.applications()] == ["Beta"] and undo.pending() == "Deleted Acme"
    undo.restore()
    assert len(store.applications()) == 2
