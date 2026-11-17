"""Blocks whose files are gone (Food, Recipes, Health, Involvement, Cut down, Applications, Network) leave their
tables and rows alone, and nothing shared still reads them: start-up, search and the weekly review."""

import importlib
from datetime import date

import pytest


@pytest.mark.parametrize("name", ["network", "applications", "food", "recipes", "health", "involvement", "cutdown"])
def test_the_modules_are_gone(name):
    with pytest.raises(ImportError):
        importlib.import_module(f"venato.blocks.{name}")


def test_old_tables_without_blocks(store):
    with store.db() as conn:                       # tables and rows an older copy of the app left behind
        conn.executescript("""
            CREATE TABLE applications (id TEXT PRIMARY KEY, company TEXT, status TEXT, created_at TEXT, updated_at TEXT);
            CREATE TABLE net_people (id TEXT PRIMARY KEY, name TEXT, works_for TEXT, created_at TEXT);
            CREATE TABLE net_interactions (id TEXT PRIMARY KEY, person_id TEXT, day TEXT, note TEXT, created_at TEXT);
            INSERT INTO applications VALUES ('a1', 'Acme', 'Applied', '2026-10-01', '2026-10-01');
            INSERT INTO net_people VALUES ('p1', 'Sam', 'Acme', '2026-10-01');
            INSERT INTO net_interactions VALUES ('i1', 'p1', '2026-10-21', 'Coffee at Acme', '2026-10-21');
        """)
    from venato import blocks, review
    importlib.reload(blocks)
    store.init_db()                                # starts fine, and keeps what's there
    with store.db() as conn:
        assert conn.execute("SELECT COUNT(*) FROM applications").fetchone()[0] == 1
        assert conn.execute("SELECT COUNT(*) FROM net_people").fetchone()[0] == 1
        assert conn.execute("SELECT COUNT(*) FROM net_interactions").fetchone()[0] == 1
    assert not {r["kind"] for r in store.search("Acme")} & {"Application", "Person", "Group", "Met"}
    assert not {r["kind"] for r in store.search("Sam")} & {"Application", "Person", "Group", "Met"}
    s = review.summary(date(2026, 10, 19))
    assert not [x for x in s["sections"] if x["key"] in {"applications", "network"}]
    assert "Sam" not in review.as_text(s)
