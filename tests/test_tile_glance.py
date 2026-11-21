"""Home tiles' small glances: the journal's week of dots and streak, habit streaks, deadline pills, Review's
day letters, and the glance helpers themselves."""

from datetime import timedelta
from pathlib import Path

from streamlit.testing.v1 import AppTest

APP = str(Path(__file__).resolve().parents[1] / "app.py")


def html(at):
    return " ".join(h.proto.body for h in at.get("html"))


def test_glance_helpers(store):
    from venato.ui import glance
    out = glance.dots([True, False, True], "Written 2 of 3", ["M", "T", "W"])
    assert out.count('class="on"') == 2 and 'aria-label="Written 2 of 3"' in out and "<b>W</b>" in out
    assert glance.pill("Today", "red") == ":red-badge[Today]"
    assert glance.pill("in 2 days", "amber") == ":orange-badge[in 2 days]"
    assert glance.pill("in 9 days", "grey") == ":gray-badge[in 9 days]"
    assert glance.pill("odd]", "nope") == ":gray-badge[odd]"


def test_journal_week_and_streak(store):
    from venato import pace, tile_status
    today = store.local_today()
    w = tile_status.journal_week(today)
    assert [d for d, _ in w["days"]] == [d.isoformat() for d in pace.week_days(today)]
    assert not any(f for _, f in w["days"]) and w["streak"] == 0
    for back in (1, 2, 3):                                    # yesterday and the two days before
        store.save_journal(today - timedelta(days=back), "Wrote something")
    w = tile_status.journal_week(today)
    assert w["streak"] == 3                                   # today not written yet: still counts to yesterday
    written = {d for d, f in w["days"] if f}
    week = {d.isoformat() for d in pace.week_days(today)}
    assert written == {(today - timedelta(days=b)).isoformat() for b in (1, 2, 3)} & week


def test_habit_streak_matches_the_daily_log(store):
    from venato import tile_status
    today = store.local_today()
    store.add_habit("Exercise")
    hid = store.find_habit("Exercise")[0]
    with store.db() as conn:
        for back in range(5):
            store.set_habit_done(conn, hid, (today - timedelta(days=back)).isoformat(), True)
    assert tile_status.habit_streak(hid, today) == 5
    assert store.habit_progress(hid, store.get_habit_dates(hid), today)[1] == 5


def test_deadline_pill_tones(store):
    from venato.ui import deadlines
    today = store.local_today()
    tone = lambda n: deadlines._pill_tone({"due": (today + timedelta(days=n)).isoformat(), "due_time": None}, today)
    assert [tone(n) for n in (-2, 0, 1, 3, 4, 10)] == ["red", "red", "amber", "amber", "grey", "grey"]


def test_tiles_render_their_glances(store):
    today = store.local_today()
    store.save_settings(blocks=["timetable", "goals", "log", "stats"],
                        home=[{"w": k, "size": "s"} for k in ("journal", "habits", "deadlines", "review")])
    store.add_habit("Exercise")
    hid = store.find_habit("Exercise")[0]
    with store.db() as conn:
        for back in range(1, 4):
            store.set_habit_done(conn, hid, (today - timedelta(days=back)).isoformat(), True)
    for back in (0, 1):
        store.save_journal(today - timedelta(days=back), "Wrote something")
    store.add_deadline("Essay", today + timedelta(days=2))
    at = AppTest.from_file(APP, default_timeout=60).run()
    assert not at.exception
    page = html(at)
    assert 'class="vn-dots"' in page and "days this week" in page           # Journal: the week's dots
    assert any(c.value == "2-day streak" for c in at.caption)
    assert any(c.label == "Exercise · 3" for c in at.checkbox)                # Daily log: the streak after the name
    assert any(":orange-badge[in 2 days]" in m.value for m in at.markdown)   # Deadlines: an amber pill
    assert 'class="vn-rv-days"' in page and "dashed line is 100%" in page    # Review: letters and the 100% line
    letters = page.split('class="vn-rv-days"')[1].split("</div>")[0]
    assert letters.count("<b>") == 7
