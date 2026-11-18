"""With Daily Log off (a new install), Review and search show none of its content; with it on, they do."""

from pathlib import Path

from streamlit.testing.v1 import AppTest

APP = str(Path(__file__).resolve().parents[1] / "app.py")
LOG_TILES = ("Avg mood", "Avg sleep", "Avg energy", "Avg productivity", "Avg water", "Habits on target")


def _seed(store):
    from venato import review
    today = store.local_today()
    store.add_habit("Stretch")
    store.save_journal(today.isoformat(), "Wrote about stretching")
    return store.week_start_of(today), review


def _texts(at):
    return [*(m.label for m in at.metric), *(c.value for c in at.caption), *(i.value for i in at.info),
            *(p.proto.popover.label for p in at.get("popover"))]


def _review_page(at, view="Trends"):
    at.session_state["rv_view"] = view
    at.sidebar.radio[0].set_value("Review").run()
    assert not at.exception
    return _texts(at)


def _search(store, at, q):
    at.sidebar.radio[0].set_value("Home").run()
    at.text_input(key="global_search").set_value(q).run()
    assert not at.exception
    return at


def test_starter_only_install(store, monkeypatch):
    week, review = _seed(store)
    store.save_settings(blocks=[])
    monkeypatch.setattr(review, "due_week", lambda now=None: week)
    at = AppTest.from_file(APP, default_timeout=60).run()      # the Sunday pop-up draws the week's review
    assert not at.exception
    popup = _texts(at)
    assert not any(t in LOG_TILES for t in popup) and not any("journal entr" in t for t in popup)
    assert not any("journal entr" in t for t in _review_page(at, "Week"))
    page = _review_page(at)
    assert not any(t in LOG_TILES for t in page) and "No entries in this period yet." not in page
    assert not any("Daily log filled in" in t for t in page)
    assert not any(m.value == "**Habits**" or m.value.startswith("**Journal**") for m in at.markdown)
    s = review.summary(week)
    assert s["habits"] == [] and s["journal"] == [] and s["days_logged"] == 0
    assert "Habits:" not in review.as_text(s) and "Journal" not in review.as_text(s)
    for q in ("stretch", "stretching"):
        _search(store, at, q)
        assert not [b for b in at.button if b.key and ("Habit" in b.key or "Journal" in b.key)]
        assert not any(m.value.startswith("1 result") for m in at.caption)
    assert store.search("stretch") == [] and store.search("stretching") == []


def test_log_on_shows_it(store, monkeypatch):
    week, review = _seed(store)
    store.save_settings(blocks=["log"])
    monkeypatch.setattr(review, "due_week", lambda now=None: week)
    at = AppTest.from_file(APP, default_timeout=60).run()
    assert not at.exception
    popup = _texts(at)
    assert "1 journal entry ›" in popup                       # the week's journal, behind a link
    assert "1 journal entry ›" in _review_page(at, "Week")
    page = _review_page(at)
    assert "Avg mood" in page
    assert sorted(r["kind"] for r in store.search("stretch")) == ["Habit", "Journal"]
    _search(store, at, "stretch")
    assert [b for b in at.button if b.key and "Habit" in b.key]
    next(b for b in at.button if b.key and "Habit" in b.key).click().run()
    assert at.sidebar.radio[0].value == "Daily Log"


def test_log_on_with_nothing_logged_says_so(store):
    store.save_settings(blocks=["log"])
    at = AppTest.from_file(APP, default_timeout=60).run()
    assert "No entries in this period yet." in _review_page(at)
