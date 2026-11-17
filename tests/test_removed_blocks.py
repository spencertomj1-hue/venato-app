"""A block whose files are gone (the public app without Applications and Network) leaves its
tables and rows alone, and nothing shared still reads them: start-up, search and the weekly review."""

from datetime import date

GONE = {"applications", "network"}


def test_old_tables_without_blocks(store, monkeypatch):
    with store.db() as conn:                       # rows a fuller copy of the app left behind
        conn.execute("INSERT INTO applications (id, company, status, created_at, updated_at) "
                     "VALUES ('a1', 'Acme', 'Applied', '2026-10-01', '2026-10-01')")
        conn.execute("INSERT INTO net_people (id, name, works_for, created_at) VALUES ('p1', 'Sam', 'Acme', '2026-10-01')")
        conn.execute("INSERT INTO net_interactions VALUES ('i1', 'p1', '2026-10-21', 'Coffee at Acme', '2026-10-21')")
    from venato import blocks, review
    every = blocks.all_blocks()
    monkeypatch.setattr(blocks, "all_blocks", lambda: [b for b in every if b.key not in GONE])

    store.init_db()                                # starts fine, and keeps what's there
    with store.db() as conn:
        assert conn.execute("SELECT COUNT(*) FROM applications").fetchone()[0] == 1
        assert conn.execute("SELECT COUNT(*) FROM net_people").fetchone()[0] == 1
    assert not {r["kind"] for r in store.search("Acme")} & {"Application", "Person", "Met"}
    s = review.summary(date(2026, 10, 19))
    assert not [x for x in s["sections"] if x["key"] in GONE]
    assert "Sam" not in review.as_text(s)
